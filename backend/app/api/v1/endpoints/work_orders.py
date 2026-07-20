"""
Work Order workflow endpoints.

GET  /work-orders/                                             — list all work orders with current status
GET  /work-orders/{work_order_number}                          — work order detail + event history
POST /work-orders/{work_order_number}/send-to-assembly         — OH bulk-sends all eligible LPTR blades to Assembly
POST /work-orders/{work_order_number}/assign-slot               — bulk-assigns computed disc slots (LPTR algorithmic / HPTR explicit)
POST /work-orders/{work_order_number}/complete-hptr-balancing   — mark a saved HPTR slot allocation balanced/complete
POST /work-orders/{work_order_number}/reset-hptr-slots          — undo a saved HPTR slot allocation, redo from scratch
GET  /work-orders/{work_order_number}/rocking-creep              — blades with slot numbers + rocking/creep values
POST /work-orders/{work_order_number}/receive                   — Assembly marks work order received
POST /work-orders/{work_order_number}/accept                    — Assembly accepts work order
POST /work-orders/{work_order_number}/reject                    — Assembly rejects work order
POST /work-orders/{work_order_number}/modify                    — Assembly corrects blade-level fields

POST /work-orders/                                              — create a Work Order + scaffold 90 blade rows (grid entry)
GET  /work-orders/{work_order_number}/entry                     — grid-entry resume/detail (rows + completion state)
PUT  /work-orders/{work_order_number}/rows/{s_no}                — autosave a single grid row
POST /work-orders/{work_order_number}/complete                  — validate + bulk-transition grid entry to MEASUREMENTS_RECORDED
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import _user_role_names, get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import BatchEventType, BladeStatus, BladeType, MeasurementType, NotificationType
from app.schemas.work_order import (
    WorkOrderCompleteResponse,
    WorkOrderCreate,
    WorkOrderDetailResponse,
    WorkOrderRowResponse,
    WorkOrderRowUpdate,
)
from app.services.work_order_service import WorkOrderService

logger = structlog.get_logger(__name__)
router = APIRouter()

# Statuses that mean "blade is with assembly"
_ASSEMBLY_STATUSES = {
    BladeStatus.SENT_TO_ASSEMBLY,
    BladeStatus.SLOT_ASSIGNED,
    BladeStatus.BALANCING_IN_PROGRESS,
    BladeStatus.BALANCING_COMPLETED,
}


def _derive_status(latest_event_type: BatchEventType | None, blades_sent: int) -> str:
    """Compute display status from latest event + blade count in assembly."""
    if latest_event_type:
        return latest_event_type.value
    if blades_sent > 0:
        return "SENT_TO_ASSEMBLY"
    return "CREATED"


def _status_label(status_val: str) -> str:
    return {
        "CREATED": "Created",
        "MEASUREMENTS_RECORDED": "Measurements Recorded",
        "SENT_TO_ASSEMBLY": "Sent to Assembly",
        "RECEIVED_BY_ASSEMBLY": "Received by Assembly",
        "ACCEPTED": "Accepted",
        "REJECTED": "Rejected",
        "MODIFIED": "Modified",
        "SLOTS_ALLOCATED": "Slots Allocated",
        "SET_MAKING": "Set Making",
        "BALANCED": "Balanced",
    }.get(status_val, status_val)


def _event_to_dict(ev: Any) -> dict:
    return {
        "id": str(ev.id),
        "work_order_number": ev.work_order_number,
        "event_type": ev.event_type.value,
        "action_by": (
            {
                "id": str(ev.action_by.id),
                "username": ev.action_by.username,
                "full_name": ev.action_by.full_name,
            }
            if ev.action_by
            else None
        ),
        "remarks": ev.remarks,
        "changes": ev.changes,
        "timestamp": ev.timestamp.isoformat(),
    }


async def _notify_oh_operators(
    work_order_number: str,
    event_type: BatchEventType,
    actor_username: str,
    remarks: str | None,
    changes: dict | None = None,
) -> None:
    """Send notification to all OH_OPERATORs and SUPER_ADMINs about a work order event.

    Opens its own DB session — safe to call from BackgroundTasks after the
    request session has already been closed.
    """
    from app.models.user import User, UserRole as UserRoleModel, Role
    from app.notifications.service import NotificationService
    from app.db.session import AsyncSessionLocal

    event_labels = {
        BatchEventType.RECEIVED_BY_ASSEMBLY: "Received by Assembly",
        BatchEventType.ACCEPTED: "Accepted",
        BatchEventType.REJECTED: "Rejected",
        BatchEventType.MODIFIED: "Modified",
    }

    title = f"Work Order {work_order_number} — {event_labels.get(event_type, event_type.value)}"
    body = f"Assembly has marked Work Order {work_order_number} as {event_labels.get(event_type, event_type.value).lower()}."
    if remarks:
        body += f" Remarks: {remarks}"

    if event_type == BatchEventType.MODIFIED and changes:
        blade_serials = list(changes.keys())
        body += f" Modified blade(s): {', '.join(blade_serials)}."
        for sn, blade_changes in changes.items():
            field_parts = []
            for field, diff in blade_changes.items():
                if isinstance(diff, dict) and "before" in diff and "after" in diff:
                    field_parts.append(f"{field}: {diff['before']} → {diff['after']}")
            if field_parts:
                body += f" [{sn}: {', '.join(field_parts)}]"

    body += f" (by {actor_username})"

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User)
                .join(UserRoleModel, UserRoleModel.user_id == User.id)
                .join(Role, Role.id == UserRoleModel.role_id)
                .where(
                    Role.name.in_(["OH_OPERATOR", "SUPER_ADMIN"]),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
                .distinct()
            )
            target_users = list(result.scalars().all())

            svc = NotificationService(db)
            for user in target_users:
                await svc.create_notification(
                    user_id=user.id,
                    title=title,
                    body=body,
                    notification_type=NotificationType.WORKFLOW_UPDATED,
                )

        logger.info(
            "work_order_notification_sent",
            work_order=work_order_number,
            event_type=event_type.value,
            recipients=len(target_users),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("work_order_notification_failed", error=str(exc))


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("/", status_code=status.HTTP_200_OK, summary="List all work orders with current status")
async def list_work_orders(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    has_slot_allocations: bool = False,
) -> list:
    """
    Return a summary of every work order known to the system, ordered by most
    recently created.  The ``current_status`` field reflects:
    - The latest explicit Assembly action (RECEIVED/ACCEPTED/REJECTED/MODIFIED), or
    - ``SENT_TO_ASSEMBLY`` if any blades have been sent, or
    - ``CREATED`` otherwise.

    A Work Order is always exactly one ``blade_type`` (LPTR or HPTR), so the
    per-work-order LPTR/HPTR split is read directly off ``WorkOrder.blade_type``
    rather than re-derived from a mixed blade population.
    """
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.work_order import WorkOrder
    from app.models.work_order_event import WorkOrderEvent
    from app.models.workflow import WorkflowLog

    # ── Blade counts per work order ────────────────────────────────────────
    blade_rows = (
        await db.execute(
            select(
                Blade.work_order_number,
                func.count(Blade.id).label("blade_count"),
                func.sum(
                    case(
                        (Blade.status.in_(list(_ASSEMBLY_STATUSES)), 1),
                        else_=0,
                    )
                ).label("blades_in_assembly_statuses"),
                func.sum(
                    case(
                        (Blade.status == BladeStatus.COMPLETED, 1),
                        else_=0,
                    )
                ).label("blades_completed"),
                func.max(Blade.nomenclature).label("nomenclature"),
                func.min(Blade.created_at).label("first_blade_at"),
            )
            .where(Blade.work_order_number.isnot(None), Blade.deleted_at.is_(None))
            .group_by(Blade.work_order_number)
            .order_by(func.min(Blade.created_at).desc())
        )
    ).all()

    if not blade_rows:
        return []

    # If caller only wants work orders with at least one active slot allocation, filter here
    if has_slot_allocations:
        from app.models.slot_allocation import SlotAllocation
        slotted = set(
            (
                await db.execute(
                    select(Blade.work_order_number)
                    .join(SlotAllocation, SlotAllocation.blade_id == Blade.id)
                    .where(
                        SlotAllocation.is_active.is_(True),
                        Blade.deleted_at.is_(None),
                        Blade.work_order_number.isnot(None),
                    )
                    .distinct()
                )
            ).scalars().all()
        )
        blade_rows = [r for r in blade_rows if r.work_order_number in slotted]
        if not blade_rows:
            return []

    work_order_numbers = [r.work_order_number for r in blade_rows]

    # ── Rows actually entered (Melt Number + Weight both present) per work
    # order — NOT the same as blade_count, which is the fixed 90-row scaffold
    # created up front and is nonzero from the moment a Work Order starts. ──
    complete_rows = (
        await db.execute(
            select(
                Blade.work_order_number,
                func.count(Blade.id).label("rows_complete_count"),
            )
            .join(
                Measurement,
                (Measurement.blade_id == Blade.id)
                & (Measurement.measurement_type == MeasurementType.INITIAL),
            )
            .where(
                Blade.work_order_number.in_(work_order_numbers),
                Blade.deleted_at.is_(None),
                Blade.melt_number.isnot(None),
                func.trim(Blade.melt_number) != "",
                Measurement.weight_grams.isnot(None),
            )
            .group_by(Blade.work_order_number)
        )
    ).all()
    rows_complete_map: dict[str, int] = {
        r.work_order_number: r.rows_complete_count for r in complete_rows
    }

    # ── Latest event per work order ────────────────────────────────────────
    latest_evt_subq = (
        select(
            WorkOrderEvent,
            func.row_number().over(
                partition_by=WorkOrderEvent.work_order_number,
                order_by=WorkOrderEvent.timestamp.desc(),
            ).label("rn"),
        )
        .where(WorkOrderEvent.work_order_number.in_(work_order_numbers))
        .subquery()
    )
    latest_events_rows = (
        await db.execute(
            select(WorkOrderEvent)
            .where(
                WorkOrderEvent.work_order_number.in_(work_order_numbers),
                WorkOrderEvent.id.in_(
                    select(latest_evt_subq.c.id).where(latest_evt_subq.c.rn == 1)
                ),
            )
        )
    ).scalars().all()
    latest_event_map: dict[str, Any] = {ev.work_order_number: ev for ev in latest_events_rows}

    # ── First SENT timestamp per work order ────────────────────────────────
    sent_rows = (
        await db.execute(
            select(
                Blade.work_order_number,
                func.min(WorkflowLog.timestamp).label("first_sent_at"),
            )
            .join(WorkflowLog, WorkflowLog.blade_id == Blade.id)
            .where(
                Blade.work_order_number.in_(work_order_numbers),
                WorkflowLog.to_status == BladeStatus.SENT_TO_ASSEMBLY,
            )
            .group_by(Blade.work_order_number)
        )
    ).all()
    sent_at_map = {r.work_order_number: r.first_sent_at for r in sent_rows}

    # ── WorkOrder header metadata (replaces the old BatchGroup autofill cache) ──
    wo_rows = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number.in_(work_order_numbers))
        )
    ).scalars().all()
    wo_map: dict[str, Any] = {wo.work_order_number: wo for wo in wo_rows}

    # ── HPTR blades already slot-allocated per work order (active allocations).
    # A Work Order is always exactly one blade_type, so this only ever
    # produces rows for work orders whose header is HPTR — computed by
    # scoping the queries to HPTR work order numbers up front. ──
    from app.models.slot_allocation import SlotAllocation

    hptr_work_order_numbers = [
        wn for wn in work_order_numbers
        if wo_map.get(wn) is not None and wo_map[wn].blade_type == BladeType.HPTR
    ]

    hptr_slotted_map: dict[str, int] = {}
    hptr_balanced_map: dict[str, int] = {}
    if hptr_work_order_numbers:
        hptr_slotted_rows = (
            await db.execute(
                select(
                    Blade.work_order_number,
                    func.count(SlotAllocation.id).label("hptr_slotted_count"),
                )
                .join(SlotAllocation, SlotAllocation.blade_id == Blade.id)
                .where(
                    Blade.work_order_number.in_(hptr_work_order_numbers),
                    SlotAllocation.is_active.is_(True),
                )
                .group_by(Blade.work_order_number)
            )
        ).all()
        hptr_slotted_map = {r.work_order_number: r.hptr_slotted_count for r in hptr_slotted_rows}

        # ── HPTR blades that have finished balancing (or moved beyond it) ──
        _HPTR_BALANCED_STATUSES = [
            BladeStatus.BALANCING_COMPLETED,
            BladeStatus.RETURNED_TO_OH,
            BladeStatus.FINAL_VERIFICATION,
            BladeStatus.COMPLETED,
        ]
        hptr_balanced_rows = (
            await db.execute(
                select(
                    Blade.work_order_number,
                    func.count(Blade.id).label("hptr_balanced_count"),
                )
                .where(
                    Blade.work_order_number.in_(hptr_work_order_numbers),
                    Blade.deleted_at.is_(None),
                    Blade.status.in_(_HPTR_BALANCED_STATUSES),
                )
                .group_by(Blade.work_order_number)
            )
        ).all()
        hptr_balanced_map = {r.work_order_number: r.hptr_balanced_count for r in hptr_balanced_rows}

    # ── Assemble response ──────────────────────────────────────────────────
    result = []
    for row in blade_rows:
        wn = row.work_order_number
        latest_ev = latest_event_map.get(wn)
        wo = wo_map.get(wn)
        blade_type = wo.blade_type if wo is not None else None
        # blades_sent / hptr_count collapse to a direct read of
        # WorkOrder.blade_type now that one work order is one blade type —
        # no more per-row blade_type case-summation needed.
        blades_sent = (row.blades_in_assembly_statuses or 0) if blade_type == BladeType.LPTR else 0
        hptr_count = row.blade_count if blade_type == BladeType.HPTR else 0
        cur_status = _derive_status(latest_ev.event_type if latest_ev else None, blades_sent)
        result.append({
            "work_order_number": wn,
            "blade_type": blade_type.value if blade_type else None,
            "blade_count": row.blade_count,
            "rows_complete_count": rows_complete_map.get(wn, 0),
            "blades_sent": blades_sent,
            "blades_completed": row.blades_completed or 0,
            "hptr_count": hptr_count,
            "hptr_slotted_count": hptr_slotted_map.get(wn, 0),
            "hptr_balanced_count": hptr_balanced_map.get(wn, 0),
            "current_status": cur_status,
            "current_status_label": _status_label(cur_status),
            "first_blade_at": row.first_blade_at.isoformat() if row.first_blade_at else None,
            "first_sent_at": sent_at_map.get(wn, None) and sent_at_map[wn].isoformat(),
            "last_event": _event_to_dict(latest_ev) if latest_ev else None,
            "shop_order_number": wo.shop_order_number if wo else None,
            "part_number": wo.part_number if wo else None,
            "engine_number": wo.engine_number if wo else None,
            "nomenclature": row.nomenclature,
            "is_entry_complete": wo.is_entry_complete if wo else False,
        })
    return result


# ---------------------------------------------------------------------------
# GET /{work_order_number}
# ---------------------------------------------------------------------------


@router.get("/{work_order_number}", status_code=status.HTTP_200_OK, summary="Work order detail with event history")
async def get_work_order(
    work_order_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Return full detail for a single work order: metadata, blade list summary,
    and the complete event history (most recent first).
    """
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.work_order import WorkOrder
    from app.models.work_order_event import WorkOrderEvent
    from app.models.workflow import WorkflowLog

    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )

    # Rows actually entered (Melt Number + Weight both present) — NOT the
    # same as blade_count, which is the fixed 90-row scaffold created up front.
    rows_complete_count = (
        await db.execute(
            select(func.count(Blade.id))
            .select_from(Blade)
            .join(
                Measurement,
                (Measurement.blade_id == Blade.id)
                & (Measurement.measurement_type == MeasurementType.INITIAL),
            )
            .where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                Blade.melt_number.isnot(None),
                func.trim(Blade.melt_number) != "",
                Measurement.weight_grams.isnot(None),
            )
        )
    ).scalar_one()

    blade_agg = (
        await db.execute(
            select(
                func.count(Blade.id).label("blade_count"),
                func.sum(
                    case(
                        (Blade.status.in_(list(_ASSEMBLY_STATUSES)), 1),
                        else_=0,
                    )
                ).label("blades_in_assembly_statuses"),
                func.sum(
                    case(
                        (Blade.status == BladeStatus.COMPLETED, 1),
                        else_=0,
                    )
                ).label("blades_completed"),
                func.max(Blade.nomenclature).label("nomenclature"),
                func.min(Blade.created_at).label("first_blade_at"),
            )
            .where(Blade.work_order_number == work_order_number, Blade.deleted_at.is_(None))
        )
    ).one()

    # Events — newest first
    events = (
        await db.execute(
            select(WorkOrderEvent)
            .where(WorkOrderEvent.work_order_number == work_order_number)
            .order_by(WorkOrderEvent.timestamp.desc())
        )
    ).scalars().all()

    # First sent timestamp
    sent_row = (
        await db.execute(
            select(func.min(WorkflowLog.timestamp).label("first_sent_at"))
            .join(Blade, Blade.id == WorkflowLog.blade_id)
            .where(
                Blade.work_order_number == work_order_number,
                WorkflowLog.to_status == BladeStatus.SENT_TO_ASSEMBLY,
            )
        )
    ).one()

    latest_ev = events[0] if events else None
    # blades_sent collapses to a direct read of WorkOrder.blade_type — HPTR
    # work orders never show blades as "sent to assembly".
    blades_sent = (blade_agg.blades_in_assembly_statuses or 0) if work_order.blade_type == BladeType.LPTR else 0
    cur_status = _derive_status(latest_ev.event_type if latest_ev else None, blades_sent)

    return {
        "work_order_number": work_order_number,
        "blade_type": work_order.blade_type.value,
        "blade_count": blade_agg.blade_count,
        "rows_complete_count": rows_complete_count,
        "blades_sent": blades_sent,
        "blades_completed": blade_agg.blades_completed or 0,
        "current_status": cur_status,
        "current_status_label": _status_label(cur_status),
        "first_blade_at": blade_agg.first_blade_at.isoformat() if blade_agg.first_blade_at else None,
        "first_sent_at": sent_row.first_sent_at.isoformat() if sent_row.first_sent_at else None,
        "last_event": _event_to_dict(latest_ev) if latest_ev else None,
        "events": [_event_to_dict(ev) for ev in events],
        "shop_order_number": work_order.shop_order_number,
        "part_number": work_order.part_number,
        "engine_number": work_order.engine_number,
        "nomenclature": blade_agg.nomenclature,
        "is_entry_complete": work_order.is_entry_complete,
    }


