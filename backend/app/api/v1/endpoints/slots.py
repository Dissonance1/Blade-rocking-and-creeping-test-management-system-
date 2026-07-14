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

from app.core.dependencies import _user_role_names, get_current_user
from app.db.session import get_db
from app.models.enums import BladeStatus, BladeType
from app.schemas.base import PaginatedResponse
from app.schemas.slot_allocation import (
    BalancingUpdateRequest,
    SlotAllocationResponse,
    SlotAssignRequest,
    SlotReassignRequest,
    SlotSwapRequest,
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


def _require_role_for_blade_type(current_user: Any, blade_type: BladeType) -> None:
    """Slot allocation/balancing is ASSEMBLY_OPERATOR's job for LPTR blades
    (sent to Assembly) and OH_OPERATOR's job for HPTR blades (never leave OH).
    SUPER_ADMIN may act on either."""
    user_roles = _user_role_names(current_user)
    if "SUPER_ADMIN" in user_roles:
        return
    required = "ASSEMBLY_OPERATOR" if blade_type == BladeType.LPTR else "OH_OPERATOR"
    if required not in user_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{required} or SUPER_ADMIN role required for {blade_type.value} blades",
        )


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
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Assign a blade to a numbered assembly slot on the rotor jig.

    Prerequisites:
    - LPTR blades must be in ``SENT_TO_ASSEMBLY`` or ``RETURNED_TO_OH`` status
      (assigned by ASSEMBLY_OPERATOR/SUPER_ADMIN).
    - HPTR blades must be in ``MEASUREMENTS_RECORDED`` status — they never
      leave OH, so slot assignment happens directly from there (assigned by
      OH_OPERATOR/SUPER_ADMIN).
    - The target slot number must not already be occupied by an active allocation.

    Side effect: blade status transitions to ``SLOT_ASSIGNED``.

    Raises:
        HTTP 403 — caller's role doesn't match the blade's type.
        HTTP 404 — blade not found.
        HTTP 409 — blade has an existing active slot / slot already occupied /
                   blade not in a valid status for slot assignment.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.workflows.state_machine import WorkflowEngine

    blade = await _get_blade_or_404(body.blade_id, db)
    _require_role_for_blade_type(current_user, blade.blade_type)

    valid_from = (
        {BladeStatus.MEASUREMENTS_RECORDED}
        if blade.blade_type == BladeType.HPTR
        else {BladeStatus.SENT_TO_ASSEMBLY, BladeStatus.RETURNED_TO_OH}
    )
    if blade.status not in valid_from:
        valid_labels = ", ".join(sorted(s.value for s in valid_from))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blade must be in one of [{valid_labels}] status. Current: '{blade.status}'",
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

    # Check target slot is free — scoped to blade_type, since LPTR and HPTR
    # are physically different rotors (different slot counts) with
    # independent slot numbering, not a shared numbering space.
    slot_occupied = (
        await db.execute(
            select(SlotAllocation)
            .join(Blade, Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.slot_number == body.slot_number,
                SlotAllocation.is_active.is_(True),
                Blade.blade_type == blade.blade_type,
            )
        )
    ).scalar_one_or_none()
    if slot_occupied:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slot '{body.slot_number}' is already occupied on the {blade.blade_type.value} rotor",
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
    await WorkflowEngine(db).transition(
        blade=blade,
        to_status=BladeStatus.SLOT_ASSIGNED,
        user=current_user,
        station_id=None,
        remarks=f"Assigned to slot {body.slot_number}",
    )

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
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Move a blade from its current active slot to a new slot.

    The previous allocation row is deactivated (``is_active=False``) and
    a new row is created with ``previous_slot_number`` set for audit.

    A mandatory ``reason`` is required for all reassignments.

    Raises:
        HTTP 403 — caller's role doesn't match the blade's type.
        HTTP 404 — blade not found, or blade has no active slot.
        HTTP 409 — new slot is already occupied.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation

    blade = await _get_blade_or_404(body.blade_id, db)
    _require_role_for_blade_type(current_user, blade.blade_type)

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

    # Check new slot is free — scoped to blade_type (see assign_slot for why).
    target_occupied = (
        await db.execute(
            select(SlotAllocation)
            .join(Blade, Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.slot_number == body.new_slot_number,
                SlotAllocation.is_active.is_(True),
                Blade.blade_type == blade.blade_type,
            )
        )
    ).scalar_one_or_none()
    if target_occupied:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Target slot '{body.new_slot_number}' is already occupied on the {blade.blade_type.value} rotor",
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
# POST /swap
# ---------------------------------------------------------------------------


