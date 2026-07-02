"""
LAN sync endpoints — exposed by the OH PC (701 Hanger) so the Assembly PC
(720 Hanger) can pull blade data before verifying blades.

GET   /sync/status               — health + station identity check
GET   /sync/blades               — all blades (optionally filtered by batch)
GET   /sync/batches/{batch_no}   — single batch snapshot

These endpoints are read-only and are ONLY meaningful when this instance is
running as the OH station (STATION_TYPE=OH in .env).  On the Assembly PC they
still function but return Assembly data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.blade import Blade
from app.models.enums import BladeStatus, MeasurementType, RoleName
from app.models.measurement import Measurement
from app.models.user import User
from app.schemas.assembly import OHBladeSnapshot, OHSyncResponse

router = APIRouter()

_SYNC_ROLES = [RoleName.ASSEMBLY_OPERATOR, RoleName.OH_OPERATOR, RoleName.SUPER_ADMIN]


async def _latest_measurement(db: AsyncSession, blade_id) -> Measurement | None:
    res = await db.execute(
        select(Measurement)
        .where(
            Measurement.blade_id == blade_id,
            Measurement.measurement_type == MeasurementType.FINAL,
        )
        .order_by(Measurement.recorded_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


@router.get(
    "/status",
    summary="Sync health check — verify OH station is reachable",
)
async def sync_status(
    _: User = Depends(require_roles(*_SYNC_ROLES)),
) -> dict:
    return {
        "station_type": getattr(settings, "STATION_TYPE", "OH"),
        "station_name": getattr(settings, "STATION_NAME", "OH Station"),
        "api_version": "v1",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
    }


@router.get(
    "/blades",
    response_model=OHSyncResponse,
    summary="Pull all blade records (for Assembly to verify against OH data)",
)
async def sync_blades(
    batch_number: str | None = Query(default=None, description="Filter by batch number"),
    status_filter: BladeStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*_SYNC_ROLES)),
) -> OHSyncResponse:
    conditions = [Blade.deleted_at.is_(None)]
    if batch_number:
        conditions.append(Blade.batch_number == batch_number)
    if status_filter:
        conditions.append(Blade.status == status_filter)

    res = await db.execute(
        select(Blade).where(*conditions).order_by(Blade.serial_number)
    )
    blades = list(res.scalars().all())

    snapshots: list[OHBladeSnapshot] = []
    for b in blades:
        m = await _latest_measurement(db, b.id)
        snapshots.append(
            OHBladeSnapshot(
                id=b.id,
                serial_number=b.serial_number,
                blade_type=b.blade_type,
                batch_number=b.batch_number,
                status=b.status,
                weight=float(m.weight) if m and m.weight is not None else None,
                dti_h1=float(m.dti_h1) if m and hasattr(m, "dti_h1") and m.dti_h1 is not None else None,
                dti_h2=float(m.dti_h2) if m and hasattr(m, "dti_h2") and m.dti_h2 is not None else None,
                dti_h3=float(m.dti_h3) if m and hasattr(m, "dti_h3") and m.dti_h3 is not None else None,
                dti_h4=float(m.dti_h4) if m and hasattr(m, "dti_h4") and m.dti_h4 is not None else None,
                part_number=b.part_number,
                work_order_number=b.work_order_number,
                created_at=b.created_at,
            )
        )

    return OHSyncResponse(
        station_id=getattr(settings, "STATION_TYPE", "OH"),
        station_name=getattr(settings, "STATION_NAME", "OH Station — 701 Hanger"),
        synced_at=datetime.now(timezone.utc),
        blade_count=len(snapshots),
        blades=snapshots,
    )


@router.get(
    "/batches/{batch_number}",
    response_model=OHSyncResponse,
    summary="Pull a single batch snapshot from OH",
)
async def sync_batch(
    batch_number: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*_SYNC_ROLES)),
) -> OHSyncResponse:
    res = await db.execute(
        select(Blade).where(
            Blade.batch_number == batch_number,
            Blade.deleted_at.is_(None),
        ).order_by(Blade.serial_number)
    )
    blades = list(res.scalars().all())

    snapshots: list[OHBladeSnapshot] = []
    for b in blades:
        m = await _latest_measurement(db, b.id)
        snapshots.append(
            OHBladeSnapshot(
                id=b.id,
                serial_number=b.serial_number,
                blade_type=b.blade_type,
                batch_number=b.batch_number,
                status=b.status,
                weight=float(m.weight) if m and m.weight is not None else None,
                dti_h1=float(m.dti_h1) if m and hasattr(m, "dti_h1") and m.dti_h1 is not None else None,
                dti_h2=float(m.dti_h2) if m and hasattr(m, "dti_h2") and m.dti_h2 is not None else None,
                dti_h3=float(m.dti_h3) if m and hasattr(m, "dti_h3") and m.dti_h3 is not None else None,
                dti_h4=float(m.dti_h4) if m and hasattr(m, "dti_h4") and m.dti_h4 is not None else None,
                part_number=b.part_number,
                work_order_number=b.work_order_number,
                created_at=b.created_at,
            )
        )

    return OHSyncResponse(
        station_id=getattr(settings, "STATION_TYPE", "OH"),
        station_name=getattr(settings, "STATION_NAME", "OH Station — 701 Hanger"),
        synced_at=datetime.now(timezone.utc),
        blade_count=len(snapshots),
        blades=snapshots,
    )
