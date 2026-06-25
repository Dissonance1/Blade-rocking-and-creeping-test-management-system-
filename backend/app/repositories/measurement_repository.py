"""
MeasurementRepository — database operations for the Measurement entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import Measurement
from app.repositories.base import BaseRepository
from app.schemas.measurement import MeasurementCreate, MeasurementUpdate

log = structlog.get_logger(__name__)


class MeasurementRepository(BaseRepository[Measurement, MeasurementCreate, MeasurementUpdate]):
    """Async repository for the ``measurements`` table."""

    model = Measurement

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    # ------------------------------------------------------------------
    # Blade-scoped queries
    # ------------------------------------------------------------------

    async def get_by_blade(self, blade_id: uuid.UUID) -> list[Measurement]:
        """
        Return all measurements for *blade_id* ordered by ``measured_at``
        ascending (oldest first).
        """
        stmt = (
            select(Measurement)
            .where(Measurement.blade_id == blade_id)
            .order_by(Measurement.measured_at.asc())
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)

    async def get_latest_by_blade(self, blade_id: uuid.UUID) -> Measurement | None:
        """Return the most-recently-recorded measurement for *blade_id*."""
        stmt = (
            select(Measurement)
            .where(Measurement.blade_id == blade_id)
            .order_by(Measurement.measured_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # QA approval
    # ------------------------------------------------------------------

    async def approve(
        self,
        measurement_id: uuid.UUID,
        approved_by: uuid.UUID,
    ) -> Measurement | None:
        """
        Mark a measurement as QA-approved.

        Returns the updated :class:`~app.models.measurement.Measurement`, or
        ``None`` if the record was not found.  Re-approving an already-approved
        measurement is idempotent (the ``approved_at`` timestamp is refreshed).
        """
        stmt = select(Measurement).where(Measurement.id == measurement_id)
        result = await self.db.execute(stmt)
        measurement = result.scalar_one_or_none()

        if measurement is None:
            log.warning(
                "measurement_repository.approve.not_found",
                measurement_id=str(measurement_id),
            )
            return None

        measurement.is_approved = True
        measurement.approved_by_id = approved_by
        measurement.approved_at = datetime.now(timezone.utc)
        self.db.add(measurement)
        await self.db.flush()
        await self.db.refresh(measurement)

        log.info(
            "measurement_repository.approved",
            measurement_id=str(measurement_id),
            approved_by=str(approved_by),
        )
        return measurement