@router.post(
    "/swap",
    response_model=list[SlotAllocationResponse],
    status_code=status.HTTP_200_OK,
    summary="Swap the blades occupying two already-saved slots",
)
async def swap_slots(
    body: SlotSwapRequest,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Exchange which blade occupies each of two slots.

    Unlike ``/reassign`` (which moves one blade into an empty slot), a full
    rotor has no empty slots — correcting a blade that fails physical
    balancing testing means swapping it with another slot's blade. Both
    allocations are reset to unbalanced since they're now in new positions.

    ``blade_type`` is not accepted from the caller — since one work order
    now always maps to exactly one blade type, it is derived by looking up
    the ``WorkOrder`` for ``body.work_order_number``.

    Raises:
        HTTP 403 — caller's role doesn't match the blade type.
        HTTP 404 — work order not found, or either slot has no active allocation.
        HTTP 422 — the two slot numbers are identical.
    """
    from datetime import datetime, timezone

    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.models.work_order import WorkOrder

    work_order = (
        await db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == body.work_order_number)
        )
    ).scalar_one_or_none()
    if work_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work order '{body.work_order_number}' not found",
        )
    blade_type_val = work_order.blade_type

    _require_role_for_blade_type(current_user, blade_type_val)

    if body.slot_number_a == body.slot_number_b:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Slot A and Slot B must be different",
        )

    async def _active_allocation(slot_number: str) -> Any:
        return (
            await db.execute(
                select(SlotAllocation)
                .join(Blade, Blade.id == SlotAllocation.blade_id)
                .where(
                    SlotAllocation.slot_number == slot_number,
                    SlotAllocation.is_active.is_(True),
                    Blade.blade_type == blade_type_val,
                    Blade.work_order_number == body.work_order_number,
                )
            )
        ).scalar_one_or_none()

    alloc_a = await _active_allocation(body.slot_number_a)
    alloc_b = await _active_allocation(body.slot_number_b)
    if alloc_a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active {blade_type_val.value} allocation at slot '{body.slot_number_a}' in work order '{body.work_order_number}'",
        )
    if alloc_b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active {blade_type_val.value} allocation at slot '{body.slot_number_b}' in work order '{body.work_order_number}'",
        )

    now = datetime.now(timezone.utc)
    alloc_a.is_active = False
    alloc_b.is_active = False

    new_a = SlotAllocation(
        blade_id=alloc_a.blade_id,
        slot_number=body.slot_number_b,
        position=alloc_a.position,
        group_id=alloc_a.group_id,
        allocated_by_id=current_user.id,
        allocated_at=now,
        is_active=True,
        is_balanced=False,
        previous_slot_number=body.slot_number_a,
        balancing_remarks=body.reason,
    )
    new_b = SlotAllocation(
        blade_id=alloc_b.blade_id,
        slot_number=body.slot_number_a,
        position=alloc_b.position,
        group_id=alloc_b.group_id,
        allocated_by_id=current_user.id,
        allocated_at=now,
        is_active=True,
        is_balanced=False,
        previous_slot_number=body.slot_number_b,
        balancing_remarks=body.reason,
    )
    db.add(new_a)
    db.add(new_b)

    await db.commit()
    await db.refresh(new_a)
    await db.refresh(new_b)

    logger.info(
        "slots_swapped",
        blade_type=blade_type_val.value,
        work_order=body.work_order_number,
        slot_a=body.slot_number_a,
        slot_b=body.slot_number_b,
    )
    return [new_a, new_b]


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
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Record the balancing outcome for a slot allocation.

    When ``is_balanced`` is True the associated blade transitions to
    ``BALANCING_COMPLETED``; when False it transitions to
    ``BALANCING_IN_PROGRESS``.

    Raises:
        HTTP 403 — caller's role doesn't match the blade's type.
        HTTP 404 — slot allocation not found.
    """
    from app.workflows.state_machine import WorkflowEngine

    allocation = await _get_slot_or_404(slot_id, db)
    blade = await _get_blade_or_404(allocation.blade_id, db)
    _require_role_for_blade_type(current_user, blade.blade_type)

    allocation.is_balanced = body.is_balanced
    allocation.unbalance_value = body.unbalance_value
    allocation.balancing_remarks = body.balancing_remarks

    # Advance blade status
    new_status = (
        BladeStatus.BALANCING_COMPLETED if body.is_balanced else BladeStatus.BALANCING_IN_PROGRESS
    )

    if (
        blade.status
        in {
            BladeStatus.SLOT_ASSIGNED,
            BladeStatus.BALANCING_IN_PROGRESS,
            BladeStatus.BALANCING_COMPLETED,
        }
        and blade.status != new_status
    ):
        await WorkflowEngine(db).transition(
            blade=blade,
            to_status=new_status,
            user=current_user,
            station_id=None,
            remarks=body.balancing_remarks,
        )

    await db.commit()
    await db.refresh(allocation)

    # When this blade is balanced, check if ALL blades in the work order are done.
    if body.is_balanced and blade.work_order_number:
        _wo_num = blade.work_order_number
        _blade_serial = blade.serial_number
        async def _notify_work_order_balanced(_work_order: str, _serial: str) -> None:
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
                            _Blade.work_order_number == _work_order,
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
                            title=f"Work Order {_work_order} — Balancing complete",
                            body=f"All blades in work order {_work_order} have been balanced and are ready to return to OH for final verification.",
                            notification_type=NotificationType.BALANCING_DONE,
                            metadata={"work_order_number": _work_order},
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify_work_order_balanced_failed", error=str(exc))

        background_tasks.add_task(_notify_work_order_balanced, _wo_num, _blade_serial)

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
    work_order_number: str | None = Query(default=None),
) -> Any:
    """
    Return all currently active slot allocations, optionally filtered by
    balancing status and/or work order number.  Results are ordered by slot number.
    """
    from app.models.blade import Blade as _Blade
    from app.models.slot_allocation import SlotAllocation

    if work_order_number:
        stmt_base = (
            select(SlotAllocation)
            .join(_Blade, _Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.is_active.is_(True),
                _Blade.work_order_number == work_order_number,
                _Blade.deleted_at.is_(None),
            )
        )
        count_stmt = (
            select(func.count())
            .select_from(SlotAllocation)
            .join(_Blade, _Blade.id == SlotAllocation.blade_id)
            .where(
                SlotAllocation.is_active.is_(True),
                _Blade.work_order_number == work_order_number,
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
