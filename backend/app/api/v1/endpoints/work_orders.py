"""
Work Order workflow endpoints.

GET  /work-orders/                                             — list all work orders with current status
GET  /work-orders/{work_order_number}                          — work order detail + event history
POST /work-orders/{work_order_number}/send-to-assembly         — OH bulk-sends all eligible LPTR blades to Assembly
POST /work-orders/{work_order_number}/assign-slot               — bulk-assigns computed disc slots (LPTR algorithmic / HPTR explicit)
POST /work-orders/{work_order_number}/complete-hptr-balancing   — mark a saved HPTR slot allocation balanced/complete
POST /work-orders/{work_order_number}/start-final-verification  — OH moves balanced HPTR blades into Final Verification
POST /work-orders/{work_order_number}/complete-lptr-balancing   — mark a saved LPTR slot allocation balanced/complete
POST /work-orders/{work_order_number}/return-to-oh              — Assembly reports LPTR balancing task complete, sends work order back to OH
POST /work-orders/{work_order_number}/accept-return             — OH accepts a work order returned from Assembly
POST /work-orders/{work_order_number}/complete-final-verification — OH completes final verification for a work order
POST /work-orders/{work_order_number}/reset-hptr-slots          — undo a saved HPTR slot allocation, redo from scratch
GET  /work-orders/{work_order_number}/rocking-creep              — blades with slot numbers + rocking/creep values
POST /work-orders/{work_order_number}/complete-rocking-creep    — confirm Rocking & Creep entry complete for a work order
POST /work-orders/{work_order_number}/receive                   — Assembly marks work order received
POST /work-orders/{work_order_number}/accept                    — Assembly accepts work order
POST /work-orders/{work_order_number}/modify                    — Assembly corrects blade-level fields

POST /work-orders/                                              — create a Work Order + scaffold 90 blade rows (grid entry)
GET  /work-orders/{work_order_number}/entry                     — grid-entry resume/detail (rows + completion state)
PUT  /work-orders/{work_order_number}/rows/{s_no}                — autosave a single grid row
POST /work-orders/{work_order_number}/rows/bulk-import           — bulk-fill grid rows from an uploaded .xlsx
POST /work-orders/{work_order_number}/complete                  — validate + bulk-transition grid entry to MEASUREMENTS_RECORDED
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import _user_role_names, get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import BatchEventType, BladeStatus, BladeType, MeasurementType, NotificationType
from app.schemas.work_order import (
    WorkOrderBulkImportError,
    WorkOrderBulkImportResponse,
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
        "MODIFIED": "Modified",
        "SLOTS_ALLOCATED": "Slots Allocated",
        "SET_MAKING": "Set Making",
        "BALANCED": "Balanced",
        "RETURNED_TO_OH": "Returned to OH",
        "ACCEPTED_BY_OH": "Accepted by OH",
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


def _format_modified_blade_changes(changes: dict) -> str:
    """Render the ' Modified blade(s): ... [serial: field: before -> after, ...]' suffix."""
    blade_serials = list(changes.keys())
    text = f" Modified blade(s): {', '.join(blade_serials)}."
    for sn, blade_changes in changes.items():
        field_parts = [
            f"{field}: {diff['before']} → {diff['after']}"
            for field, diff in blade_changes.items()
            if isinstance(diff, dict) and "before" in diff and "after" in diff
        ]
        if field_parts:
            text += f" [{sn}: {', '.join(field_parts)}]"
    return text


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
        BatchEventType.MODIFIED: "Modified",
    }

    title = f"Work Order {work_order_number} — {event_labels.get(event_type, event_type.value)}"
    body = f"Assembly has marked Work Order {work_order_number} as {event_labels.get(event_type, event_type.value).lower()}."
    if remarks:
        body += f" Remarks: {remarks}"

    if event_type == BatchEventType.MODIFIED and changes:
        body += _format_modified_blade_changes(changes)

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


async def _fetch_blade_count_rows(db: AsyncSession, has_slot_allocations: bool) -> list:
    """Per-work-order blade counts, optionally filtered to work orders with an active slot allocation."""
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation

    blade_rows = (
        await db.execute(
            select(
                Blade.work_order_number,
                func.count(Blade.id).label("blade_count"),
                func.sum(
                    case((Blade.status.in_(list(_ASSEMBLY_STATUSES)), 1), else_=0)
                ).label("blades_in_assembly_statuses"),
                func.sum(
                    case((Blade.status == BladeStatus.COMPLETED, 1), else_=0)
                ).label("blades_completed"),
                func.sum(
                    case((Blade.status == BladeStatus.FINAL_VERIFICATION, 1), else_=0)
                ).label("blades_final_verification"),
                func.sum(
                    case((Blade.status == BladeStatus.BALANCING_COMPLETED, 1), else_=0)
                ).label("blades_balancing_completed"),
                func.min(Blade.created_at).label("first_blade_at"),
            )
            .where(Blade.work_order_number.isnot(None), Blade.deleted_at.is_(None))
            .group_by(Blade.work_order_number)
            .order_by(func.min(Blade.created_at).desc())
        )
    ).all()

    if not blade_rows or not has_slot_allocations:
        return blade_rows

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
    return [r for r in blade_rows if r.work_order_number in slotted]


async def _fetch_rows_complete_map(db: AsyncSession, work_order_numbers: list) -> dict[str, int]:
    """Rows actually entered (Melt Number + Weight both present) per work order —
    NOT the same as blade_count, which is the fixed 90-row scaffold created up
    front and is nonzero from the moment a Work Order starts."""
    from app.models.blade import Blade
    from app.models.measurement import Measurement

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
    return {r.work_order_number: r.rows_complete_count for r in complete_rows}


async def _fetch_latest_event_map(db: AsyncSession, work_order_numbers: list) -> dict[str, Any]:
    from app.models.work_order_event import WorkOrderEvent

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
    return {ev.work_order_number: ev for ev in latest_events_rows}


async def _fetch_sent_at_map(db: AsyncSession, work_order_numbers: list) -> dict:
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

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
    return {r.work_order_number: r.first_sent_at for r in sent_rows}


async def _fetch_work_order_map(db: AsyncSession, work_order_numbers: list) -> dict[str, Any]:
    """WorkOrder header metadata (replaces the old BatchGroup autofill cache)."""
    from app.models.work_order import WorkOrder

    wo_rows = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number.in_(work_order_numbers))
        )
    ).scalars().all()
    return {wo.work_order_number: wo for wo in wo_rows}


async def _fetch_hptr_slot_maps(
    db: AsyncSession, work_order_numbers: list, wo_map: dict
) -> tuple[dict[str, int], dict[str, int]]:
    """HPTR blades already slot-allocated / already-balanced per work order.

    A Work Order is always exactly one blade_type, so this only ever produces
    rows for work orders whose header is HPTR — computed by scoping the
    queries to HPTR work order numbers up front.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation

    hptr_work_order_numbers = [
        wn for wn in work_order_numbers
        if wo_map.get(wn) is not None and wo_map[wn].blade_type == BladeType.HPTR
    ]
    if not hptr_work_order_numbers:
        return {}, {}

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

    # HPTR blades that have finished balancing (or moved beyond it)
    hptr_balanced_statuses = [
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
                Blade.status.in_(hptr_balanced_statuses),
            )
            .group_by(Blade.work_order_number)
        )
    ).all()
    hptr_balanced_map = {r.work_order_number: r.hptr_balanced_count for r in hptr_balanced_rows}

    return hptr_slotted_map, hptr_balanced_map


