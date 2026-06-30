"""
Slot allocation endpoints.

POST /slots/assign                — assign blade to a slot
POST /slots/reassign              — reassign blade to a new slot
PUT  /slots/{slot_id}/balancing   — record balancing result
GET  /slots/                      — list all active slot allocations
GET  /slots/blade/{blade_id}      — get current slot for a blade
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import BladeStatus
from app.schemas.base import PaginatedResponse
from app.schemas.slot_allocation import (
    BalancingUpdateRequest,
    SlotAllocationResponse,
    SlotAssignRequest,
    SlotReassignRequest,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_slot_or_404(slot_id: uuid.UUID, db: AsyncSession) -> Any:
    from app.models.slot_allocation import SlotAllocation

    result = await db.execute(
        select(SlotAllocation).where(SlotAllocation.id == slot_id)
    )
    slot = result.scalar_one_or_none()
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slot allocation {slot_id} not found",
        )
    return slot


async def _get_blade_or_404(blade_id: uuid.UUID, db: AsyncSession) -> Any:
    from app.models.blade import Blade

    result = await db.execute(
        select(Blade).where(Blade.id == blade_id, Blade.deleted_at.is_(None))
    )
    blade = result.scalar_one_or_none()
    if blade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blade {blade_id} not found",
        )
    return blade


# ---------------------------------------------------------------------------
# POST /assign
# ---------------------------------------------------------------------------


@router.post(
    "/assign",
    response_model=SlotAllocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a blade to an assembly slot",
)
async def assign_slot(
    body: SlotAssignRequest,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Assign a blade to a numbered assembly slot on the rotor jig.

    Prerequisites:
    - The blade must be in ``SENT_TO_ASSEMBLY`` or ``RETURNED_TO_OH`` status.
    - The target slot number must not already be occupied by an active allocation.

    Side effect: blade status transitions to ``SLOT_ASSIGNED``.

    Raises:
        HTTP 404 — blade not found.
        HTTP 409 — blade has an existing active slot / slot already occupied /
                   blade not in a valid status for slot assignment.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.models.workflow import WorkflowLog

    blade = await _get_blade_or_404(body.blade_id, db)

    valid_from = {BladeStatus.SENT_TO_ASSEMBLY, BladeStatus.RETURNED_TO_OH}
    if blade.status not in valid_from:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blade must be in SENT_TO_ASSEMBLY or RETURNED_TO_OH status. Current: '{blade.status}'",
        )

    # Check blade doesn't already have an active slot
    existing = (
        await db.execute(
            select(SlotAllocation).where(
                SlotAllocation.blade_id == body.blade_id,
                SlotAllocation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blade already has active slot assignment '{existing.slot_number}'",
        )

    # Check target slot is free
    slot_occupied = (
        await db.execute(
            select(SlotAllocation).where(
                SlotAllocation.slot_number == body.slot_number,
                SlotAllocation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if slot_occupied:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slot '{body.slot_number}' is already occupied",
        )

    from datetime import datetime, timezone

    allocation = SlotAllocation(
        blade_id=body.blade_id,
        slot_number=body.slot_number,
        position=body.position,
        group_id=body.group_id,
        allocated_by_id=current_user.id,
        allocated_at=datetime.now(timezone.utc),
        is_active=True,
        is_balanced=False,
        balancing_remarks=body.remarks,
    )
    db.add(allocation)

    # Advance blade status
    prev_status = blade.status
    blade.status = BladeStatus.SLOT_ASSIGNED
    log = WorkflowLog(
        blade_id=blade.id,
        from_status=prev_status,
        to_status=BladeStatus.SLOT_ASSIGNED,
        action_by_id=current_user.id,
        remarks=f"Assigned to slot {body.slot_number}",
    )
    db.add(log)

    await db.commit()
    await db.refresh(allocation)

    logger.info(
        "slot_assigned",
        blade_id=str(body.blade_id),
        slot=body.slot_number,
        allocation_id=str(allocation.id),
    )
    return allocation


# ---------------------------------------------------------------------------
# POST /reassign
# ---------------------------------------------------------------------------


@router.post(
    "/reassign",
    response_model=SlotAllocationResponse,
    status_code=status.HTTP_200_OK,
    summary="Reassign a blade to a different slot",
)
async def reassign_slot(
    body: SlotReassignRequest,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Move a blade from its current active slot to a new slot.

    The previous allocation row is deactivated (``is_active=False``) and
    a new row is created with ``previous_slot_number`` set for audit.

    A mandatory ``reason`` is required for all reassignments.

    Raises:
        HTTP 404 — blade not found, or blade has no active slot.
        HTTP 409 — new slot is already occupied.
    """
    from app.models.slot_allocation import SlotAllocation

    await _get_blade_or_404(body.blade_id, db)

    # Find current active allocation
    current_alloc = (
        await db.execute(
            select(SlotAllocation).where(
                SlotAllocation.blade_id == body.blade_id,
                SlotAllocation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if current_alloc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blade has no active slot allocation to reassign",
        )

    # Check new slot is free
    target_occupied = (
        await db.execute(
            select(SlotAllocation).where(
                SlotAllocation.slot_number == body.new_slot_number,
                SlotAllocation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if target_occupied:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Target slot '{body.new_slot_number}' is already occupied",
        )

    from datetime import datetime, timezone

    old_slot_number = current_alloc.slot_number

    # Deactivate old
    current_alloc.is_active = False

    # Create new
    new_alloc = SlotAllocation(
        blade_id=body.blade_id,
        slot_number=body.new_slot_number,
        position=body.new_position,
        group_id=current_alloc.group_id,
        allocated_by_id=current_user.id,
        allocated_at=datetime.now(timezone.utc),
        is_active=True,
        is_balanced=False,
        previous_slot_number=old_slot_number,
        balancing_remarks=body.reason,
    )
    db.add(new_alloc)

    await db.commit()
    await db.refresh(new_alloc)

    logger.info(
        "slot_reassigned",
        blade_id=str(body.blade_id),
        old_slot=old_slot_number,
        new_slot=body.new_slot_number,
    )
    return new_alloc


# ---------------------------------------------------------------------------
# PUT /{slot_id}/balancing
# ---------------------------------------------------------------------------


@router.put(
    "/{slot_id}/balancing",
    response_model=SlotAllocationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update balancing status and remarks for a slot allocation",
)
async def update_balancing(
    slot_id: uuid.UUID,
    body: BalancingUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[Any, Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Record the balancing outcome for a slot allocation.

    When ``is_balanced`` is True the associated blade transitions to
    ``BALANCING_COMPLETED``; when False it transitions to
    ``BALANCING_IN_PROGRESS``.

    Raises:
        HTTP 404 — slot allocation not found.
    """
    from app.models.workflow import WorkflowLog

    allocation = await _get_slot_or_404(slot_id, db)

    allocation.is_balanced = body.is_balanced
    allocation.unbalance_value = body.unbalance_value
    allocation.balancing_remarks = body.balancing_remarks

    # Advance blade status
    blade = await _get_blade_or_404(allocation.blade_id, db)
    prev_status = blade.status
    new_status = (
        BladeStatus.BALANCING_COMPLETED if body.is_balanced else BladeStatus.BALANCING_IN_PROGRESS
    )

    if blade.status in {
        BladeStatus.SLOT_ASSIGNED,
        BladeStatus.BALANCING_IN_PROGRESS,
        BladeStatus.BALANCING_COMPLETED,
    }:
        blade.status = new_status
        log = WorkflowLog(
            blade_id=blade.id,
            from_status=prev_status,
            to_status=new_status,
            action_by_id=current_user.id,
            remarks=body.balancing_remarks,
        )
        db.add(log)

    await db.commit()
    await db.refresh(allocation)

    # When this blade is balanced, check if ALL blades in the batch are done.
    if body.is_balanced and blade.batch_number:
        _batch_num = blade.batch_number
        _blade_serial = blade.serial_number
        async def _notify_batch_balanced(_batch: str, _serial: str) -> None:
            from app.notifications.service import NotificationService
            from app.models.notification import NotificationType
            from app.models.blade import Blade as _Blade
            from app.models.enums import BladeStatus as _BS
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import select as _sel, func as _func
            try:
                async with AsyncSessionLocal() as _db:
                    unbalanced = (await _db.execute(
                        _sel(_func.count(_Blade.id)).where(
                            _Blade.batch_number == _batch,
                            _Blade.deleted_at.is_(None),
                            _Blade.status.notin_([
                                _BS.BALANCING_COMPLETED,
                                _BS.RETURNED_TO_OH,
                                _BS.FINAL_VERIFICATION,
                                _BS.COMPLETED,
                                _BS.REJECTED,
                            ]),
                        )
                    )).scalar_one()
                    if unbalanced == 0:
                        svc = NotificationService(_db)
                        await svc.notify_roles(
                            roles=["OH_OPERATOR", "ASSEMBLY_OPERATOR", "SUPER_ADMIN"],
                            title=f"Batch {_batch} — Balancing complete",
                            body=f"All blades in batch {_batch} have been balanced and are ready to return to OH for final verification.",
                            notification_type=NotificationType.BALANCING_DONE,
                            metadata={"batch_number": _batch},
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify_batch_balanced_failed", error=str(exc))

        background_tasks.add_task(_notify_batch_balanced, _batch_num, _blade_serial)

    logger.info(
        "balancing_updated",
        slot_id=str(slot_id),
        is_balanced=body.is_balanced,
        blade_id=str(allocation.blade_id),
    )
    return allocation


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=PaginatedResponse[SlotAllocationResponse],
    status_code=status.HTTP_200_OK,
    summary="List all active slot allocations",
)
async def list_slots(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    is_balanced: bool | None = Query(default=None),
    batch_number: str | None = Query(default=None),
) -> Any:
    """
    Return all currently active slot allocations, optionally filtered by
    balancing status and/or batch number.  Results are ordered by slot number.
    """
    from app.models.blade import Blade as _Blade
    from app.models.slot_allocation import SlotAllocation

    if batch_number:
        stmt_base = (
            select(SlotAllocation)
            .join(_Blade, _Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.is_active.is_(True),
                _Blade.batch_number == batch_number,
                _Blade.deleted_at.is_(None),
            )
        )
        count_stmt = (
            select(func.count())
            .select_from(SlotAllocation)
            .join(_Blade, _Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.is_active.is_(True),
                _Blade.batch_number == batch_number,
                _Blade.deleted_at.is_(None),
            )
        )
    else:
        stmt_base = select(SlotAllocation).where(SlotAllocation.is_active.is_(True))
        count_stmt = select(func.count()).select_from(SlotAllocation).where(SlotAllocation.is_active.is_(True))

    if is_balanced is not None:
        stmt_base = stmt_base.where(SlotAllocation.is_balanced.is_(is_balanced))
        count_stmt = count_stmt.where(SlotAllocation.is_balanced.is_(is_balanced))

    total: int = (await db.execute(count_stmt)).scalar_one()

    items = list(
        (
            await db.execute(
                stmt_base
                .order_by(SlotAllocation.allocated_at.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    page = skip // limit + 1 if limit > 0 else 1
    return PaginatedResponse(items=items, total=total, page=page, page_size=limit)


# ---------------------------------------------------------------------------
# GET /blade/{blade_id}
# ---------------------------------------------------------------------------


@router.get(
    "/blade/{blade_id}",
    response_model=SlotAllocationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the current active slot allocation for a blade",
)
async def get_blade_slot(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Return the currently active slot allocation for the specified blade.

    Raises:
        HTTP 404 — blade not found or has no active slot allocation.
    """
    from app.models.slot_allocation import SlotAllocation

    await _get_blade_or_404(blade_id, db)

    allocation = (
        await db.execute(
            select(SlotAllocation).where(
                SlotAllocation.blade_id == blade_id,
                SlotAllocation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if allocation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active slot allocation found for blade {blade_id}",
        )

    return allocation
