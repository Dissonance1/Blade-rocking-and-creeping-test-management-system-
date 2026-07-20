"""
LPTR two-stage slot allocation & balancing endpoints.

POST /lptr/{work_order_number}/empty-rotor         — record the empty-rotor reading
GET  /lptr/{work_order_number}/empty-rotor          — read it back
POST /lptr/{work_order_number}/balancing-check      — record a stage's measured-unbalance check
GET  /lptr/{work_order_number}/balancing-checks     — list all checks for a work order
POST /lptr/{work_order_number}/manual-correction    — record a manual correction / replacement request
GET  /lptr/{work_order_number}/manual-corrections   — list all corrections for a work order

These are all traceability records for the LPTR workflow (empty-rotor
reading -> stage-1 allocation -> stage-1 balancing check -> optional manual
corrections -> stage-2 allocation -> stage-2 balancing check). The
allocation math itself is computed client-side (frontend/src/utils/
lptrBalancing.ts) and persisted via the existing bulk
``/work-orders/{wo}/assign-slot`` endpoint — this router only covers the
three record types that don't fit the generic SlotAllocation model.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import _user_role_names, get_current_user
from app.db.session import get_db
from app.models.enums import BladeType
from app.models.lptr_balancing_check import LPTR_UNBALANCE_LIMIT_G
from app.schemas.lptr_balancing import (
    BalancingCheckRequest,
    BalancingCheckResponse,
    EmptyRotorReadingRequest,
    EmptyRotorReadingResponse,
    ManualCorrectionRequest,
    ManualCorrectionResponse,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_lptr_work_order_or_404(work_order_number: str, db: AsyncSession) -> Any:
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
    if work_order.blade_type != BladeType.LPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Work Order '{work_order_number}' is not an LPTR work order",
        )
    return work_order


def _require_assembly_role(current_user: Any) -> None:
    user_roles = _user_role_names(current_user)
    if "SUPER_ADMIN" in user_roles or "ASSEMBLY_OPERATOR" in user_roles:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="ASSEMBLY_OPERATOR or SUPER_ADMIN role required for LPTR balancing records",
    )


# ---------------------------------------------------------------------------
# Empty rotor reading
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/empty-rotor",
    response_model=EmptyRotorReadingResponse,
    status_code=status.HTTP_200_OK,
    summary="Record (or update) the empty-rotor unbalance reading for a work order",
)
async def save_empty_rotor_reading(
    work_order_number: str,
    body: EmptyRotorReadingRequest,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.models.lptr_empty_rotor_reading import LptrEmptyRotorReading

    await _get_lptr_work_order_or_404(work_order_number, db)
    _require_assembly_role(current_user)

    existing = (
        await db.execute(
            select(LptrEmptyRotorReading).where(
                LptrEmptyRotorReading.work_order_number == work_order_number
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.unbalance_slot = body.unbalance_slot
        existing.unbalance_value = body.unbalance_value
        existing.recorded_by_id = current_user.id
        reading = existing
    else:
        reading = LptrEmptyRotorReading(
            work_order_number=work_order_number,
            unbalance_slot=body.unbalance_slot,
            unbalance_value=body.unbalance_value,
            recorded_by_id=current_user.id,
        )
        db.add(reading)

    await db.commit()
    await db.refresh(reading)

    logger.info(
        "lptr_empty_rotor_reading_saved",
        work_order=work_order_number,
        unbalance_slot=body.unbalance_slot,
    )
    return reading


@router.get(
    "/{work_order_number}/empty-rotor",
    response_model=EmptyRotorReadingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the empty-rotor unbalance reading for a work order",
)
async def get_empty_rotor_reading(
    work_order_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.models.lptr_empty_rotor_reading import LptrEmptyRotorReading

    await _get_lptr_work_order_or_404(work_order_number, db)

    reading = (
        await db.execute(
            select(LptrEmptyRotorReading).where(
                LptrEmptyRotorReading.work_order_number == work_order_number
            )
        )
    ).scalar_one_or_none()
    if reading is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No empty-rotor reading recorded for Work Order '{work_order_number}'",
        )
    return reading


# ---------------------------------------------------------------------------
# Balancing check
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/balancing-check",
    response_model=BalancingCheckResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a stage's measured-unbalance balancing check",
)
async def create_balancing_check(
    work_order_number: str,
    body: BalancingCheckRequest,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.models.lptr_balancing_check import LptrBalancingCheck

    await _get_lptr_work_order_or_404(work_order_number, db)
    _require_assembly_role(current_user)

    check = LptrBalancingCheck(
        work_order_number=work_order_number,
        stage=body.stage,
        measured_unbalance=body.measured_unbalance,
        is_pass=body.measured_unbalance <= LPTR_UNBALANCE_LIMIT_G,
        remarks=body.remarks,
        recorded_by_id=current_user.id,
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)

    logger.info(
        "lptr_balancing_check_recorded",
        work_order=work_order_number,
        stage=body.stage,
        measured_unbalance=str(body.measured_unbalance),
        is_pass=check.is_pass,
    )
    return check


@router.get(
    "/{work_order_number}/balancing-checks",
    response_model=list[BalancingCheckResponse],
    status_code=status.HTTP_200_OK,
    summary="List balancing checks recorded for a work order",
)
async def list_balancing_checks(
    work_order_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.models.lptr_balancing_check import LptrBalancingCheck

    await _get_lptr_work_order_or_404(work_order_number, db)

    checks = (
        await db.execute(
            select(LptrBalancingCheck)
            .where(LptrBalancingCheck.work_order_number == work_order_number)
            .order_by(LptrBalancingCheck.recorded_at.desc())
        )
    ).scalars().all()
    return list(checks)


# ---------------------------------------------------------------------------
# Manual correction
# ---------------------------------------------------------------------------


@router.post(
    "/{work_order_number}/manual-correction",
    response_model=ManualCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a manual correction or manufacturer replacement request",
)
async def create_manual_correction(
    work_order_number: str,
    body: ManualCorrectionRequest,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.models.blade import Blade
    from app.models.lptr_manual_correction import LptrManualCorrection

    await _get_lptr_work_order_or_404(work_order_number, db)
    _require_assembly_role(current_user)

    if body.blade_id is not None:
        blade = (
            await db.execute(
                select(Blade).where(Blade.id == body.blade_id, Blade.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if blade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blade {body.blade_id} not found",
            )

    correction = LptrManualCorrection(
        work_order_number=work_order_number,
        stage=body.stage,
        correction_type=body.correction_type,
        description=body.description,
        blade_id=body.blade_id,
        slot_number=body.slot_number,
        recorded_by_id=current_user.id,
    )
    db.add(correction)
    await db.commit()
    await db.refresh(correction)

    logger.info(
        "lptr_manual_correction_recorded",
        work_order=work_order_number,
        stage=body.stage,
        correction_type=body.correction_type,
    )
    return correction


@router.get(
    "/{work_order_number}/manual-corrections",
    response_model=list[ManualCorrectionResponse],
    status_code=status.HTTP_200_OK,
    summary="List manual corrections recorded for a work order",
)
async def list_manual_corrections(
    work_order_number: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.models.lptr_manual_correction import LptrManualCorrection

    await _get_lptr_work_order_or_404(work_order_number, db)

    corrections = (
        await db.execute(
            select(LptrManualCorrection)
            .where(LptrManualCorrection.work_order_number == work_order_number)
            .order_by(LptrManualCorrection.recorded_at.desc())
        )
    ).scalars().all()
    return list(corrections)