async def _fetch_lptr_slotted_map(db: AsyncSession, work_order_numbers: list, wo_map: dict) -> dict[str, int]:
    """LPTR blades already slot-allocated per work order (active allocations,
    either stage) — used to tell "Stage 1 only" apart from "both stages done"
    (blade_count is always 90 for a full LPTR work order: 46 + 44)."""
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation

    lptr_work_order_numbers = [
        wn for wn in work_order_numbers
        if wo_map.get(wn) is not None and wo_map[wn].blade_type == BladeType.LPTR
    ]
    if not lptr_work_order_numbers:
        return {}

    lptr_slotted_rows = (
        await db.execute(
            select(
                Blade.work_order_number,
                func.count(SlotAllocation.id).label("lptr_slotted_count"),
            )
            .join(SlotAllocation, SlotAllocation.blade_id == Blade.id)
            .where(
                Blade.work_order_number.in_(lptr_work_order_numbers),
                SlotAllocation.is_active.is_(True),
            )
            .group_by(Blade.work_order_number)
        )
    ).all()
    return {r.work_order_number: r.lptr_slotted_count for r in lptr_slotted_rows}


def _build_work_order_summary(
    row,
    wo_map: dict,
    latest_event_map: dict,
    rows_complete_map: dict,
    hptr_slotted_map: dict,
    hptr_balanced_map: dict,
    lptr_slotted_map: dict,
    sent_at_map: dict,
) -> dict:
    wn = row.work_order_number
    latest_ev = latest_event_map.get(wn)
    wo = wo_map.get(wn)
    blade_type = wo.blade_type if wo is not None else None
    # blades_sent / hptr_count collapse to a direct read of WorkOrder.blade_type
    # now that one work order is one blade type — no more per-row
    # blade_type case-summation needed.
    blades_sent = (row.blades_in_assembly_statuses or 0) if blade_type == BladeType.LPTR else 0
    hptr_count = row.blade_count if blade_type == BladeType.HPTR else 0
    cur_status = _derive_status(latest_ev.event_type if latest_ev else None, blades_sent)
    return {
        "work_order_number": wn,
        "blade_type": blade_type.value if blade_type else None,
        "blade_count": row.blade_count,
        "rows_complete_count": rows_complete_map.get(wn, 0),
        "blades_sent": blades_sent,
        "blades_completed": row.blades_completed or 0,
        "blades_final_verification": row.blades_final_verification or 0,
        "blades_balancing_completed": row.blades_balancing_completed or 0,
        "hptr_count": hptr_count,
        "hptr_slotted_count": hptr_slotted_map.get(wn, 0),
        "hptr_balanced_count": hptr_balanced_map.get(wn, 0),
        "lptr_slotted_count": lptr_slotted_map.get(wn, 0),
        "current_status": cur_status,
        "current_status_label": _status_label(cur_status),
        "first_blade_at": row.first_blade_at.isoformat() if row.first_blade_at else None,
        "first_sent_at": sent_at_map.get(wn, None) and sent_at_map[wn].isoformat(),
        "last_event": _event_to_dict(latest_ev) if latest_ev else None,
        "shop_order_number": wo.shop_order_number if wo else None,
        "part_number": wo.part_number if wo else None,
        "engine_number": wo.engine_number if wo else None,
        "is_entry_complete": wo.is_entry_complete if wo else False,
        "rocking_creep_complete": wo.is_rocking_creep_complete if wo else False,
    }


