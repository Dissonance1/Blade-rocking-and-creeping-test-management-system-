"""
Measurement endpoints.

POST /blades/{blade_id}/measurements          — add measurement
GET  /blades/{blade_id}/measurements          — list measurements for a blade
GET  /measurements/{measurement_id}           — get specific measurement
PUT  /measurements/{measurement_id}           — update measurement (before approval)
POST /measurements/{measurement_id}/approve   — approve measurement
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import BladeStatus
from app.schemas.base import PaginatedResponse, StatusResponse
from app.schemas.measurement import MeasurementCreate, MeasurementResponse, MeasurementUpdate, RockingCreepUpdate

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_measurement_or_404(measurement_id: uuid.UUID, db: AsyncSession) -> Any:
    """Fetch a Measurement by primary key or raise HTTP 404."""
    from app.models.measurement import Measurement

    result = await db.execute(
        select(Measurement).where(Measurement.id == measurement_id)
    )
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurement {measurement_id} not found",
        )
    return m


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
# POST /blades/{blade_id}/measurements
# ---------------------------------------------------------------------------


@router.post(
    "/blades/{blade_id}/measurements",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new measurement for a blade",
)
async def add_measurement(
    blade_id: uuid.UUID,
    body: MeasurementCreate,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Record a new rocking/creep measurement session against a blade.

    The ``blade_id`` in the URL must match ``body.blade_id``.
    At least one measurement value must be supplied.

    Side effect: when the blade is in ``OH_INSPECTION`` or ``REOPENED``
    status, recording a measurement transitions it to
    ``MEASUREMENTS_RECORDED``.

    Raises:
        HTTP 400 — blade_id mismatch.
        HTTP 403 — insufficient role.
        HTTP 404 — blade not found.
        HTTP 409 — blade status does not permit new measurements
                   (e.g. COMPLETED, REJECTED).
    """
    from app.models.measurement import Measurement
    from app.models.workflow import WorkflowLog

    # blade_id is taken from the URL; body.blade_id is optional but must match if provided
    if body.blade_id is not None and body.blade_id != blade_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="blade_id in body does not match URL parameter",
        )

    blade = await _get_blade_or_404(blade_id, db)

    # Blades in terminal or assembly-only statuses cannot have new OH measurements.
    blocked = {BladeStatus.COMPLETED, BladeStatus.REJECTED}
    if blade.status in blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot record measurements for a blade with status '{blade.status}'",
        )

    measurement = Measurement(
        blade_id=blade_id,
        measurement_type=body.measurement_type,
        weight_grams=body.weight_grams,
        static_moment_gcm=body.static_moment_gcm,
        rocking_value=body.rocking_value,
        creep_value=body.creep_value,
        station_id=body.station_id or current_user.station_id,
        notes=body.notes,
        measured_by_id=current_user.id,
        is_approved=False,
    )
    db.add(measurement)

    # Auto-calculate static moment if not provided
    # Formula: SM = weight_grams × 1.57 × 20
    if body.weight_grams and not body.static_moment_gcm:
        auto_sm = float(body.weight_grams) * 1.57 * 20
        measurement.static_moment_gcm = Decimal(str(round(auto_sm, 2)))

    # Auto-advance blade status
    if blade.status in {BladeStatus.OH_INSPECTION, BladeStatus.REOPENED}:
        previous_status = blade.status
        blade.status = BladeStatus.MEASUREMENTS_RECORDED
        log = WorkflowLog(
            blade_id=blade_id,
            from_status=previous_status,
            to_status=BladeStatus.MEASUREMENTS_RECORDED,
            action_by_id=current_user.id,
            station_id=body.station_id or current_user.station_id,
            remarks="Measurements recorded",
        )
        db.add(log)

    await db.commit()
    await db.refresh(measurement)

    logger.info(
        "measurement_created",
        measurement_id=str(measurement.id),
        blade_id=str(blade_id),
        type=str(body.measurement_type),
    )
    return measurement


# ---------------------------------------------------------------------------
# GET /blades/{blade_id}/measurements
# ---------------------------------------------------------------------------


