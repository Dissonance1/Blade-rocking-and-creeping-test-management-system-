"""
Batch workflow endpoints.

GET  /batches/                                  — list all batches with current status
GET  /batches/{batch_number}                    — batch detail + event history
POST /batches/{batch_number}/send-to-assembly   — OH bulk-sends all eligible blades to Assembly
POST /batches/{batch_number}/receive            — Assembly marks batch received
POST /batches/{batch_number}/accept             — Assembly accepts batch
POST /batches/{batch_number}/reject             — Assembly rejects batch
POST /batches/{batch_number}/modify             — Assembly flags modifications
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import BatchEventType, BladeStatus, NotificationType

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
        "SENT_TO_ASSEMBLY": "Sent to Assembly",
        "RECEIVED_BY_ASSEMBLY": "Received by Assembly",
        "ACCEPTED": "Accepted",
        "REJECTED": "Rejected",
        "MODIFIED": "Modified",
    }.get(status_val, status_val)


def _event_to_dict(ev: Any) -> dict:
    return {
        "id": str(ev.id),
        "batch_number": ev.batch_number,
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
    batch_number: str,
    event_type: BatchEventType,
    actor_username: str,
    remarks: str | None,
    changes: dict | None = None,
) -> None:
    """Send notification to all OH_OPERATORs and SUPER_ADMINs about a batch event.

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

    title = f"Batch {batch_number} — {event_labels.get(event_type, event_type.value)}"
    body = f"Assembly has marked batch {batch_number} as {event_labels.get(event_type, event_type.value).lower()}."
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
            "batch_notification_sent",
            batch=batch_number,
            event_type=event_type.value,
            recipients=len(target_users),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("batch_notification_failed", error=str(exc))


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("/", status_code=status.HTTP_200_OK, summary="List all batches with current status")
async def list_batches(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    has_slot_allocations: bool = False,
) -> list:
    """
    Return a summary of every batch known to the system, ordered by most
    recently created.  The ``current_status`` field reflects:
    - The latest explicit Assembly action (RECEIVED/ACCEPTED/REJECTED/MODIFIED), or
    - ``SENT_TO_ASSEMBLY`` if any blades have been sent, or
    - ``CREATED`` otherwise.
    """
    from app.models.batch_event import BatchEvent
    from app.models.batch_group import BatchGroup
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    # ── Blade counts per batch ─────────────────────────────────────────────
    blade_rows = (
        await db.execute(
            select(
                Blade.batch_number,
                func.count(Blade.id).label("blade_count"),
                func.sum(
                    case(
                        (Blade.status.in_(list(_ASSEMBLY_STATUSES)), 1),
                        else_=0,
                    )
                ).label("blades_sent"),
                func.min(Blade.created_at).label("first_blade_at"),
            )
            .where(Blade.batch_number.isnot(None), Blade.deleted_at.is_(None))
            .group_by(Blade.batch_number)
            .order_by(func.min(Blade.created_at).desc())
        )
    ).all()

    if not blade_rows:
        return []

    # If caller only wants batches with at least one active slot allocation, filter here
    if has_slot_allocations:
        from app.models.slot_allocation import SlotAllocation
        slotted = set(
            (
                await db.execute(
                    select(Blade.batch_number)
                    .join(SlotAllocation, SlotAllocation.blade_id == Blade.id)
                    .where(
                        SlotAllocation.is_active.is_(True),
                        Blade.deleted_at.is_(None),
                        Blade.batch_number.isnot(None),
                    )
                    .distinct()
                )
            ).scalars().all()
        )
        blade_rows = [r for r in blade_rows if r.batch_number in slotted]
        if not blade_rows:
            return []

    batch_numbers = [r.batch_number for r in blade_rows]

    # ── Latest event per batch ─────────────────────────────────────────────
    # Subquery: rank events by timestamp desc per batch
    from sqlalchemy import over, desc
    from sqlalchemy.sql.functions import rank

    latest_evt_subq = (
        select(
            BatchEvent,
            func.row_number().over(
                partition_by=BatchEvent.batch_number,
                order_by=BatchEvent.timestamp.desc(),
            ).label("rn"),
        )
        .where(BatchEvent.batch_number.in_(batch_numbers))
        .subquery()
    )
    latest_events_rows = (
        await db.execute(
            select(BatchEvent)
            .where(
                BatchEvent.batch_number.in_(batch_numbers),
                BatchEvent.id.in_(
                    select(latest_evt_subq.c.id).where(latest_evt_subq.c.rn == 1)
                ),
            )
        )
    ).scalars().all()
    latest_event_map: dict[str, Any] = {ev.batch_number: ev for ev in latest_events_rows}

    # ── First SENT timestamp per batch ─────────────────────────────────────
    sent_rows = (
        await db.execute(
            select(
                Blade.batch_number,
                func.min(WorkflowLog.timestamp).label("first_sent_at"),
            )
            .join(WorkflowLog, WorkflowLog.blade_id == Blade.id)
            .where(
                Blade.batch_number.in_(batch_numbers),
                WorkflowLog.to_status == BladeStatus.SENT_TO_ASSEMBLY,
            )
            .group_by(Blade.batch_number)
        )
    ).all()
    sent_at_map = {r.batch_number: r.first_sent_at for r in sent_rows}

    # ── BatchGroup metadata ────────────────────────────────────────────────
    bg_rows = (
        await db.execute(
            select(BatchGroup).where(BatchGroup.batch_number.in_(batch_numbers))
        )
    ).scalars().all()
    bg_map = {bg.batch_number: bg for bg in bg_rows}

    # ── Assemble response ──────────────────────────────────────────────────
    result = []
    for row in blade_rows:
        bn = row.batch_number
        latest_ev = latest_event_map.get(bn)
        bg = bg_map.get(bn)
        cur_status = _derive_status(
            latest_ev.event_type if latest_ev else None,
            row.blades_sent or 0,
        )
        result.append({
            "batch_number": bn,
            "blade_count": row.blade_count,
            "blades_sent": row.blades_sent or 0,
            "current_status": cur_status,
            "current_status_label": _status_label(cur_status),
            "first_blade_at": row.first_blade_at.isoformat() if row.first_blade_at else None,
            "first_sent_at": sent_at_map.get(bn, None) and sent_at_map[bn].isoformat(),
            "last_event": _event_to_dict(latest_ev) if latest_ev else None,
            "work_order_number": bg.work_order_number if bg else None,
            "part_number": bg.part_number if bg else None,
            "engine_number": bg.engine_number if bg else None,
            "nomenclature": bg.nomenclature if bg else None,
        })
    return result