@router.get("/", status_code=status.HTTP_200_OK, summary="List all work orders with current status")
async def list_work_orders(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    has_slot_allocations: bool = False,
) -> list:
    """
    Return a summary of every work order known to the system, ordered by most
    recently created.  The ``current_status`` field reflects:
    - The latest explicit Assembly action (RECEIVED/ACCEPTED/MODIFIED), or
    - ``SENT_TO_ASSEMBLY`` if any blades have been sent, or
    - ``CREATED`` otherwise.

    A Work Order is always exactly one ``blade_type`` (LPTR or HPTR), so the
    per-work-order LPTR/HPTR split is read directly off ``WorkOrder.blade_type``
    rather than re-derived from a mixed blade population.
    """
    blade_rows = await _fetch_blade_count_rows(db, has_slot_allocations)
    if not blade_rows:
        return []

    work_order_numbers = [r.work_order_number for r in blade_rows]

    rows_complete_map = await _fetch_rows_complete_map(db, work_order_numbers)
    latest_event_map = await _fetch_latest_event_map(db, work_order_numbers)
    sent_at_map = await _fetch_sent_at_map(db, work_order_numbers)
    wo_map = await _fetch_work_order_map(db, work_order_numbers)
    hptr_slotted_map, hptr_balanced_map = await _fetch_hptr_slot_maps(db, work_order_numbers, wo_map)
    lptr_slotted_map = await _fetch_lptr_slotted_map(db, work_order_numbers, wo_map)

    return [
        _build_work_order_summary(
            row, wo_map, latest_event_map, rows_complete_map,
            hptr_slotted_map, hptr_balanced_map, lptr_slotted_map, sent_at_map,
        )
        for row in blade_rows
    ]


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
                func.sum(
                    case(
                        (Blade.status == BladeStatus.FINAL_VERIFICATION, 1),
                        else_=0,
                    )
                ).label("blades_final_verification"),
                func.sum(
                    case(
                        (Blade.status == BladeStatus.BALANCING_COMPLETED, 1),
                        else_=0,
                    )
                ).label("blades_balancing_completed"),
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
        "blades_final_verification": blade_agg.blades_final_verification or 0,
        "blades_balancing_completed": blade_agg.blades_balancing_completed or 0,
        "current_status": cur_status,
        "current_status_label": _status_label(cur_status),
        "first_blade_at": blade_agg.first_blade_at.isoformat() if blade_agg.first_blade_at else None,
        "first_sent_at": sent_row.first_sent_at.isoformat() if sent_row.first_sent_at else None,
        "last_event": _event_to_dict(latest_ev) if latest_ev else None,
        "events": [_event_to_dict(ev) for ev in events],
        "shop_order_number": work_order.shop_order_number,
        "part_number": work_order.part_number,
        "engine_number": work_order.engine_number,
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


def _transition_eligible_blades_to_assembly(blades: list, current_user: Any, remarks: str, db: AsyncSession) -> tuple[int, int]:
    """Move every OH-eligible blade to SENT_TO_ASSEMBLY, logging a WorkflowLog
    row for each. Returns (sent_count, skipped_count)."""
    from app.models.workflow import WorkflowLog

    sent_count = 0
    skipped_count = 0
    for blade in blades:
        if blade.status.value not in _OH_ELIGIBLE_STATUSES:
            skipped_count += 1
            continue
        prev_status = blade.status
        blade.status = BladeStatus.SENT_TO_ASSEMBLY
        db.add(WorkflowLog(
            blade_id=blade.id,
            from_status=prev_status,
            to_status=BladeStatus.SENT_TO_ASSEMBLY,
            action_by_id=current_user.id,
            remarks=remarks,
        ))
        sent_count += 1
    return sent_count, skipped_count


async def _notify_assembly_operators(
    work_order_number: str, actor_name: str, sent_count: int, skipped_count: int
) -> None:
    """Notify assembly operators — uses a fresh session (request session closes before BG task runs)."""
    from app.models.user import User, UserRole as UserRoleModel, Role
    from app.notifications.service import NotificationService
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
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
            svc = NotificationService(db)
            skipped_note = f" {skipped_count} blade(s) skipped." if skipped_count else ""
            for user in target_users:
                await svc.create_notification(
                    user_id=user.id,
                    title=f"Work Order {work_order_number} ready for Assembly",
                    body=(
                        f"OH ({actor_name}) has sent {sent_count} blade(s) from Work Order "
                        f"{work_order_number} to Assembly.{skipped_note}"
                    ),
                    notification_type=NotificationType.WORKFLOW_UPDATED,
                )
        logger.info("work_order_send_notification_sent", work_order=work_order_number, recipients=len(target_users))
    except Exception as exc:  # noqa: BLE001
        logger.warning("work_order_send_notification_failed", error=str(exc))


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

    sent_count, skipped_count = _transition_eligible_blades_to_assembly(blades, current_user, remarks, db)

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
    background_tasks.add_task(_notify_assembly_operators, work_order_number, actor_name, sent_count, skipped_count)

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


def _parse_lptr_slot_body(body: dict, stage1_count: int, stage2_count: int) -> tuple[int, int, int, dict[uuid.UUID, int]]:
    """Parse and validate the raw request body for LPTR slot assignment.

    Returns (stage, unbalance_slot, total_slots, slot_by_blade_id) or raises
    HTTPException 422 with a message identifying which part of the payload
    is invalid.
    """
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

    expected_count = stage1_count if stage == 1 else stage2_count
    if len(slot_by_blade_id) != expected_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage {stage} requires exactly {expected_count} assignments, received {len(slot_by_blade_id)}",
        )

    return stage, unbalance_slot, total_slots, slot_by_blade_id


async def _check_work_order_accepted_for_slots(db: AsyncSession, work_order_number: str) -> None:
    """Gate: work order must have been accepted by Assembly before slots can be assigned."""
    from app.models.work_order_event import WorkOrderEvent

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
    accepted_statuses = {
        BatchEventType.ACCEPTED.value,
        BatchEventType.MODIFIED.value,
        BatchEventType.SLOTS_ALLOCATED.value,
    }
    if work_order_status not in accepted_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' must be accepted by Assembly before slot assignment. "
                f"Current status: {work_order_status}. "
                f"Please accept the work order first."
            ),
        )