# ---------------------------------------------------------------------------
# Shared action helper
# ---------------------------------------------------------------------------


async def _create_work_order_event(
    work_order_number: str,
    event_type: BatchEventType,
    remarks: str | None,
    changes: dict | None,
    current_user: Any,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> dict:
    """Create a WorkOrderEvent, commit it, fire notifications, return dict."""
    from app.models.work_order import WorkOrder
    from app.models.work_order_event import WorkOrderEvent

    # Verify work order exists
    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )

    ev = WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=event_type,
        action_by_id=current_user.id,
        remarks=remarks,
        changes=changes,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    actor_name = getattr(current_user, "username", str(current_user.id))
    background_tasks.add_task(
        _notify_oh_operators, work_order_number, event_type, actor_name, remarks, changes
    )

    logger.info("work_order_event_created", work_order=work_order_number, event_type=event_type.value)
    return _event_to_dict(ev)


# ---------------------------------------------------------------------------
# POST /{work_order_number}/send-to-assembly  (OH bulk action)
# ---------------------------------------------------------------------------


_OH_ELIGIBLE_STATUSES = {
    "CREATED",
    "OH_INSPECTION",
    "MEASUREMENTS_RECORDED",
    "REOPENED",
}


@router.post(
    "/{work_order_number}/send-to-assembly",
    status_code=status.HTTP_200_OK,
    summary="OH bulk-sends all eligible blades in a work order to Assembly",
)
async def send_work_order_to_assembly(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Transitions all eligible blades in an LPTR work order to
    ``SENT_TO_ASSEMBLY`` in a single operation.  Only blades in CREATED,
    OH_INSPECTION, MEASUREMENTS_RECORDED, or REOPENED status are eligible.
    Blades already in Assembly-side statuses are skipped.

    HPTR work orders never go to Assembly — HPTR blades stay in OH per the
    state machine — so calling this against an HPTR work order returns 422;
    use the OH Slot Allocation / Set Making tools for HPTR instead.

    Returns a summary: total blade count, how many were sent, how many skipped.
    """
    from app.models.blade import Blade
    from app.models.work_order import WorkOrder
    from app.models.work_order_event import WorkOrderEvent
    from app.models.workflow import WorkflowLog
    from app.notifications.service import NotificationService

    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )
    if work_order.blade_type != BladeType.LPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' is {work_order.blade_type.value} — "
                "this endpoint only applies to LPTR work orders. HPTR blades stay in "
                "OH; use the OH Slot Allocation / Set Making tools instead."
            ),
        )

    remarks = body.get("remarks") or f"Work Order {work_order_number} sent to Assembly"

    # Fetch all non-deleted blades in this work order
    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )

    sent_count = 0
    skipped_count = 0

    for blade in blades:
        if blade.status.value in _OH_ELIGIBLE_STATUSES:
            prev_status = blade.status
            blade.status = BladeStatus.SENT_TO_ASSEMBLY
            log = WorkflowLog(
                blade_id=blade.id,
                from_status=prev_status,
                to_status=BladeStatus.SENT_TO_ASSEMBLY,
                action_by_id=current_user.id,
                remarks=remarks,
            )
            db.add(log)
            sent_count += 1
        else:
            skipped_count += 1

    if sent_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No eligible blades found in Work Order '{work_order_number}'. "
                f"{skipped_count} blade(s) already in Assembly or completed."
            ),
        )

    await db.commit()

    # Record the work-order-level audit event for "Sent to Assembly"
    ev = WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.SENT_TO_ASSEMBLY,
        action_by_id=current_user.id,
        remarks=remarks,
        changes={
            "sent_count": sent_count,
            "skipped_count": skipped_count,
        },
    )
    db.add(ev)
    await db.commit()

    actor_name = getattr(current_user, "username", str(current_user.id))

    # Notify assembly operators — use a fresh session (request session closes before BG task runs)
    async def _notify_assembly(
        _work_order_number: str, _actor_name: str, _sent_count: int, _skipped_count: int
    ) -> None:
        try:
            from app.models.user import User, UserRole as UserRoleModel, Role
            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as _db:
                result = await _db.execute(
                    select(User)
                    .join(UserRoleModel, UserRoleModel.user_id == User.id)
                    .join(Role, Role.id == UserRoleModel.role_id)
                    .where(
                        Role.name.in_(["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]),
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                    )
                    .distinct()
                )
                target_users = list(result.scalars().all())
                svc = NotificationService(_db)
                for user in target_users:
                    await svc.create_notification(
                        user_id=user.id,
                        title=f"Work Order {_work_order_number} ready for Assembly",
                        body=(
                            f"OH ({_actor_name}) has sent {_sent_count} blade(s) from Work Order {_work_order_number} to Assembly."
                            + (f" {_skipped_count} blade(s) skipped." if _skipped_count else "")
                        ),
                        notification_type=NotificationType.WORKFLOW_UPDATED,
                    )
            logger.info("work_order_send_notification_sent", work_order=_work_order_number, recipients=len(target_users))
        except Exception as exc:  # noqa: BLE001
            logger.warning("work_order_send_notification_failed", error=str(exc))

    background_tasks.add_task(_notify_assembly, work_order_number, actor_name, sent_count, skipped_count)

    logger.info(
        "work_order_sent_to_assembly",
        work_order=work_order_number,
        sent=sent_count,
        skipped=skipped_count,
    )
    return {
        "work_order_number": work_order_number,
        "total_blades": len(blades),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "message": (
            f"{sent_count} blade(s) sent to Assembly."
            + (f" {skipped_count} already in Assembly." if skipped_count else "")
        ),
    }


# ---------------------------------------------------------------------------
# POST /{work_order_number}/assign-slot  (Assembly/OH bulk slot assignment)
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/assign-slot",
    status_code=status.HTTP_200_OK,
    summary="Bulk-assigns computed slots to all eligible blades in a work order",
)
async def assign_work_order_slot(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Assigns computed disc slots to the work order's eligible blades. LPTR and
    HPTR use genuinely different allocation logic (different physical rotors,
    different balancing procedures) — see the branch-specific docstrings on
    ``_assign_lptr_work_order_slot`` / ``_assign_hptr_work_order_slot`` below.

    ``blade_type`` is derived from the Work Order header (``WorkOrder.blade_type``)
    rather than trusted from the request body — a Work Order is always exactly
    one blade type, so there is nothing left for the caller to disambiguate.
    """
    from app.models.work_order import WorkOrder

    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )
    blade_type = work_order.blade_type

    user_roles = _user_role_names(current_user)
    if "SUPER_ADMIN" not in user_roles:
        required_role = "ASSEMBLY_OPERATOR" if blade_type == BladeType.LPTR else "OH_OPERATOR"
        if required_role not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{required_role} or SUPER_ADMIN role required for {blade_type.value} slot assignment",
            )

    if blade_type == BladeType.LPTR:
        return await _assign_lptr_work_order_slot(work_order_number, body, current_user, db, background_tasks)
    return await _assign_hptr_work_order_slot(work_order_number, body, current_user, db)


async def _assign_lptr_work_order_slot(
    work_order_number: str,
    body: dict,
    current_user: Any,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Persists the operator-confirmed LPTR two-stage blade-to-slot mapping.

    LPTR slot allocation happens in two physical stages: 46 blades are
    installed and balancing-checked first, then physically removed, then
    the remaining 44 blades fill the slots stage 1 left empty and are
    balancing-checked again. The allocation itself (weight sort, anchor
    placement at the reported unbalance position, target-weight matching
    for the opposite slots, alternating-gap fill) is computed client-side
    in frontend/src/utils/lptrBalancing.ts — like HPTR's set-making swaps,
    this endpoint only validates and persists whatever final
    ``assignments`` the frontend submits for the given ``stage``, it does
    not run the allocation algorithm itself.

    Requires ASSEMBLY_OPERATOR/SUPER_ADMIN (checked by the caller). The
    work order must already be ACCEPTED/MODIFIED by Assembly. Stage 2
    additionally requires a stage-1 allocation to already exist — it
    physically cannot happen before those 46 blades are installed and
    removed.
    """
    from app.core.constants import LPTR_STAGE1_BLADE_COUNT, LPTR_STAGE2_BLADE_COUNT
    from app.models.blade import Blade
    from app.models.work_order_event import WorkOrderEvent
    from app.models.slot_allocation import SlotAllocation
    from app.workflows.state_machine import WorkflowEngine

    try:
        stage: int = int(body["stage"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stage (1 or 2) is required for LPTR slot assignment",
        )
    if stage not in (1, 2):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stage must be 1 or 2",
        )

    try:
        unbalance_slot: int = int(body["unbalance_slot"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="unbalance_slot (int) is required for LPTR slot assignment",
        )

    total_slots: int = int(body.get("total_slots", 90))
    assignments = body.get("assignments")

    if total_slots < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="total_slots must be at least 2",
        )
    if unbalance_slot < 1 or unbalance_slot > total_slots:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unbalance_slot must be between 1 and {total_slots}",
        )
    if not isinstance(assignments, list) or not assignments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assignments (non-empty list of {blade_id, slot_number}) is required for LPTR slot assignment",
        )

    try:
        parsed = [
            (uuid.UUID(str(a["blade_id"])), int(a["slot_number"]))
            for a in assignments
        ]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Each assignment must have a valid blade_id (uuid) and slot_number (int)",
        )

    slot_by_blade_id: dict = dict(parsed)
    if len(slot_by_blade_id) != len(parsed):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate blade_id in assignments",
        )
    slot_numbers = [s for _, s in parsed]
    if len(set(slot_numbers)) != len(slot_numbers):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate slot_number in assignments",
        )
    if any(s < 1 or s > total_slots for s in slot_numbers):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"All slot_number values must be between 1 and {total_slots}",
        )

    expected_count = LPTR_STAGE1_BLADE_COUNT if stage == 1 else LPTR_STAGE2_BLADE_COUNT
    if len(slot_by_blade_id) != expected_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage {stage} requires exactly {expected_count} assignments, received {len(slot_by_blade_id)}",
        )

    # Gate: work order must have been accepted by Assembly before slots can be assigned
    latest_event = (
        await db.execute(
            select(WorkOrderEvent)
            .where(WorkOrderEvent.work_order_number == work_order_number)
            .order_by(WorkOrderEvent.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    work_order_status = latest_event.event_type.value if latest_event else "CREATED"
    # SLOTS_ALLOCATED is included so stage 2 (submitted after stage 1's own
    # SLOTS_ALLOCATED event) isn't blocked by its own prior event.
    _ACCEPTED_STATUSES = {
        BatchEventType.ACCEPTED.value,
        BatchEventType.MODIFIED.value,
        BatchEventType.SLOTS_ALLOCATED.value,
    }
    if work_order_status not in _ACCEPTED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' must be accepted by Assembly before slot assignment. "
                f"Current status: {work_order_status}. "
                f"Please accept the work order first."
            ),
        )

    # Stage 2 physically cannot happen before stage 1's blades are installed
    # and balancing-checked. Do not additionally require a passing check —
    # the operator may proceed via documented manual corrections/manufacturer
    # replacement even when balancing can't be perfected; the software must
    # never gate on or silently override that judgment call.
    if stage == 2:
        existing_stage1 = (
            await db.execute(
                select(SlotAllocation.id)
                .join(Blade, Blade.id == SlotAllocation.blade_id)
                .where(
                    Blade.work_order_number == work_order_number,
                    Blade.blade_type == BladeType.LPTR,
                    SlotAllocation.stage == 1,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_stage1 is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Work Order '{work_order_number}' has no stage-1 LPTR slot allocation yet. "
                    "Stage 1 must be installed and balancing-checked before stage 2."
                ),
            )

    _ELIGIBLE_FOR_SLOT = [
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.ASSEMBLY_RECEIVED,
        BladeStatus.ASSEMBLY_VERIFIED,
    ]

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.blade_type == BladeType.LPTR,
                Blade.status.in_(_ELIGIBLE_FOR_SLOT),
                Blade.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No eligible LPTR blades found in Work Order '{work_order_number}' — all blades may already have slots assigned.",
        )

    # Stage 1 assigns 46 of the currently-eligible pool (the other 44 stay
    # eligible, for stage 2) — unlike HPTR's single-shot assignment, this is
    # deliberately a subset, not an exact match to the full eligible set.
    # Every referenced blade must still be currently eligible, though.
    eligible_ids = {b.id for b in blades}
    if not set(slot_by_blade_id.keys()) <= eligible_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "assignments reference blade(s) that are not currently eligible "
                f"for LPTR slot assignment in Work Order '{work_order_number}'."
            ),
        )

    assigned_blades = [b for b in blades if b.id in slot_by_blade_id]

    for blade in assigned_blades:
        slot_number = str(slot_by_blade_id[blade.id])

        # Deactivate any existing allocation
        existing = (
            await db.execute(
                select(SlotAllocation).where(
                    SlotAllocation.blade_id == blade.id,
                    SlotAllocation.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.is_active = False
            existing.previous_slot_number = existing.slot_number

        # Create new allocation
        alloc = SlotAllocation(
            blade_id=blade.id,
            slot_number=slot_number,
            stage=stage,
            allocated_by_id=current_user.id,
        )
        db.add(alloc)

        # Transition blade status
        await WorkflowEngine(db).transition(
            blade=blade,
            to_status=BladeStatus.SLOT_ASSIGNED,
            user=current_user,
            station_id=None,
            remarks=(
                f"LPTR stage {stage} slot {slot_number} assigned "
                f"(unbalance at slot {unbalance_slot}, disc has {total_slots} slots)"
            ),
        )

    await db.commit()

    # Record the work-order-level audit event for "Slots Allocated" so it shows
    # up in the work order's Event History alongside Sent/Received/Accepted/Rejected.
    ev = WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.SLOTS_ALLOCATED,
        action_by_id=current_user.id,
        remarks=f"LPTR stage {stage}: {len(assigned_blades)} blade(s) assigned to computed disc slots.",
        changes={
            "stage": stage,
            "blades_assigned": len(assigned_blades),
            "unbalance_slot": unbalance_slot,
            "total_slots": total_slots,
        },
    )
    db.add(ev)
    await db.commit()

    # Notify OH that this stage's slots are now assigned.
    blade_count_assigned = len(assigned_blades)
    async def _notify_slots_assigned(_work_order: str, _count: int, _stage: int) -> None:
        from app.notifications.service import NotificationService
        from app.models.notification import NotificationType
        from app.db.session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as _db:
                svc = NotificationService(_db)
                await svc.notify_roles(
                    roles=["OH_OPERATOR", "SUPER_ADMIN"],
                    title=f"Work Order {_work_order} — LPTR stage {_stage} slots assigned",
                    body=f"Assembly has assigned disc slots to {_count} blade(s) for LPTR stage {_stage} in Work Order {_work_order}.",
                    notification_type=NotificationType.SLOT_PENDING,
                    metadata={"work_order_number": _work_order, "stage": _stage, "blades_assigned": _count},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify_slots_assigned_failed", error=str(exc))

    background_tasks.add_task(
        _notify_slots_assigned, work_order_number, blade_count_assigned, stage
    )

    logger.info(
        "work_order_lptr_slots_assigned",
        work_order=work_order_number,
        blade_type="LPTR",
        stage=stage,
        blades=len(assigned_blades),
        unbalance_slot=unbalance_slot,
        total_slots=total_slots,
    )
    return {
        "work_order_number": work_order_number,
        "blade_type": "LPTR",
        "stage": stage,
        "blades_assigned": len(assigned_blades),
        "unbalance_slot": unbalance_slot,
        "total_slots": total_slots,
        "message": f"{len(assigned_blades)} LPTR blade(s) assigned to computed disc slots (stage {stage}).",
    }


async def _assign_hptr_work_order_slot(
    work_order_number: str,
    body: dict,
    current_user: Any,
    db: AsyncSession,
) -> dict:
    """
    Persists the operator-confirmed HPTR blade-to-slot mapping.

    Unlike LPTR, HPTR slot allocation is NOT purely algorithmic: the OH
    Slot Allocation tab computes an initial mapping client-side (sort by
    weight descending, pair heaviest with ``start_slot`` and lightest with
    its opposite slot 45 positions away on the 90-slot rotor, alternating
    inward), then the Set Making tab lets the operator manually swap blades
    between the two halves (W1 = slots 1-45, W2 = slots 46-90) until the
    half containing ``start_slot`` is heavier by 1.5-2.0 g. Because those
    swaps are manual and un-recomputable server-side, this endpoint simply
    validates and persists whatever final ``assignments`` the frontend
    submits — it does not run the allocation algorithm itself.

    Requires OH_OPERATOR/SUPER_ADMIN (checked by the caller). HPTR never
    leaves OH, so there is no Assembly-acceptance gate. Eligible blades are
    those at MEASUREMENTS_RECORDED. Logs both a SLOTS_ALLOCATED and a
    SET_MAKING WorkOrderEvent — this single call is the only backend
    touchpoint for both steps (Set Making's manual W1/W2 swaps happen
    client-side and are only persisted once confirmed here).
    """
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.slot_allocation import SlotAllocation
    from app.models.work_order_event import WorkOrderEvent
    from app.workflows.state_machine import WorkflowEngine

    try:
        start_slot = int(body["start_slot"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_slot (int) is required for HPTR slot assignment",
        )
    total_slots = int(body.get("total_slots", 90))
    unbalance_value = body.get("unbalance_value")
    assignments = body.get("assignments")

    if start_slot < 1 or start_slot > total_slots:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"start_slot must be between 1 and {total_slots}",
        )
    if not isinstance(assignments, list) or not assignments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assignments (non-empty list of {blade_id, slot_number}) is required for HPTR slot assignment",
        )

    try:
        parsed = [
            (uuid.UUID(str(a["blade_id"])), int(a["slot_number"]))
            for a in assignments
        ]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Each assignment must have a valid blade_id (uuid) and slot_number (int)",
        )

    slot_by_blade_id: dict = dict(parsed)
    if len(slot_by_blade_id) != len(parsed):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate blade_id in assignments",
        )
    slot_numbers = [s for _, s in parsed]
    if len(set(slot_numbers)) != len(slot_numbers):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate slot_number in assignments",
        )
    if any(s < 1 or s > total_slots for s in slot_numbers):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"All slot_number values must be between 1 and {total_slots}",
        )

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.blade_type == BladeType.HPTR,
                Blade.status == BladeStatus.MEASUREMENTS_RECORDED,
                Blade.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No eligible HPTR blades found in Work Order '{work_order_number}' — all blades may already have slots assigned.",
        )

    eligible_ids = {b.id for b in blades}
    if set(slot_by_blade_id.keys()) != eligible_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "assignments must cover exactly the work order's eligible HPTR blades "
                f"({len(eligible_ids)} expected, {len(slot_by_blade_id)} received)."
            ),
        )

    # Fetch latest INITIAL weight_grams per blade, purely to report the W1/W2
    # split back to the caller for audit/confirmation — the swap decision
    # itself already happened client-side before this call.
    from sqlalchemy import func as sa_func

    blade_ids = list(eligible_ids)
    subq = (
        select(
            Measurement.blade_id,
            sa_func.max(Measurement.measured_at).label("latest_at"),
        )
        .where(
            Measurement.blade_id.in_(blade_ids),
            Measurement.measurement_type == "INITIAL",
        )
        .group_by(Measurement.blade_id)
        .subquery()
    )
    meas_rows = (
        await db.execute(
            select(Measurement.blade_id, Measurement.weight_grams)
            .join(
                subq,
                (Measurement.blade_id == subq.c.blade_id)
                & (Measurement.measured_at == subq.c.latest_at),
            )
        )
    ).all()
    weight_map: dict = {row.blade_id: float(row.weight_grams or 0) for row in meas_rows}

    half = total_slots // 2  # W1 = 1..half, W2 = half+1..total_slots
    w1_total = 0.0
    w2_total = 0.0
    for blade in blades:
        slot = slot_by_blade_id[blade.id]
        weight = weight_map.get(blade.id, 0.0)
        if slot <= half:
            w1_total += weight
        else:
            w2_total += weight

    for blade in blades:
        slot_number = str(slot_by_blade_id[blade.id])

        existing = (
            await db.execute(
                select(SlotAllocation).where(
                    SlotAllocation.blade_id == blade.id,
                    SlotAllocation.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.is_active = False
            existing.previous_slot_number = existing.slot_number

        alloc = SlotAllocation(
            blade_id=blade.id,
            slot_number=slot_number,
            allocated_by_id=current_user.id,
        )
        db.add(alloc)

        await WorkflowEngine(db).transition(
            blade=blade,
            to_status=BladeStatus.SLOT_ASSIGNED,
            user=current_user,
            station_id=None,
            remarks=(
                f"HPTR slot {slot_number} assigned "
                f"(start slot {start_slot}"
                + (f", unbalance {unbalance_value} g" if unbalance_value is not None else "")
                + ")"
            ),
        )

    await db.commit()

    weight_diff = round(abs(w1_total - w2_total), 3)

    db.add(WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.SLOTS_ALLOCATED,
        action_by_id=current_user.id,
        remarks=f"{len(blades)} HPTR blade(s) assigned to computed disc slots (start slot {start_slot}).",
        changes={"blades_assigned": len(blades), "start_slot": start_slot},
    ))
    db.add(WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.SET_MAKING,
        action_by_id=current_user.id,
        remarks=(
            f"Set Making confirmed — W1 {round(w1_total, 3)} g, W2 {round(w2_total, 3)} g "
            f"(diff {weight_diff} g)."
        ),
        changes={"w1_total": round(w1_total, 3), "w2_total": round(w2_total, 3), "weight_diff": weight_diff},
    ))
    await db.commit()

    logger.info(
        "work_order_hptr_slots_assigned",
        work_order=work_order_number,
        blades=len(blades),
        start_slot=start_slot,
        w1_total=round(w1_total, 3),
        w2_total=round(w2_total, 3),
        weight_diff=weight_diff,
    )
    return {
        "work_order_number": work_order_number,
        "blade_type": "HPTR",
        "blades_assigned": len(blades),
        "start_slot": start_slot,
        "w1_total": round(w1_total, 3),
        "w2_total": round(w2_total, 3),
        "weight_diff": weight_diff,
        "message": f"{len(blades)} HPTR blade(s) assigned to computed disc slots.",
    }



# ---------------------------------------------------------------------------
# POST /{work_order_number}/complete-hptr-balancing
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/complete-hptr-balancing",
    status_code=status.HTTP_200_OK,
    summary="Mark a work order's saved HPTR slot allocation as balanced/complete",
)
async def complete_hptr_balancing(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Physical balancing testing confirmed the set is balanced — transition
    every HPTR blade in the work order's active slot allocation from
    ``SLOT_ASSIGNED``/``BALANCING_IN_PROGRESS`` to ``BALANCING_COMPLETED``
    and mark each slot allocation as balanced.

    Once every HPTR blade in the work order reaches ``BALANCING_COMPLETED``
    the work order stops showing up as selectable in the OH Slot Allocation
    page — there is nothing left to do here.

    Only applies to HPTR work orders — calling this on an LPTR work order
    returns 422.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.models.work_order import WorkOrder
    from app.models.work_order_event import WorkOrderEvent
    from app.workflows.state_machine import WorkflowEngine

    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )
    if work_order.blade_type != BladeType.HPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' is {work_order.blade_type.value} — "
                "this endpoint only applies to HPTR work orders."
            ),
        )

    remarks = (body or {}).get("remarks") or "Physical balancing testing confirmed — set balanced"

    blades = (
        await db.execute(
            select(Blade)
            .join(SlotAllocation, SlotAllocation.blade_id == Blade.id)
            .where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                SlotAllocation.is_active.is_(True),
                Blade.status.in_([
                    BladeStatus.SLOT_ASSIGNED,
                    BladeStatus.BALANCING_IN_PROGRESS,
                ]),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No HPTR blades pending balancing found for Work Order '{work_order_number}'",
        )

    alloc_by_blade_id: dict[uuid.UUID, Any] = {}
    for blade in blades:
        alloc = (
            await db.execute(
                select(SlotAllocation).where(
                    SlotAllocation.blade_id == blade.id,
                    SlotAllocation.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if alloc:
            alloc_by_blade_id[blade.id] = alloc

    engine = WorkflowEngine(db)
    for blade in blades:
        alloc = alloc_by_blade_id.get(blade.id)
        if alloc:
            alloc.is_balanced = True
            alloc.balancing_remarks = remarks
        await engine.transition(
            blade=blade,
            to_status=BladeStatus.BALANCING_COMPLETED,
            user=current_user,
            station_id=None,
            remarks=remarks,
        )

    await db.commit()

    db.add(WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.BALANCED,
        action_by_id=current_user.id,
        remarks=f"{len(blades)} HPTR blade(s) confirmed balanced. {remarks}",
        changes={"blades_balanced": len(blades)},
    ))
    await db.commit()

    actor_name = getattr(current_user, "username", str(current_user.id))

    async def _notify_hptr_balancing_complete(_work_order: str, _count: int, _actor: str) -> None:
        from app.notifications.service import NotificationService
        from app.models.notification import NotificationType
        from app.db.session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as _db:
                svc = NotificationService(_db)
                await svc.notify_roles(
                    roles=["OH_OPERATOR", "SUPER_ADMIN"],
                    title=f"Work Order {_work_order} — HPTR balancing complete",
                    body=(
                        f"{_actor} confirmed HPTR balancing complete for Work Order {_work_order} "
                        f"({_count} blade(s))."
                    ),
                    notification_type=NotificationType.WORKFLOW_UPDATED,
                    metadata={"work_order_number": _work_order},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify_hptr_balancing_complete_failed", error=str(exc))

    background_tasks.add_task(_notify_hptr_balancing_complete, work_order_number, len(blades), actor_name)

    logger.info("work_order_hptr_balancing_completed", work_order=work_order_number, blades=len(blades))
    return {
        "work_order_number": work_order_number,
        "blades_completed": len(blades),
        "message": f"{len(blades)} HPTR blade(s) marked balanced — work order complete.",
    }


# ---------------------------------------------------------------------------
# POST /{work_order_number}/reset-hptr-slots
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/reset-hptr-slots",
    status_code=status.HTTP_200_OK,
    summary="Reset a work order's HPTR slot allocation so Slot Allocation / Set Making can be redone",
)
async def reset_hptr_slots(
    work_order_number: str,
    body: dict,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Deactivates the work order's active HPTR slot allocations and transitions
    every affected blade back to MEASUREMENTS_RECORDED — the same state they
    were in before Slot Allocation ever ran — making the batch eligible for a
    fresh Slot Allocation / Set Making pass in the OH Slot Allocation page.

    Only applies to HPTR work orders, and only to blades still at
    SLOT_ASSIGNED or BALANCING_IN_PROGRESS — i.e. before physical balancing
    testing has been confirmed complete. A batch already marked
    BALANCING_COMPLETED is not resettable through this endpoint (undoing a
    physically-confirmed balance is a separate, more deliberate action).
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.models.work_order import WorkOrder
    from app.models.work_order_event import WorkOrderEvent
    from app.workflows.state_machine import WorkflowEngine

    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )
    if work_order.blade_type != BladeType.HPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' is {work_order.blade_type.value} — "
                "this endpoint only applies to HPTR work orders."
            ),
        )

    remarks = (body or {}).get("remarks") or "Slot allocation reset — redoing Set Making from scratch"

    _RESETTABLE_STATUSES = [BladeStatus.SLOT_ASSIGNED, BladeStatus.BALANCING_IN_PROGRESS]
    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                Blade.status.in_(_RESETTABLE_STATUSES),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No resettable HPTR blades found for Work Order '{work_order_number}' — "
                "blades must be at Slot Assigned or Balancing In Progress (not yet Balancing Completed)."
            ),
        )

    engine = WorkflowEngine(db)
    for blade in blades:
        alloc = (
            await db.execute(
                select(SlotAllocation).where(
                    SlotAllocation.blade_id == blade.id,
                    SlotAllocation.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if alloc:
            alloc.is_active = False
            alloc.previous_slot_number = alloc.slot_number
        await engine.transition(
            blade=blade,
            to_status=BladeStatus.MEASUREMENTS_RECORDED,
            user=current_user,
            station_id=None,
            remarks=remarks,
        )

    await db.commit()

    db.add(WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.MEASUREMENTS_RECORDED,
        action_by_id=current_user.id,
        remarks=f"{len(blades)} HPTR blade(s) reset — slot allocation redone from scratch. {remarks}",
        changes={"blades_reset": len(blades)},
    ))
    await db.commit()

    logger.info("work_order_hptr_slots_reset", work_order=work_order_number, blades=len(blades))
    return {
        "work_order_number": work_order_number,
        "blades_reset": len(blades),
        "message": f"{len(blades)} HPTR blade(s) reset to Measurements Recorded — ready for a fresh Slot Allocation.",
    }


# ---------------------------------------------------------------------------
# GET /{work_order_number}/rocking-creep
# ---------------------------------------------------------------------------


@router.get(
    "/{work_order_number}/rocking-creep",
    status_code=status.HTTP_200_OK,
    summary="Get all blades in a work order with slot numbers and rocking/creep values",
)
async def get_work_order_rocking_creep(
    work_order_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    """
    Return one row per blade in the work order containing:
    - blade identity (serial, melt, blade_type, status)
    - allocated slot_number (from active SlotAllocation, if assigned)
    - current rocking_value and creep_value (from the most recent measurement)

    Intended for the OH Rocking & Creep Entry screen.
    """
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.slot_allocation import SlotAllocation
    from sqlalchemy import func as sa_func

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
            ).order_by(Blade.created_at)
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{work_order_number}' not found",
        )

    blade_ids = [b.id for b in blades]

    # Active slot allocation per blade
    slot_rows = (
        await db.execute(
            select(SlotAllocation.blade_id, SlotAllocation.slot_number)
            .where(
                SlotAllocation.blade_id.in_(blade_ids),
                SlotAllocation.is_active.is_(True),
            )
        )
    ).all()
    slot_map = {str(r.blade_id): r.slot_number for r in slot_rows}

    # Latest measurement per blade (for rocking_value, creep_value, measurement_id)
    subq = (
        select(
            Measurement.blade_id,
            sa_func.max(Measurement.measured_at).label("latest_at"),
        )
        .where(Measurement.blade_id.in_(blade_ids))
        .group_by(Measurement.blade_id)
        .subquery()
    )
    meas_rows = (
        await db.execute(
            select(
                Measurement.blade_id,
                Measurement.id.label("measurement_id"),
                Measurement.weight_grams,
                Measurement.static_moment_gcm,
                Measurement.rocking_value,
                Measurement.creep_value,
            ).join(
                subq,
                (Measurement.blade_id == subq.c.blade_id)
                & (Measurement.measured_at == subq.c.latest_at),
            )
        )
    ).all()
    meas_map = {
        str(r.blade_id): {
            "measurement_id": str(r.measurement_id),
            "weight_grams": float(r.weight_grams) if r.weight_grams is not None else None,
            "static_moment_gcm": float(r.static_moment_gcm) if r.static_moment_gcm is not None else None,
            "rocking_value": float(r.rocking_value) if r.rocking_value is not None else None,
            "creep_value": float(r.creep_value) if r.creep_value is not None else None,
        }
        for r in meas_rows
    }

    result = []
    for blade in blades:
        bid = str(blade.id)
        meas = meas_map.get(bid, {})
        result.append({
            "blade_id": bid,
            "serial_number": blade.serial_number,
            "melt_number": blade.melt_number,
            "blade_type": blade.blade_type.value if hasattr(blade.blade_type, "value") else str(blade.blade_type),
            "status": blade.status.value if hasattr(blade.status, "value") else str(blade.status),
            "slot_number": slot_map.get(bid),
            "measurement_id": meas.get("measurement_id"),
            "weight_grams": meas.get("weight_grams"),
            "static_moment_gcm": meas.get("static_moment_gcm"),
            "rocking_value": meas.get("rocking_value"),
            "creep_value": meas.get("creep_value"),
        })
    return result


# ---------------------------------------------------------------------------
# POST /{work_order_number}/receive
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/receive",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly marks a work order as received",
)
async def receive_work_order(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Assembly operator acknowledges receipt of the work order from OH."""
    return await _create_work_order_event(
        work_order_number=work_order_number,
        event_type=BatchEventType.RECEIVED_BY_ASSEMBLY,
        remarks=body.get("remarks"),
        changes=None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /{work_order_number}/accept
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/accept",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly accepts a work order",
)
async def accept_work_order(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Assembly operator formally accepts the work order for assembly work."""
    return await _create_work_order_event(
        work_order_number=work_order_number,
        event_type=BatchEventType.ACCEPTED,
        remarks=body.get("remarks"),
        changes=None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /{work_order_number}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/reject",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly rejects a work order",
)
async def reject_work_order(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Assembly operator rejects the work order, notifying OH."""
    return await _create_work_order_event(
        work_order_number=work_order_number,
        event_type=BatchEventType.REJECTED,
        remarks=body.get("remarks") or body.get("reason"),
        changes=None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /{work_order_number}/modify
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/modify",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly applies blade-level modifications to a work order",
)
async def modify_work_order(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Assembly operator corrects blade details (weight, static moment, melt number) for
    one or more blades in the work order.  Each modification entry carries the original
    and updated field values so the diff is preserved in the WorkOrderEvent and in OH
    notifications.
    """
    import uuid as _uuid
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    remarks: str = body.get("remarks") or ""
    raw_mods: list = body.get("modifications", [])

    ALLOWED_FIELDS = {
        "weight_grams",
        "static_moment_gcm",
        "melt_number",
        "part_number",
        "nomenclature",
        "work_order_number",
        "shop_order_number",
        "engine_number",
    }
    changes_summary: dict = {}

    for mod in raw_mods:
        blade_id_str = mod.get("blade_id")
        updated_fields: dict = mod.get("updated", {})
        original_fields: dict = mod.get("original", {})
        serial_number: str = mod.get("serial_number", "")

        if not blade_id_str or not updated_fields:
            continue

        try:
            blade_uuid = _uuid.UUID(blade_id_str)
        except (ValueError, TypeError):
            continue

        blade = (
            await db.execute(
                select(Blade).where(
                    Blade.id == blade_uuid,
                    Blade.work_order_number == work_order_number,
                    Blade.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if not blade:
            continue

        applied: dict = {}
        for field, new_value in updated_fields.items():
            if field not in ALLOWED_FIELDS or new_value is None:
                continue
            old_value = getattr(blade, field, None)
            if old_value == new_value:
                continue
            setattr(blade, field, new_value)
            applied[field] = {"before": old_value, "after": new_value}

        if applied:
            sn_key = serial_number or str(blade.id)
            changes_summary[sn_key] = applied
            db.add(WorkflowLog(
                blade_id=blade.id,
                from_status=blade.status,
                to_status=blade.status,
                action_by_id=current_user.id,
                remarks=f"Fields modified: {', '.join(applied.keys())}. {remarks}".strip(". "),
            ))

    if changes_summary:
        await db.commit()

    return await _create_work_order_event(
        work_order_number=work_order_number,
        event_type=BatchEventType.MODIFIED,
        remarks=remarks,
        changes=changes_summary or None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /  (grid-entry: create Work Order + scaffold 90 blade rows)
# ---------------------------------------------------------------------------


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Work Order and scaffold its 90 blade rows",
    response_model=WorkOrderDetailResponse,
)
async def create_work_order(
    data: WorkOrderCreate,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkOrderDetailResponse:
    """
    Phase A ("Start Blade Entry"): persist the Work Order header and scaffold
    ``BLADES_PER_WORK_ORDER`` blank blade rows ready for grid entry.
    """
    service = WorkOrderService(db)
    return await service.create(data, current_user)


# ---------------------------------------------------------------------------
# GET /{work_order_number}/entry  (grid-entry: resume/detail)
# ---------------------------------------------------------------------------


@router.get(
    "/{work_order_number}/entry",
    status_code=status.HTTP_200_OK,
    summary="Get the Work Order grid-entry detail (all rows + completion state)",
    response_model=WorkOrderDetailResponse,
)
async def get_work_order_entry(
    work_order_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkOrderDetailResponse:
    """
    Resume/detail view for the grid-entry screen — a distinct path from
    ``GET /{work_order_number}`` above (which returns the Batch/Work-Order
    Tracking page shape with event history) so both endpoints can coexist.
    """
    service = WorkOrderService(db)
    return await service.get_detail(work_order_number)


# ---------------------------------------------------------------------------
# PUT /{work_order_number}/rows/{s_no}  (grid-entry: per-row autosave)
# ---------------------------------------------------------------------------


@router.put(
    "/{work_order_number}/rows/{s_no}",
    status_code=status.HTTP_200_OK,
    summary="Autosave a single Work Order grid row",
    response_model=WorkOrderRowResponse,
)
async def save_work_order_row(
    work_order_number: str,
    s_no: int,
    data: WorkOrderRowUpdate,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkOrderRowResponse:
    """Idempotent per-row autosave for the grid-entry screen."""
    service = WorkOrderService(db)
    return await service.save_row(work_order_number, s_no, data, current_user)


# ---------------------------------------------------------------------------
# POST /{work_order_number}/complete  (grid-entry: validate + bulk transition)
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/complete",
    status_code=status.HTTP_200_OK,
    summary="Validate and complete Work Order grid entry",
    response_model=WorkOrderCompleteResponse,
)
async def complete_work_order_entry(
    work_order_number: str,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkOrderCompleteResponse:
    """
    Validate every row is complete and melt numbers are unique, then bulk
    transition all 90 blades CREATED → OH_INSPECTION → MEASUREMENTS_RECORDED.
    """
    service = WorkOrderService(db)
    return await service.complete(work_order_number, current_user)
