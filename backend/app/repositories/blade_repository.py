"""
BladeRepository — all database operations for the Blade entity.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.blade import Blade
from app.models.enums import BladeStatus
from app.repositories.base import BaseRepository
from app.schemas.blade import BladeUpdate

log = structlog.get_logger(__name__)


class BladeRepository(BaseRepository[Blade, Any, BladeUpdate]):
    """Async repository for the ``blades`` table."""

    model = Blade

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    # ------------------------------------------------------------------
    # Work-order-scoped queries
    # ------------------------------------------------------------------

    async def get_by_work_order(self, work_order_id: uuid.UUID) -> list[Blade]:
        """Return all 90 blades for *work_order_id*, ordered by S.No."""
        stmt = (
            select(Blade)
            .where(Blade.work_order_id == work_order_id, Blade.deleted_at.is_(None))
            .order_by(Blade.serial_number)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)

    async def get_row(self, work_order_id: uuid.UUID, s_no: int) -> Blade | None:
        """Return the single blade at position *s_no* (1-90) within a work order."""
        stmt = select(Blade).where(
            Blade.work_order_id == work_order_id,
            Blade.serial_number == f"{s_no:02d}",
            Blade.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def bulk_create_scaffold_rows(
        self,
        work_order: Any,
        created_by_id: uuid.UUID,
        station_id: uuid.UUID | None,
        count: int,
    ) -> list[Blade]:
        """
        Create *count* blank ``CREATED`` blade rows (S.No ``"01"``..``f"{count:02d}"``)
        for a freshly-created work order, copying its common-info fields.
        """
        blades = [
            Blade(
                serial_number=f"{i:02d}",
                work_order_id=work_order.id,
                work_order_number=work_order.work_order_number,
                shop_order_number=work_order.shop_order_number,
                part_number=work_order.part_number,
                engine_number=work_order.engine_number,
                engine_hours=work_order.engine_hours,
                component_hours=work_order.component_hours,
                blade_type=work_order.blade_type,
                status=BladeStatus.CREATED,
                created_by_id=created_by_id,
                current_station_id=station_id,
            )
            for i in range(1, count + 1)
        ]
        self.db.add_all(blades)
        await self.db.flush()
        for blade in blades:
            await self.db.refresh(blade)
        return blades

    # ------------------------------------------------------------------
    # Status transition
    # ------------------------------------------------------------------

    async def update_status(
        self,
        blade_id: uuid.UUID,
        new_status: BladeStatus,
        updated_by: uuid.UUID,
    ) -> Blade:
        """
        Directly set ``blade.status`` without going through the workflow engine.

        Prefer :meth:`WorkflowEngine.transition` in service code; this method
        exists as the low-level DB primitive used by the engine itself.

        Raises :class:`ValueError` when the blade is not found.
        """
        blade = await self.get(blade_id)
        if blade is None:
            raise ValueError(f"Blade {blade_id} not found")

        old_status = blade.status
        blade.status = new_status
        self.db.add(blade)
        await self.db.flush()
        await self.db.refresh(blade)

        log.info(
            "blade.status_updated",
            blade_id=str(blade_id),
            from_status=old_status.value,
            to_status=new_status.value,
            updated_by=str(updated_by),
        )
        return blade

    # ------------------------------------------------------------------
    # Eager-load relationships
    # ------------------------------------------------------------------

    async def get_with_measurements(self, blade_id: uuid.UUID) -> Blade | None:
        """
        Return the blade with ``measurements``, ``slot_allocation``, and
        ``workflow_logs`` eagerly loaded in a single round-trip.
        """
        stmt = (
            select(Blade)
            .options(
                selectinload(Blade.measurements),
                selectinload(Blade.slot_allocation),
                selectinload(Blade.workflow_logs),
            )
            .where(
                Blade.id == blade_id,
                Blade.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