async def _check_lptr_stage2_prerequisite(db: AsyncSession, work_order_number: str, stage: int) -> None:
    """Stage 2 physically cannot happen before stage 1's blades are installed
    and balancing-checked. Do not additionally require a passing check — the
    operator may proceed via documented manual corrections/manufacturer
    replacement even when balancing can't be perfected; the software must
    never gate on or silently override that judgment call."""
    if stage != 2:
        return

    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation

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


async def _fetch_eligible_lptr_blades(db: AsyncSession, work_order_number: str) -> list:
    from app.models.blade import Blade

    eligible_statuses = [
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.ASSEMBLY_RECEIVED,
        BladeStatus.ASSEMBLY_VERIFIED,
    ]
    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.blade_type == BladeType.LPTR,
                Blade.status.in_(eligible_statuses),
                Blade.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No eligible LPTR blades found in Work Order '{work_order_number}' — all blades may already have slots assigned.",
        )
    return blades


async def _check_lptr_slot_conflicts(
    db: AsyncSession, work_order_number: str, slot_by_blade_id: dict
) -> None:
    """Guard against Stage 1 and Stage 2 (two independent save requests)
    landing on the same physical slot number for two different blades —
    nothing else stops that, since each stage only validates duplicates
    within its own request body.

    Scoped to this work order only: each work order/batch has its own
    independent slot numbering, not a numbering space shared across every
    LPTR work order that has ever run — a slot number is only meaningful
    relative to the 90 blades of the batch that's currently on the rig.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation

    # is_active marks the current live allocation *row for that blade* — it
    # is never flipped off once the blade leaves the slot, so within this
    # same work order it does not by itself mean "still physically on the
    # rig". Only blades still sitting in the slot (not yet through
    # balancing) actually hold it — this also lets a REJECTED -> REOPENED
    # blade's stale prior-cycle row be superseded instead of blocking the
    # new cycle's assignment.
    occupying_statuses = [BladeStatus.SLOT_ASSIGNED, BladeStatus.BALANCING_IN_PROGRESS]

    target_slot_numbers = {str(s) for s in slot_by_blade_id.values()}
    conflicts = (
        await db.execute(
            select(SlotAllocation.slot_number, Blade.serial_number)
            .join(Blade, Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.slot_number.in_(target_slot_numbers),
                SlotAllocation.is_active.is_(True),
                Blade.blade_type == BladeType.LPTR,
                Blade.work_order_number == work_order_number,
                Blade.status.in_(occupying_statuses),
                SlotAllocation.blade_id.notin_(slot_by_blade_id.keys()),
            )
        )
    ).all()
    if conflicts:
        detail = ", ".join(f"slot {slot} (blade {serial})" for slot, serial in conflicts)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Target slot(s) already occupied by another active allocation: {detail}",
        )


async def _apply_lptr_slot_assignments(
    db: AsyncSession,
    work_order_number: str,
    assigned_blades: list,
    slot_by_blade_id: dict,
    stage: int,
    unbalance_slot: int,
    total_slots: int,
    current_user: Any,
) -> None:
    from app.models.slot_allocation import SlotAllocation
    from app.workflows.state_machine import WorkflowEngine

    await _check_lptr_slot_conflicts(db, work_order_number, slot_by_blade_id)

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
        db.add(SlotAllocation(
            blade_id=blade.id,
            slot_number=slot_number,
            stage=stage,
            allocated_by_id=current_user.id,
        ))

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


async def _notify_lptr_slots_assigned(work_order_number: str, blade_count: int, stage: int) -> None:
    """Notify OH that this stage's slots are now assigned."""
    from app.notifications.service import NotificationService
    from app.models.notification import NotificationType
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            svc = NotificationService(db)
            await svc.notify_roles(
                roles=["OH_OPERATOR", "SUPER_ADMIN"],
                title=f"Work Order {work_order_number} — LPTR stage {stage} slots assigned",
                body=f"Assembly has assigned disc slots to {blade_count} blade(s) for LPTR stage {stage} in Work Order {work_order_number}.",
                notification_type=NotificationType.SLOT_PENDING,
                metadata={"work_order_number": work_order_number, "stage": stage, "blades_assigned": blade_count},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_slots_assigned_failed", error=str(exc))


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
    from app.models.work_order_event import WorkOrderEvent

    stage, unbalance_slot, total_slots, slot_by_blade_id = _parse_lptr_slot_body(
        body, LPTR_STAGE1_BLADE_COUNT, LPTR_STAGE2_BLADE_COUNT
    )

    await _check_work_order_accepted_for_slots(db, work_order_number)
    await _check_lptr_stage2_prerequisite(db, work_order_number, stage)

    blades = await _fetch_eligible_lptr_blades(db, work_order_number)

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
    await _apply_lptr_slot_assignments(
        db, work_order_number, assigned_blades, slot_by_blade_id, stage, unbalance_slot, total_slots, current_user
    )

    await db.commit()

    # Record the work-order-level audit event for "Slots Allocated" so it shows
    # up in the work order's Event History alongside Sent/Received/Accepted.
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

    background_tasks.add_task(
        _notify_lptr_slots_assigned, work_order_number, len(assigned_blades), stage
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


def _parse_hptr_slot_body(body: dict) -> tuple[int, int, Any, dict[uuid.UUID, int]]:
    """Parse and validate the raw request body for HPTR slot assignment.

    Returns (start_slot, total_slots, unbalance_value, slot_by_blade_id) or
    raises HTTPException 422 identifying which part of the payload is invalid.
    """
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

    return start_slot, total_slots, unbalance_value, slot_by_blade_id


async def _fetch_eligible_hptr_blades(db: AsyncSession, work_order_number: str, slot_by_blade_id: dict) -> list:
    """Fetch this work order's MEASUREMENTS_RECORDED HPTR blades and check the
    submitted assignments cover exactly that set (HPTR is single-shot: every
    eligible blade must get a slot, unlike LPTR's two-stage subset)."""
    from app.models.blade import Blade

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
    return blades


async def _fetch_latest_weight_map(db: AsyncSession, blade_ids: list) -> dict:
    """Latest INITIAL weight_grams per blade id, purely to report the W1/W2
    split back to the caller for audit/confirmation."""
    from app.models.measurement import Measurement
    from sqlalchemy import func as sa_func

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
    return {row.blade_id: float(row.weight_grams or 0) for row in meas_rows}


def _compute_hptr_half_totals(blades: list, slot_by_blade_id: dict, weight_map: dict, half: int) -> tuple[float, float]:
    w1_total = 0.0
    w2_total = 0.0
    for blade in blades:
        slot = slot_by_blade_id[blade.id]
        weight = weight_map.get(blade.id, 0.0)
        if slot <= half:
            w1_total += weight
        else:
            w2_total += weight
    return w1_total, w2_total


async def _apply_hptr_slot_assignments(
    db: AsyncSession,
    blades: list,
    slot_by_blade_id: dict,
    start_slot: int,
    unbalance_value: Any,
    current_user: Any,
) -> None:
    from app.models.slot_allocation import SlotAllocation
    from app.workflows.state_machine import WorkflowEngine

    unbalance_note = f", unbalance {unbalance_value} g" if unbalance_value is not None else ""
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

        db.add(SlotAllocation(
            blade_id=blade.id,
            slot_number=slot_number,
            allocated_by_id=current_user.id,
        ))

        await WorkflowEngine(db).transition(
            blade=blade,
            to_status=BladeStatus.SLOT_ASSIGNED,
            user=current_user,
            station_id=None,
            remarks=f"HPTR slot {slot_number} assigned (start slot {start_slot}{unbalance_note})",
        )


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
    from app.models.work_order_event import WorkOrderEvent

    start_slot, total_slots, unbalance_value, slot_by_blade_id = _parse_hptr_slot_body(body)
    blades = await _fetch_eligible_hptr_blades(db, work_order_number, slot_by_blade_id)

    # Fetch latest INITIAL weight_grams per blade, purely to report the W1/W2
    # split back to the caller for audit/confirmation — the swap decision
    # itself already happened client-side before this call.
    weight_map = await _fetch_latest_weight_map(db, list(slot_by_blade_id.keys()))

    half = total_slots // 2  # W1 = 1..half, W2 = half+1..total_slots
    w1_total, w2_total = _compute_hptr_half_totals(blades, slot_by_blade_id, weight_map, half)

    await _apply_hptr_slot_assignments(db, blades, slot_by_blade_id, start_slot, unbalance_value, current_user)

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
        "message": f"{len(blades)} HPTR blade(s) marked balanced.",
    }


# ---------------------------------------------------------------------------
# POST /{work_order_number}/start-final-verification
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/start-final-verification",
    status_code=status.HTTP_200_OK,
    summary="OH starts final verification for a work order's balanced HPTR blades",
)
async def start_final_verification(
    work_order_number: str,
    body: dict,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    HPTR blades never leave OH, so unlike LPTR (which reaches
    ``FINAL_VERIFICATION`` via ``accept-return`` once Assembly physically
    returns the set) they need a direct trigger — transitions every
    ``BALANCING_COMPLETED`` blade in *work_order_number* to
    ``FINAL_VERIFICATION``.

    Only applies to HPTR work orders — calling this on an LPTR work order
    returns 422 (use ``accept-return`` instead).
    """
    from app.models.blade import Blade
    from app.models.work_order import WorkOrder
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

    remarks = (body or {}).get("remarks") or "Final verification started by OH"

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                Blade.status == BladeStatus.BALANCING_COMPLETED,
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No balanced HPTR blades pending final verification found for Work Order '{work_order_number}'",
        )

    engine = WorkflowEngine(db)
    for blade in blades:
        await engine.transition(
            blade=blade,
            to_status=BladeStatus.FINAL_VERIFICATION,
            user=current_user,
            station_id=None,
            remarks=remarks,
        )

    await db.commit()

    logger.info(
        "work_order_hptr_final_verification_started",
        work_order=work_order_number,
        blades=len(blades),
    )
    return {
        "work_order_number": work_order_number,
        "blades_started": len(blades),
        "message": f"{len(blades)} HPTR blade(s) moved to Final Verification.",
    }


# ---------------------------------------------------------------------------
# POST /{work_order_number}/complete-lptr-balancing
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/complete-lptr-balancing",
    status_code=status.HTTP_200_OK,
    summary="Mark a work order's saved LPTR slot allocation as balanced/complete",
)
async def complete_lptr_balancing(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Physical balancing testing confirmed the set is balanced — transition
    every LPTR blade in the work order's active slot allocation (both
    Stage 1's 46 and Stage 2's 44 must already be saved — see the
    ``still_awaiting_slot`` guard below) from
    ``SLOT_ASSIGNED``/``BALANCING_IN_PROGRESS`` to ``BALANCING_COMPLETED``
    and mark each slot allocation as balanced.

    Mirrors ``complete_hptr_balancing`` (which has no stages to gate on),
    except this runs at Assembly (720 Hanger) rather than OH, since that's
    where LPTR slot allocation and balancing happen.

    Only applies to LPTR work orders — calling this on an HPTR work order
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
    if work_order.blade_type != BladeType.LPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' is {work_order.blade_type.value} — "
                "this endpoint only applies to LPTR work orders."
            ),
        )

    remarks = (body or {}).get("remarks") or "Physical balancing testing confirmed — set balanced"

    # Both stages must be saved before balancing can be confirmed — otherwise
    # this would mark the work order BALANCED (and ready to send back to OH)
    # after only Stage 1's 46 blades, silently skipping Stage 2 entirely.
    still_awaiting_slot = (
        await db.execute(
            select(func.count(Blade.id)).where(
                Blade.work_order_number == work_order_number,
                Blade.blade_type == BladeType.LPTR,
                Blade.deleted_at.is_(None),
                Blade.status.in_([
                    BladeStatus.SENT_TO_ASSEMBLY,
                    BladeStatus.ASSEMBLY_RECEIVED,
                    BladeStatus.ASSEMBLY_VERIFIED,
                ]),
            )
        )
    ).scalar_one()
    if still_awaiting_slot > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{still_awaiting_slot} LPTR blade(s) in Work Order '{work_order_number}' are still "
                "awaiting slot assignment — both Stage 1 and Stage 2 must be saved before "
                "confirming physical balancing."
            ),
        )

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
            detail=f"No LPTR blades pending balancing found for Work Order '{work_order_number}'",
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
        remarks=f"{len(blades)} LPTR blade(s) confirmed balanced. {remarks}",
        changes={"blades_balanced": len(blades)},
    ))
    await db.commit()

    actor_name = getattr(current_user, "username", str(current_user.id))

    async def _notify_lptr_balancing_complete(_work_order: str, _count: int, _actor: str) -> None:
        from app.notifications.service import NotificationService
        from app.models.notification import NotificationType
        from app.db.session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as _db:
                svc = NotificationService(_db)
                await svc.notify_roles(
                    roles=["OH_OPERATOR", "SUPER_ADMIN"],
                    title=f"Work Order {_work_order} — LPTR balancing complete",
                    body=(
                        f"{_actor} confirmed LPTR balancing complete for Work Order {_work_order} "
                        f"({_count} blade(s))."
                    ),
                    notification_type=NotificationType.WORKFLOW_UPDATED,
                    metadata={"work_order_number": _work_order},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify_lptr_balancing_complete_failed", error=str(exc))

    background_tasks.add_task(_notify_lptr_balancing_complete, work_order_number, len(blades), actor_name)

    logger.info("work_order_lptr_balancing_completed", work_order=work_order_number, blades=len(blades))
    return {
        "work_order_number": work_order_number,
        "blades_completed": len(blades),
        "message": f"{len(blades)} LPTR blade(s) marked balanced.",
    }


# ---------------------------------------------------------------------------
# POST /{work_order_number}/return-to-oh
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/return-to-oh",
    status_code=status.HTTP_200_OK,
    summary="Assembly reports the LPTR balancing task complete and sends the work order back to OH",
)
async def return_work_order_to_oh(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Assembly formally reports this work order's task complete — transitions
    every LPTR blade currently ``BALANCING_COMPLETED`` to ``RETURNED_TO_OH``
    and logs a ``RETURNED_TO_OH`` batch event. This is a deliberate, separate
    step from "Physical balancing confirmed?" (``complete-lptr-balancing``)
    since the blades may not physically travel back to OH immediately.

    Only applies to LPTR work orders — calling this on an HPTR work order
    returns 422, since HPTR blades never leave OH (see state_machine.py).
    """
    from app.models.blade import Blade
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
    if work_order.blade_type != BladeType.LPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Work Order '{work_order_number}' is {work_order.blade_type.value} — "
                "this endpoint only applies to LPTR work orders."
            ),
        )

    remarks = (body or {}).get("remarks") or "Assembly task complete — sent back to OH"

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                Blade.status == BladeStatus.BALANCING_COMPLETED,
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No balanced LPTR blades pending return-to-OH found for Work Order '{work_order_number}'",
        )

    engine = WorkflowEngine(db)
    for blade in blades:
        await engine.transition(
            blade=blade,
            to_status=BladeStatus.RETURNED_TO_OH,
            user=current_user,
            station_id=None,
            remarks=remarks,
        )

    await db.commit()

    db.add(WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.RETURNED_TO_OH,
        action_by_id=current_user.id,
        remarks=f"{len(blades)} LPTR blade(s) sent back to OH. {remarks}",
        changes={"blades_returned": len(blades)},
    ))
    await db.commit()

    actor_name = getattr(current_user, "username", str(current_user.id))

    async def _notify_returned_to_oh(_wo: str, _count: int, _actor: str) -> None:
        from app.notifications.service import NotificationService
        from app.models.notification import NotificationType
        from app.db.session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as _db:
                svc = NotificationService(_db)
                await svc.notify_roles(
                    roles=["OH_OPERATOR", "SUPER_ADMIN"],
                    title=f"Work Order {_wo} — returned from Assembly",
                    body=(
                        f"{_actor} sent Work Order {_wo} back to OH ({_count} blade(s)). "
                        "Accept it in the OH Work Order Overview to continue."
                    ),
                    notification_type=NotificationType.WORKFLOW_UPDATED,
                    metadata={"work_order_number": _wo},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify_returned_to_oh_failed", error=str(exc))

    background_tasks.add_task(_notify_returned_to_oh, work_order_number, len(blades), actor_name)

    logger.info("work_order_returned_to_oh", work_order=work_order_number, blades=len(blades))
    return {
        "work_order_number": work_order_number,
        "blades_returned": len(blades),
        "message": f"{len(blades)} LPTR blade(s) sent back to OH.",
    }


# ---------------------------------------------------------------------------
# POST /{work_order_number}/accept-return
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/accept-return",
    status_code=status.HTTP_201_CREATED,
    summary="OH accepts a work order returned from Assembly",
)
async def accept_returned_work_order(
    work_order_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    OH operator acknowledges and accepts a work order returned from Assembly —
    transitions every blade currently ``RETURNED_TO_OH`` to
    ``FINAL_VERIFICATION`` and logs an ``ACCEPTED_BY_OH`` batch event.
    """
    from app.models.blade import Blade
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

    remarks = (body or {}).get("remarks") or "OH accepted return from Assembly"

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                Blade.status == BladeStatus.RETURNED_TO_OH,
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No blades pending OH acceptance found for Work Order '{work_order_number}'",
        )

    engine = WorkflowEngine(db)
    for blade in blades:
        await engine.transition(
            blade=blade,
            to_status=BladeStatus.FINAL_VERIFICATION,
            user=current_user,
            station_id=None,
            remarks=remarks,
        )

    await db.commit()

    ev = WorkOrderEvent(
        work_order_number=work_order_number,
        event_type=BatchEventType.ACCEPTED_BY_OH,
        action_by_id=current_user.id,
        remarks=remarks,
        changes={"blades_accepted": len(blades)},
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    actor_name = getattr(current_user, "username", str(current_user.id))

    async def _notify_accepted_by_oh(_wo: str, _actor: str, _remarks: str | None) -> None:
        from app.notifications.service import NotificationService
        from app.models.notification import NotificationType
        from app.db.session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as _db:
                svc = NotificationService(_db)
                body_text = f"{_actor} accepted Work Order {_wo} back at OH."
                if _remarks:
                    body_text += f" Remarks: {_remarks}"
                await svc.notify_roles(
                    roles=["ASSEMBLY_OPERATOR", "SUPER_ADMIN"],
                    title=f"Work Order {_wo} — accepted by OH",
                    body=body_text,
                    notification_type=NotificationType.WORKFLOW_UPDATED,
                    metadata={"work_order_number": _wo},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify_accepted_by_oh_failed", error=str(exc))

    background_tasks.add_task(_notify_accepted_by_oh, work_order_number, actor_name, remarks)

    logger.info("work_order_accepted_by_oh", work_order=work_order_number)
    return _event_to_dict(ev)


# ---------------------------------------------------------------------------
# POST /{work_order_number}/complete-final-verification
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/complete-final-verification",
    status_code=status.HTTP_200_OK,
    summary="OH completes final verification for every blade in a work order",
)
async def complete_final_verification(
    work_order_number: str,
    body: dict,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    OH operator confirms final verification is done for every blade in
    *work_order_number* currently ``FINAL_VERIFICATION`` — transitions them
    all to ``COMPLETED`` in one action.
    """
    from app.models.blade import Blade
    from app.models.work_order import WorkOrder
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

    remarks = (body or {}).get("remarks") or "Final verification completed by OH"

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.work_order_number == work_order_number,
                Blade.deleted_at.is_(None),
                Blade.status == BladeStatus.FINAL_VERIFICATION,
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No blades pending final verification found for Work Order '{work_order_number}'",
        )

    engine = WorkflowEngine(db)
    for blade in blades:
        await engine.transition(
            blade=blade,
            to_status=BladeStatus.COMPLETED,
            user=current_user,
            station_id=None,
            remarks=remarks,
        )

    await db.commit()

    logger.info(
        "work_order_final_verification_completed",
        work_order=work_order_number,
        blades=len(blades),
    )
    return {
        "work_order_number": work_order_number,
        "blades_completed": len(blades),
        "message": f"{len(blades)} blade(s) marked completed — final verification done.",
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
# POST /{work_order_number}/complete-rocking-creep
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/complete-rocking-creep",
    status_code=status.HTTP_200_OK,
    summary="Confirm Rocking & Creep entry is complete for a work order",
)
def _find_blades_missing_rocking_creep(blades: list, meas_map: dict) -> tuple[list[str], bool]:
    """Serials still missing a required Rocking (and Creep, for LPTR) value,
    plus whether any LPTR blade is present (for the error message wording)."""
    missing_serials: list[str] = []
    any_lptr = False
    for blade in blades:
        meas = meas_map.get(blade.id)
        has_rocking = meas is not None and meas.rocking_value is not None
        needs_creep = blade.blade_type == BladeType.LPTR
        any_lptr = any_lptr or needs_creep
        has_creep = meas is not None and meas.creep_value is not None
        if not has_rocking or (needs_creep and not has_creep):
            missing_serials.append(blade.serial_number)
    return missing_serials, any_lptr


