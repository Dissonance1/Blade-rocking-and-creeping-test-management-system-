"""
Station management endpoints.

GET  /stations/                   — list all stations
POST /stations/                   — create station (SUPER_ADMIN)
PUT  /stations/{station_id}       — update station (SUPER_ADMIN)
GET  /stations/{station_id}/blades — blades currently at this station
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import BladeStatus, StationType
from app.schemas.base import PaginatedResponse
from app.schemas.workflow import StationResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas (inline — simple enough not to warrant a separate schema file)
# ---------------------------------------------------------------------------


from pydantic import Field

from app.schemas.base import BaseSchema


class StationCreate(BaseSchema):
    """Payload for creating a new station."""

    name: str = Field(..., min_length=1, max_length=128, description="Station display name")
    code: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Unique station code (e.g. OH-01, ASSY-02)",
        examples=["OH-01"],
    )
    station_type: StationType = Field(..., description="Functional type of the station")
    location: str | None = Field(default=None, max_length=255)


class StationUpdate(BaseSchema):
    """Partial update for a station."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    location: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_station_or_404(station_id: uuid.UUID, db: AsyncSession) -> Any:
    from app.models.workflow import Station

    result = await db.execute(
        select(Station).where(Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station {station_id} not found",
        )
    return station


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[StationResponse],
    status_code=status.HTTP_200_OK,
    summary="List all stations",
)
async def list_stations(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    is_active: bool | None = Query(default=None),
    station_type: StationType | None = Query(default=None),
) -> Any:
    """
    Return all station records, optionally filtered by active status
    and/or station type.

    Results are ordered alphabetically by station name.
    """
    from app.models.workflow import Station

    conditions: list = []
    if is_active is not None:
        conditions.append(Station.is_active.is_(is_active))
    if station_type is not None:
        conditions.append(Station.station_type == station_type)

    query = select(Station).order_by(Station.name)
    if conditions:
        query = query.where(*conditions)

    return list((await db.execute(query)).scalars().all())


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=StationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new station",
)
async def create_station(
    body: StationCreate,
    current_user: Annotated[Any, Depends(require_roles("SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Create a new physical workstation.

    Station codes must be unique system-wide.

    Raises:
        HTTP 409 — a station with the given code already exists.
    """
    from app.models.workflow import Station

    existing = (
        await db.execute(
            select(Station).where(Station.code == body.code.upper())
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Station with code '{body.code}' already exists",
        )

    station = Station(
        name=body.name,
        code=body.code.upper(),
        station_type=body.station_type,
        location=body.location,
        is_active=True,
    )
    db.add(station)
    await db.commit()
    await db.refresh(station)

    logger.info(
        "station_created",
        station_id=str(station.id),
        code=station.code,
        by=str(current_user.id),
    )
    return station


# ---------------------------------------------------------------------------
# PUT /{station_id}
# ---------------------------------------------------------------------------


@router.put(
    "/{station_id}",
    response_model=StationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a station",
)
async def update_station(
    station_id: uuid.UUID,
    body: StationUpdate,
    current_user: Annotated[Any, Depends(require_roles("SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Update mutable fields of an existing station record.

    Note: ``code`` and ``station_type`` are immutable after creation.

    Raises:
        HTTP 404 — station not found.
    """
    station = await _get_station_or_404(station_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(station, field, value)

    await db.commit()
    await db.refresh(station)

    logger.info(
        "station_updated",
        station_id=str(station_id),
        by=str(current_user.id),
        fields=list(update_data.keys()),
    )
    return station


# ---------------------------------------------------------------------------
# GET /{station_id}/blades
# ---------------------------------------------------------------------------


@router.get(
    "/{station_id}/blades",
    status_code=status.HTTP_200_OK,
    summary="List blades currently located at a station",
)
async def list_station_blades(
    station_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    include_terminal: bool = Query(
        default=False,
        description="Include COMPLETED and REJECTED blades in results",
    ),
) -> dict:
    """
    Return blades whose ``current_station_id`` matches the given station.

    By default, terminal blades (COMPLETED, REJECTED) are excluded.

    Raises:
        HTTP 404 — station not found.
    """
    from app.models.blade import Blade

    await _get_station_or_404(station_id, db)

    terminal = {BladeStatus.COMPLETED, BladeStatus.REJECTED}
    conditions = [
        Blade.current_station_id == station_id,
        Blade.deleted_at.is_(None),
    ]
    if not include_terminal:
        conditions.append(Blade.status.notin_(list(terminal)))

    total: int = (
        await db.execute(
            select(func.count()).select_from(Blade).where(*conditions)
        )
    ).scalar_one()

    blades = list(
        (
            await db.execute(
                select(Blade)
                .where(*conditions)
                .order_by(Blade.updated_at.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return {
        "station_id": str(station_id),
        "items": [
            {
                "id": str(b.id),
                "serial_number": b.serial_number,
                "melt_number": b.melt_number,
                "part_number": b.part_number,
                "status": b.status.value if b.status else None,
                "ocr_mismatch_flag": b.ocr_mismatch_flag,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "updated_at": b.updated_at.isoformat() if b.updated_at else None,
            }
            for b in blades
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }
