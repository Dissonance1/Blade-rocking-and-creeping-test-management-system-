"""
Assembly station endpoints (720 Hanger).

POST   /assembly/batches/{batch_number}/receive         — mark batch as received
GET    /assembly/batches/{batch_number}/receipt         — get receipt details
GET    /assembly/batches/{batch_number}/progress        — verification progress
GET    /assembly/batches/{batch_number}/blades          — list blades in batch
POST   /assembly/blades/{blade_id}/verify               — scan + validate blade
POST   /assembly/blades/{blade_id}/accept               — accept blade (+ optional overrides)
POST   /assembly/blades/{blade_id}/reject               — reject blade
POST   /assembly/batches/{batch_number}/start-setmaking — trigger set-making
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.blade import Blade
from app.models.enums import BladeStatus, RoleName
from app.models.user import User
from app.schemas.assembly import (
    AssemblyBladeRecordResponse,
    BatchProgressResponse,
    BatchReceiptResponse,
    BatchReceiveRequest,
    BladeAcceptRequest,
    BladeRejectRequest,
    BladeVerifyRequest,
    BladeVerifyResponse,
    SetMakingResponse,
    StartSetMakingRequest,
)
from app.schemas.base import StatusResponse
from app.services.assembly_service import AssemblyService

router = APIRouter()
log = structlog.get_logger(__name__)

_ASSEMBLY_ROLES = [RoleName.ASSEMBLY_OPERATOR, RoleName.SUPER_ADMIN]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_blade_or_404(blade_id: uuid.UUID, db: AsyncSession) -> Blade:
    res = await db.execute(
        select(Blade).where(Blade.id == blade_id, Blade.deleted_at.is_(None))
    )
    blade = res.scalar_one_or_none()
    if blade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Blade not found.")
    return blade


# ---------------------------------------------------------------------------
# Batch receipt
# ---------------------------------------------------------------------------

@router.post(
    "/batches/{batch_number}/receive",
    response_model=BatchReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mark a batch as received at Assembly",
)
async def receive_batch(
    batch_number: str,
    body: BatchReceiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(*_ASSEMBLY_ROLES)),
) -> BatchReceiptResponse:
    svc = AssemblyService(db)
    try:
        result = await svc.receive_batch(
            batch_number=batch_number,
            operator=current_user,
            station_id=body.station_id,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return result


@router.get(
    "/batches/{batch_number}/receipt",
    response_model=BatchReceiptResponse,
    summary="Get batch receipt details",
)
async def get_receipt(
    batch_number: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*_ASSEMBLY_ROLES, RoleName.QA_VIEWER)),
) -> BatchReceiptResponse:
    from app.repositories.assembly_repository import AssemblyRepository
    repo = AssemblyRepository(db)
    receipt = await repo.get_receipt_by_batch(batch_number)
    if receipt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_number}' has not been received at Assembly yet.",
        )
    return BatchReceiptResponse(
        id=receipt.id,
        batch_number=receipt.batch_number,
        received_at=receipt.received_at,
        received_by_id=receipt.received_by_id,
        station_id=receipt.station_id,
        total_expected=receipt.total_expected,
        notes=receipt.notes,
        created_at=receipt.created_at,
    )


# ---------------------------------------------------------------------------
# Batch progress
# ---------------------------------------------------------------------------

@router.get(
    "/batches/{batch_number}/progress",
    response_model=BatchProgressResponse,
    summary="Batch verification progress at Assembly",
)
async def batch_progress(
    batch_number: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*_ASSEMBLY_ROLES, RoleName.QA_VIEWER)),
) -> BatchProgressResponse:
    svc = AssemblyService(db)
    return await svc.get_batch_progress(batch_number)


# ---------------------------------------------------------------------------
# List blades in batch
# ---------------------------------------------------------------------------

@router.get(
    "/batches/{batch_number}/blades",
    summary="List blades in a batch with their Assembly verification status",
)
async def list_batch_blades(
    batch_number: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*_ASSEMBLY_ROLES, RoleName.QA_VIEWER)),
) -> dict:
    from app.repositories.assembly_repository import AssemblyRepository
    repo = AssemblyRepository(db)
    blades = await repo.get_batch_blades(batch_number)
    if not blades:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No blades found in batch '{batch_number}'.",
        )

    receipt = await repo.get_receipt_by_batch(batch_number)
    blade_records: dict[uuid.UUID, dict] = {}
    if receipt:
        records = await repo.list_blade_records(receipt.id)
        for r in records:
            blade_records[r.blade_id] = {
                "verification_status": r.status.value,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
                "weight_delta": float(r.weight_delta) if r.weight_delta is not None else None,
            }

    return {
        "batch_number": batch_number,
        "total": len(blades),
        "blades": [
            {
                "id": str(b.id),
                "serial_number": b.serial_number,
                "blade_type": b.blade_type.value,
                "status": b.status.value,
                "assembly_verification": blade_records.get(b.id),
            }
            for b in blades
        ],
    }


# ---------------------------------------------------------------------------
# Per-blade verify / accept / reject
# ---------------------------------------------------------------------------

@router.post(
    "/blades/{blade_id}/verify",
    response_model=BladeVerifyResponse,
    summary="Scan blade and validate measurements against OH records",
)
async def verify_blade(
    blade_id: uuid.UUID,
    batch_number: str,
    body: BladeVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(*_ASSEMBLY_ROLES)),
) -> BladeVerifyResponse:
    blade = await _get_blade_or_404(blade_id, db)
    svc = AssemblyService(db)
    try:
        result = await svc.verify_blade(blade, batch_number, body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return result


@router.post(
    "/blades/{blade_id}/accept",
    response_model=AssemblyBladeRecordResponse,
    summary="Accept blade at Assembly (optionally override readings)",
)
async def accept_blade(
    blade_id: uuid.UUID,
    batch_number: str,
    body: BladeAcceptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(*_ASSEMBLY_ROLES)),
) -> AssemblyBladeRecordResponse:
    blade = await _get_blade_or_404(blade_id, db)
    svc = AssemblyService(db)
    try:
        result = await svc.accept_blade(
            blade=blade,
            batch_number=batch_number,
            payload=body,
            operator=current_user,
            station_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return result


@router.post(
    "/blades/{blade_id}/reject",
    response_model=AssemblyBladeRecordResponse,
    summary="Reject blade at Assembly",
)
async def reject_blade(
    blade_id: uuid.UUID,
    batch_number: str,
    body: BladeRejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(*_ASSEMBLY_ROLES)),
) -> AssemblyBladeRecordResponse:
    blade = await _get_blade_or_404(blade_id, db)
    svc = AssemblyService(db)
    try:
        result = await svc.reject_blade(
            blade=blade,
            batch_number=batch_number,
            payload=body,
            operator=current_user,
            station_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Set-making trigger
# ---------------------------------------------------------------------------

@router.post(
    "/batches/{batch_number}/start-setmaking",
    response_model=SetMakingResponse,
    summary="Trigger set-making after all blades in batch are verified",
)
async def start_setmaking(
    batch_number: str,
    body: StartSetMakingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(*_ASSEMBLY_ROLES)),
) -> SetMakingResponse:
    svc = AssemblyService(db)
    progress = await svc.get_batch_progress(batch_number)

    if not progress.set_making_ready:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Batch is not ready for set-making. "
                f"{progress.assembly_verified}/{progress.total_expected} blades verified, "
                f"{progress.pending} still pending verification."
            ),
        )

    # Set-making is handled by the existing slots/balancing workflow.
    # This endpoint validates readiness and returns confirmation.
    # The ASSEMBLY_OPERATOR then uses POST /slots/ and the balancing endpoints
    # to run the HAL algorithm and assign slots.
    log.info(
        "assembly.setmaking_triggered",
        batch_number=batch_number,
        verified=progress.assembly_verified,
        operator_id=str(current_user.id),
    )

    return SetMakingResponse(
        batch_number=batch_number,
        status="INITIATED",
        total_blades=progress.assembly_verified,
        message=(
            f"All {progress.assembly_verified} blades verified. "
            "Proceed to slot assignment and balancing operations."
        ),
    )