async def complete_rocking_creep(
    work_order_number: str,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    OH operator confirms every blade in *work_order_number* has its required
    Rocking (and Creep, for LPTR) value recorded. Marking this explicitly —
    rather than auto-detecting it — is what drops the work order out of the
    Rocking & Creep picker; idempotent if already marked complete.
    """
    from datetime import datetime, timezone

    from app.models.blade import Blade
    from app.models.measurement import Measurement
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

    if work_order.is_rocking_creep_complete:
        return {
            "work_order_number": work_order_number,
            "is_rocking_creep_complete": True,
            "completed_at": (
                work_order.rocking_creep_completed_at.isoformat()
                if work_order.rocking_creep_completed_at else None
            ),
        }

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
            detail=f"Work Order '{work_order_number}' has no blades",
        )

    blade_ids = [b.id for b in blades]
    meas_rows = (
        await db.execute(
            select(Measurement.blade_id, Measurement.rocking_value, Measurement.creep_value)
            .where(
                Measurement.blade_id.in_(blade_ids),
                Measurement.measurement_type == MeasurementType.INITIAL,
            )
        )
    ).all()
    meas_map = {r.blade_id: r for r in meas_rows}

    missing_serials, any_lptr = _find_blades_missing_rocking_creep(blades, meas_map)

    if missing_serials:
        missing_serials.sort()
        preview = ", ".join(missing_serials[:10])
        more = f" (+{len(missing_serials) - 10} more)" if len(missing_serials) > 10 else ""
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{len(missing_serials)} blade(s) still missing Rocking"
                f"{' or Creep' if any_lptr else ''} value(s): {preview}{more}"
            ),
        )

    work_order.is_rocking_creep_complete = True
    work_order.rocking_creep_completed_at = datetime.now(timezone.utc)
    work_order.rocking_creep_completed_by_id = current_user.id
    db.add(work_order)
    await db.commit()
    await db.refresh(work_order)

    logger.info(
        "work_order_rocking_creep_completed",
        work_order=work_order_number,
        blades=len(blades),
    )
    return {
        "work_order_number": work_order_number,
        "is_rocking_creep_complete": True,
        "completed_at": work_order.rocking_creep_completed_at.isoformat(),
    }


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
# POST /{work_order_number}/modify
# ---------------------------------------------------------------------------


_MODIFY_ALLOWED_FIELDS = {
    "weight_grams",
    "static_moment_gcm",
    "melt_number",
    "part_number",
    "work_order_number",
    "shop_order_number",
    "engine_number",
}


def _apply_blade_field_updates(blade, updated_fields: dict) -> dict:
    """Apply each allowed, actually-changed field from updated_fields onto
    blade. Returns {field: {"before": ..., "after": ...}} for what changed."""
    applied: dict = {}
    for field, new_value in updated_fields.items():
        if field not in _MODIFY_ALLOWED_FIELDS or new_value is None:
            continue
        old_value = getattr(blade, field, None)
        if old_value == new_value:
            continue
        setattr(blade, field, new_value)
        applied[field] = {"before": old_value, "after": new_value}
    return applied


async def _apply_one_modification(
    db: AsyncSession, mod: dict, work_order_number: str, current_user: Any, remarks: str
) -> tuple[str, dict] | None:
    """Validate, look up, and apply one modification entry. Returns
    (change_summary_key, applied_fields), or None if the entry was skipped
    (missing blade_id/updated fields, invalid uuid, blade not found, or no
    actual field changes)."""
    import uuid as _uuid
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    blade_id_str = mod.get("blade_id")
    updated_fields: dict = mod.get("updated", {})
    serial_number: str = mod.get("serial_number", "")

    if not blade_id_str or not updated_fields:
        return None

    try:
        blade_uuid = _uuid.UUID(blade_id_str)
    except (ValueError, TypeError):
        return None

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
        return None

    applied = _apply_blade_field_updates(blade, updated_fields)
    if not applied:
        return None

    sn_key = serial_number or str(blade.id)
    db.add(WorkflowLog(
        blade_id=blade.id,
        from_status=blade.status,
        to_status=blade.status,
        action_by_id=current_user.id,
        remarks=f"Fields modified: {', '.join(applied.keys())}. {remarks}".strip(". "),
    ))
    return sn_key, applied


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
    remarks: str = body.get("remarks") or ""
    raw_mods: list = body.get("modifications", [])

    changes_summary: dict = {}
    for mod in raw_mods:
        result = await _apply_one_modification(db, mod, work_order_number, current_user, remarks)
        if result:
            sn_key, applied = result
            changes_summary[sn_key] = applied

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
# POST /{work_order_number}/rows/bulk-import  (grid-entry: Excel upload)
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/rows/bulk-import",
    status_code=status.HTTP_200_OK,
    summary="Bulk-fill grid rows from an uploaded .xlsx/.xls (S.No / Melt Number / Weight)",
    response_model=WorkOrderBulkImportResponse,
)
async def bulk_import_work_order_rows(
    work_order_number: str,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(description="Excel (.xlsx or .xls) file with S.No / Melt Number / Weight columns")],
) -> WorkOrderBulkImportResponse:
    """
    Parses an uploaded Excel sheet and writes its rows into this Work
    Order's grid via the same per-row logic as manual autosave — only S.No,
    Melt Number, and the raw Weight reading are read; Weight (g)/Static
    Moment are recomputed server-side exactly as for manual entry.

    Partial success: bad rows (out-of-range/duplicate S.No, non-numeric
    weight, S.No not found for this Work Order) are skipped and reported in
    ``errors`` — valid rows still import.
    """
    from app.services.excel_import import parse_work_order_rows

    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx or .xls files are supported.",
        )

    content = await file.read()
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB",
        )

    parsed = parse_work_order_rows(content)

    service = WorkOrderService(db)
    response = await service.bulk_import_rows(work_order_number, parsed.rows, current_user)

    # Parse-time errors (bad header, unreadable file, bad rows) are prepended
    # to any row-level errors raised while writing (e.g. S.No not found).
    parse_errors = [
        WorkOrderBulkImportError(s_no=None, message=f"Sheet row {e.row}: {e.message}" if e.row else e.message)
        for e in parsed.errors
    ]
    response.errors = parse_errors + response.errors
    response.skipped_count += len(parse_errors)

    logger.info(
        "work_order_bulk_import",
        work_order=work_order_number,
        filename=filename,
        imported=response.imported_count,
        skipped=response.skipped_count,
    )
    return response


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