# ---------------------------------------------------------------------------
# GET /{batch_number}
# ---------------------------------------------------------------------------


@router.get("/{batch_number}", status_code=status.HTTP_200_OK, summary="Batch detail with event history")
async def get_batch(
    batch_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Return full detail for a single batch: metadata, blade list summary,
    and the complete event history (most recent first).
    """
    from app.models.batch_event import BatchEvent
    from app.models.batch_group import BatchGroup
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    blade_agg = (
        await db.execute(
            select(
                func.count(Blade.id).label("blade_count"),
                func.sum(
                    case(
                        (Blade.status.in_(list(_ASSEMBLY_STATUSES)), 1),
                        else_=0,
                    )
                ).label("blades_sent"),
                func.min(Blade.created_at).label("first_blade_at"),
            )
            .where(Blade.batch_number == batch_number, Blade.deleted_at.is_(None))
        )
    ).one()

    if blade_agg.blade_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_number}' not found",
        )

    # Events — newest first
    events = (
        await db.execute(
            select(BatchEvent)
            .where(BatchEvent.batch_number == batch_number)
            .order_by(BatchEvent.timestamp.desc())
        )
    ).scalars().all()

    # First sent timestamp
    sent_row = (
        await db.execute(
            select(func.min(WorkflowLog.timestamp).label("first_sent_at"))
            .join(Blade, Blade.id == WorkflowLog.blade_id)
            .where(
                Blade.batch_number == batch_number,
                WorkflowLog.to_status == BladeStatus.SENT_TO_ASSEMBLY,
            )
        )
    ).one()

    bg = (
        await db.execute(
            select(BatchGroup).where(BatchGroup.batch_number == batch_number)
        )
    ).scalar_one_or_none()

    latest_ev = events[0] if events else None
    cur_status = _derive_status(
        latest_ev.event_type if latest_ev else None,
        blade_agg.blades_sent or 0,
    )

    return {
        "batch_number": batch_number,
        "blade_count": blade_agg.blade_count,
        "blades_sent": blade_agg.blades_sent or 0,
        "current_status": cur_status,
        "current_status_label": _status_label(cur_status),
        "first_blade_at": blade_agg.first_blade_at.isoformat() if blade_agg.first_blade_at else None,
        "first_sent_at": sent_row.first_sent_at.isoformat() if sent_row.first_sent_at else None,
        "last_event": _event_to_dict(latest_ev) if latest_ev else None,
        "events": [_event_to_dict(ev) for ev in events],
        "work_order_number": bg.work_order_number if bg else None,
        "part_number": bg.part_number if bg else None,
        "engine_number": bg.engine_number if bg else None,
        "nomenclature": bg.nomenclature if bg else None,
    }


# ---------------------------------------------------------------------------
# Shared action helper
# ---------------------------------------------------------------------------


async def _create_batch_event(
    batch_number: str,
    event_type: BatchEventType,
    remarks: str | None,
    changes: dict | None,
    current_user: Any,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> dict:
    """Create a BatchEvent, commit it, fire notifications, return dict."""
    from app.models.batch_event import BatchEvent
    from app.models.blade import Blade

    # Verify batch exists
    count = (
        await db.execute(
            select(func.count(Blade.id)).where(
                Blade.batch_number == batch_number,
                Blade.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_number}' not found",
        )

    ev = BatchEvent(
        batch_number=batch_number,
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
        _notify_oh_operators, batch_number, event_type, actor_name, remarks, changes
    )

    logger.info("batch_event_created", batch=batch_number, event_type=event_type.value)
    return _event_to_dict(ev)


# ---------------------------------------------------------------------------
# POST /{batch_number}/send-to-assembly  (OH bulk action)
# ---------------------------------------------------------------------------


_OH_ELIGIBLE_STATUSES = {
    "CREATED",
    "OH_INSPECTION",
    "MEASUREMENTS_RECORDED",
    "REOPENED",
}


@router.post(
    "/{batch_number}/send-to-assembly",
    status_code=status.HTTP_200_OK,
    summary="OH bulk-sends all eligible blades in a batch to Assembly",
)
async def send_batch_to_assembly(
    batch_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Transitions all OH-side blades in the batch to ``SENT_TO_ASSEMBLY`` in a
    single operation.  Only blades in CREATED, OH_INSPECTION,
    MEASUREMENTS_RECORDED, or REOPENED status are eligible.  Blades already
    in Assembly-side statuses are skipped.

    Returns a summary: total blade count, how many were sent, how many skipped.
    """
    from app.models.batch_event import BatchEvent
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog
    from app.notifications.service import NotificationService

    remarks = body.get("remarks") or f"Batch {batch_number} sent to Assembly"

    # Fetch all non-deleted blades in this batch
    blades = (
        await db.execute(
            select(Blade).where(
                Blade.batch_number == batch_number,
                Blade.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_number}' not found",
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
                f"No eligible blades found in batch '{batch_number}'. "
                f"All {skipped_count} blades are already in Assembly or completed."
            ),
        )

    await db.commit()

    # Record the batch-level audit event for "Sent to Assembly"
    ev = BatchEvent(
        batch_number=batch_number,
        event_type=BatchEventType.SENT_TO_ASSEMBLY,
        action_by_id=current_user.id,
        remarks=remarks,
        changes={"sent_count": sent_count, "skipped_count": skipped_count},
    )
    db.add(ev)
    await db.commit()

    actor_name = getattr(current_user, "username", str(current_user.id))

    # Notify assembly operators — use a fresh session (request session closes before BG task runs)
    async def _notify_assembly(
        _batch_number: str, _actor_name: str, _sent_count: int, _skipped_count: int
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
                        title=f"Batch {_batch_number} ready for Assembly",
                        body=(
                            f"OH ({_actor_name}) has sent {_sent_count} blade(s) from batch {_batch_number} to Assembly."
                            + (f" {_skipped_count} blade(s) skipped." if _skipped_count else "")
                        ),
                        notification_type=NotificationType.WORKFLOW_UPDATED,
                    )
            logger.info("batch_send_notification_sent", batch=_batch_number, recipients=len(target_users))
        except Exception as exc:  # noqa: BLE001
            logger.warning("batch_send_notification_failed", error=str(exc))

    background_tasks.add_task(_notify_assembly, batch_number, actor_name, sent_count, skipped_count)

    logger.info("batch_sent_to_assembly", batch=batch_number, sent=sent_count, skipped=skipped_count)
    return {
        "batch_number": batch_number,
        "total_blades": len(blades),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "message": (
            f"{sent_count} blade(s) sent to Assembly."
            + (f" {skipped_count} already in Assembly." if skipped_count else "")
        ),
    }


# ---------------------------------------------------------------------------
# POST /{batch_number}/assign-slot  (Assembly bulk slot assignment)
# ---------------------------------------------------------------------------


@router.post(
    "/{batch_number}/assign-slot",
    status_code=status.HTTP_200_OK,
    summary="Assembly bulk-assigns computed slots to all incoming blades in a batch",
)
async def assign_batch_slot(
    batch_number: str,
    body: dict,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Runs the balancing algorithm over all SENT_TO_ASSEMBLY blades in the
    batch and assigns each one a computed disc slot.

    Algorithm: sort blades by static_moment_gcm descending (heaviest first),
    then assign slots starting at ``imbalance_slot`` and stepping through
    positions: slot_i = ((K - 1 + i) % N) + 1.

    Also transitions each blade from SENT_TO_ASSEMBLY → SLOT_ASSIGNED.
    """
    import math
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.models.workflow import WorkflowLog

    imbalance_slot: int = int(body.get("imbalance_slot", 0))
    total_slots: int = int(body.get("total_slots", 80))

    if imbalance_slot < 1 or imbalance_slot > total_slots:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"imbalance_slot must be between 1 and {total_slots}",
        )

    blades = (
        await db.execute(
            select(Blade).where(
                Blade.batch_number == batch_number,
                Blade.status == BladeStatus.SENT_TO_ASSEMBLY,
                Blade.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No incoming (SENT_TO_ASSEMBLY) blades found in batch '{batch_number}'",
        )

    # Fetch latest INITIAL measurement static_moment_gcm for each blade
    from app.models.measurement import Measurement
    from sqlalchemy import func as sa_func

    blade_ids = [b.id for b in blades]
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
            select(Measurement.blade_id, Measurement.static_moment_gcm)
            .join(
                subq,
                (Measurement.blade_id == subq.c.blade_id)
                & (Measurement.measured_at == subq.c.latest_at),
            )
        )
    ).all()
    sm_map: dict = {str(row.blade_id): float(row.static_moment_gcm or 0) for row in meas_rows}

    # Sort heaviest static moment first, then interleave:
    # first half (heavy) + reversed second half (light) so that
    # each heavy blade is placed directly opposite a light blade.
    sorted_blades = sorted(blades, key=lambda b: -sm_map.get(str(b.id), 0))
    half = len(sorted_blades) // 2
    interleaved = sorted_blades[:half] + list(reversed(sorted_blades[half:]))

    N = total_slots
    K = imbalance_slot

    for i, blade in enumerate(interleaved):
        computed_slot = str(((K - 1 + i) % N) + 1)

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
            slot_number=computed_slot,
            allocated_by_id=current_user.id,
        )
        db.add(alloc)

        # Transition blade status
        prev_status = blade.status
        blade.status = BladeStatus.SLOT_ASSIGNED
        log = WorkflowLog(
            blade_id=blade.id,
            from_status=prev_status,
            to_status=BladeStatus.SLOT_ASSIGNED,
            action_by_id=current_user.id,
            remarks=(
                f"Slot {computed_slot} assigned via batch balancing "
                f"(imbalance at slot {K}, disc has {N} slots)"
            ),
        )
        db.add(log)

    await db.commit()

    logger.info(
        "batch_slots_assigned",
        batch=batch_number,
        blades=len(sorted_blades),
        imbalance_slot=K,
        total_slots=N,
    )
    return {
        "batch_number": batch_number,
        "blades_assigned": len(sorted_blades),
        "imbalance_slot": K,
        "total_slots": N,
        "message": f"{len(sorted_blades)} blade(s) assigned to computed disc slots.",
    }


# ---------------------------------------------------------------------------
# GET /{batch_number}/rocking-creep
# ---------------------------------------------------------------------------


@router.get(
    "/{batch_number}/rocking-creep",
    status_code=status.HTTP_200_OK,
    summary="Get all blades in a batch with slot numbers and rocking/creep values",
)
async def get_batch_rocking_creep(
    batch_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    """
    Return one row per blade in the batch containing:
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
                Blade.batch_number == batch_number,
                Blade.deleted_at.is_(None),
            ).order_by(Blade.created_at)
        )
    ).scalars().all()

    if not blades:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_number}' not found",
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
            "rocking_value": meas.get("rocking_value"),
            "creep_value": meas.get("creep_value"),
        })
    return result