@router.get(
    "/blades/{blade_id}/measurements",
    response_model=PaginatedResponse[MeasurementResponse],
    status_code=status.HTTP_200_OK,
    summary="List all measurements for a blade",
)
async def list_blade_measurements(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """
    Return all measurement records associated with the specified blade,
    ordered by measurement time (newest first).

    Raises:
        HTTP 404 — blade not found.
    """
    from app.models.measurement import Measurement

    await _get_blade_or_404(blade_id, db)

    total: int = (
        await db.execute(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.blade_id == blade_id)
        )
    ).scalar_one()

    items = list(
        (
            await db.execute(
                select(Measurement)
                .where(Measurement.blade_id == blade_id)
                .order_by(Measurement.measured_at.desc())
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
# GET /measurements/{measurement_id}
# ---------------------------------------------------------------------------


@router.get(
    "/measurements/{measurement_id}",
    response_model=MeasurementResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a specific measurement record",
)
async def get_measurement(
    measurement_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Return the full record for a single measurement."""
    return await _get_measurement_or_404(measurement_id, db)


# ---------------------------------------------------------------------------
# PUT /measurements/{measurement_id}
# ---------------------------------------------------------------------------


@router.put(
    "/measurements/{measurement_id}",
    response_model=MeasurementResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a measurement (only before approval)",
)
async def update_measurement(
    measurement_id: uuid.UUID,
    body: MeasurementUpdate,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Update the values of an existing measurement.

    Updates are only permitted before the measurement has been approved
    (``is_approved == False``).  To approve a measurement, use the
    ``/measurements/{id}/approve`` endpoint instead.

    Raises:
        HTTP 404 — measurement not found.
        HTTP 409 — measurement is already approved.
    """
    measurement = await _get_measurement_or_404(measurement_id, db)

    if measurement.is_approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update an approved measurement",
        )

    update_data = body.model_dump(exclude_unset=True, exclude={"is_approved"})
    for field, value in update_data.items():
        setattr(measurement, field, value)

    await db.commit()
    await db.refresh(measurement)

    logger.info("measurement_updated", measurement_id=str(measurement_id))
    return measurement


# ---------------------------------------------------------------------------
# PATCH /blades/{blade_id}/rocking-creep
# ---------------------------------------------------------------------------


@router.patch(
    "/blades/{blade_id}/rocking-creep",
    response_model=MeasurementResponse,
    status_code=status.HTTP_200_OK,
    summary="Set rocking and/or creep values for a blade (post slot-allocation entry)",
)
async def set_rocking_creep(
    blade_id: uuid.UUID,
    body: RockingCreepUpdate,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Save rocking_value and/or creep_value for a blade.

    Finds the blade's most recent measurement record and updates the
    rocking/creep fields on it.  If the blade has no measurement yet,
    a new INITIAL record is created with only those values.

    Only one physical gauge is shared between the Rocking and Creep
    measurement fixtures, so each value is saved independently as soon as
    it arrives — the request may carry just one of the two fields, and the
    other can follow later (even from a different session).

    This endpoint is intended for the dedicated Rocking & Creep Entry
    workflow after Assembly has allocated slot numbers.
    """
    from app.models.measurement import Measurement
    from app.models.enums import MeasurementType

    blade = await _get_blade_or_404(blade_id, db)

    # Enforce blade-type rules
    is_lptr = str(getattr(blade.blade_type, "value", blade.blade_type)).upper() == "LPTR"
    if body.rocking_value is None and body.creep_value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of rocking_value or creep_value must be provided.",
        )
    if not is_lptr and body.creep_value is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="HPTR blades do not have a creep value.",
        )

    measurement = (
        await db.execute(
            select(Measurement)
            .where(Measurement.blade_id == blade_id)
            .order_by(Measurement.measured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if measurement is None:
        measurement = Measurement(
            blade_id=blade_id,
            measurement_type=MeasurementType.INITIAL,
            rocking_value=body.rocking_value,
            creep_value=body.creep_value,
            measured_by_id=current_user.id,
            station_id=current_user.station_id,
            is_approved=False,
        )
        db.add(measurement)
    else:
        if body.rocking_value is not None:
            measurement.rocking_value = body.rocking_value
        if body.creep_value is not None:
            measurement.creep_value = body.creep_value

    await db.commit()
    await db.refresh(measurement)

    logger.info(
        "rocking_creep_updated",
        blade_id=str(blade_id),
        measurement_id=str(measurement.id),
    )
    return measurement


# ---------------------------------------------------------------------------
# POST /measurements/{measurement_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/measurements/{measurement_id}/approve",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a measurement record",
)
async def approve_measurement(
    measurement_id: uuid.UUID,
    current_user: Annotated[Any, Depends(require_roles("SUPER_ADMIN", "OH_OPERATOR"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Mark a measurement as approved by a QA reviewer or super-admin.

    Once approved, the measurement cannot be modified.  Records the
    approver and approval timestamp.

    Raises:
        HTTP 404 — measurement not found.
        HTTP 409 — measurement is already approved.
    """
    from datetime import datetime, timezone

    measurement = await _get_measurement_or_404(measurement_id, db)

    if measurement.is_approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Measurement is already approved",
        )

    measurement.is_approved = True
    measurement.approved_by_id = current_user.id
    measurement.approved_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "measurement_approved",
        measurement_id=str(measurement_id),
        approved_by=str(current_user.id),
    )
    return StatusResponse(message="Measurement approved successfully")