# ---------------------------------------------------------------------------
# POST /{batch_number}/receive
# ---------------------------------------------------------------------------


@router.post(
    "/{batch_number}/receive",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly marks a batch as received",
)
async def receive_batch(
    batch_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Assembly operator acknowledges receipt of the batch from OH."""
    return await _create_batch_event(
        batch_number=batch_number,
        event_type=BatchEventType.RECEIVED_BY_ASSEMBLY,
        remarks=body.get("remarks"),
        changes=None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /{batch_number}/accept
# ---------------------------------------------------------------------------


@router.post(
    "/{batch_number}/accept",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly accepts a batch",
)
async def accept_batch(
    batch_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Assembly operator formally accepts the batch for assembly work."""
    return await _create_batch_event(
        batch_number=batch_number,
        event_type=BatchEventType.ACCEPTED,
        remarks=body.get("remarks"),
        changes=None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /{batch_number}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/{batch_number}/reject",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly rejects a batch",
)
async def reject_batch(
    batch_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Assembly operator rejects the batch, notifying OH."""
    return await _create_batch_event(
        batch_number=batch_number,
        event_type=BatchEventType.REJECTED,
        remarks=body.get("remarks") or body.get("reason"),
        changes=None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )


# ---------------------------------------------------------------------------
# POST /{batch_number}/modify
# ---------------------------------------------------------------------------


@router.post(
    "/{batch_number}/modify",
    status_code=status.HTTP_201_CREATED,
    summary="Assembly applies blade-level modifications to a batch",
)
async def modify_batch(
    batch_number: str,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Assembly operator corrects blade details (weight, static moment, melt number) for
    one or more blades in the batch.  Each modification entry carries the original and
    updated field values so the diff is preserved in the BatchEvent and in OH notifications.
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
                    Blade.batch_number == batch_number,
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

    return await _create_batch_event(
        batch_number=batch_number,
        event_type=BatchEventType.MODIFIED,
        remarks=remarks,
        changes=changes_summary or None,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks,
    )
