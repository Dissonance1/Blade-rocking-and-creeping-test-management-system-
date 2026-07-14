"""
BladeRepository — all database operations for the Blade entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.blade import Blade
from app.models.enums import BladeStatus
from app.repositories.base import BaseRepository
from app.schemas.blade import BladeSearchParams, BladeUpdate

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

    async def get_by_status(
        self,
        status: BladeStatus,
        station_id: uuid.UUID | None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Blade], int]:
        """Return blades in *status*, optionally filtered to *station_id*."""
        conditions: list[Any] = [
            Blade.status == status,
            Blade.deleted_at.is_(None),
        ]
        if station_id is not None:
            conditions.append(Blade.current_station_id == station_id)

        base_stmt = select(Blade).where(*conditions)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        page_stmt = base_stmt.offset(skip).limit(limit)
        rows = (await self.db.execute(page_stmt)).scalars().all()

        return list(rows), total

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
    # Rich search
    # ------------------------------------------------------------------

    async def search(
        self,
        params: BladeSearchParams,
    ) -> tuple[list[Blade], int]:
        """
        Full-featured search supporting:

        * Partial ILIKE match on ``serial_number``, ``melt_number``,
          ``work_order_number``, ``part_number``
        * Exact match on ``status``, ``station_id``, ``assigned_to_id``,
          ``created_by_id``
        * Date-range filter on ``created_at``
        * ``ocr_mismatch_only`` flag
        * Pagination and sort order
        """
        conditions: list[Any] = [Blade.deleted_at.is_(None)]

        # --- text filters (ILIKE) ---
        if params.serial_number:
            conditions.append(
                Blade.serial_number.ilike(f"%{params.serial_number}%")
            )
        if params.melt_number:
            conditions.append(Blade.melt_number.ilike(f"%{params.melt_number}%"))
        if params.work_order_number:
            conditions.append(
                Blade.work_order_number.ilike(f"%{params.work_order_number}%")
            )
        if params.part_number:
            conditions.append(Blade.part_number.ilike(f"%{params.part_number}%"))

        # --- exact filters ---
        if params.status is not None:
            conditions.append(Blade.status == params.status)
        if params.station_id is not None:
            conditions.append(Blade.current_station_id == params.station_id)
        if params.assigned_to_id is not None:
            conditions.append(Blade.assigned_to_id == params.assigned_to_id)
        if params.created_by_id is not None:
            conditions.append(Blade.created_by_id == params.created_by_id)
        if params.ocr_mismatch_only:
            conditions.append(Blade.ocr_mismatch_flag.is_(True))

        # --- date range (created_at) ---
        if params.date_from is not None:
            from_dt = datetime(
                params.date_from.year,
                params.date_from.month,
                params.date_from.day,
                tzinfo=timezone.utc,
            )
            conditions.append(Blade.created_at >= from_dt)
        if params.date_to is not None:
            to_dt = datetime(
                params.date_to.year,
                params.date_to.month,
                params.date_to.day,
                23, 59, 59,
                tzinfo=timezone.utc,
            )
            conditions.append(Blade.created_at <= to_dt)

        base_stmt = select(Blade).where(and_(*conditions))

        # --- sorting ---
        sort_column = getattr(Blade, params.sort_by, None)
        if sort_column is None:
            sort_column = Blade.created_at
        base_stmt = base_stmt.order_by(
            sort_column.desc() if params.sort_desc else sort_column.asc()
        )

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        skip = (params.page - 1) * params.page_size
        page_stmt = base_stmt.offset(skip).limit(params.page_size)
        rows = (await self.db.execute(page_stmt)).scalars().all()

        return list(rows), total

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

    # ------------------------------------------------------------------
    # Station helpers
    # ------------------------------------------------------------------

    async def get_pending_at_station(self, station_id: uuid.UUID) -> list[Blade]:
        """
        Return all non-deleted blades currently assigned to *station_id*
        that are in a "work in progress" status (not COMPLETED or REJECTED).
        """
        terminal_statuses = {BladeStatus.COMPLETED, BladeStatus.REJECTED}
        stmt = select(Blade).where(
            Blade.current_station_id == station_id,
            Blade.deleted_at.is_(None),
            Blade.status.not_in(terminal_statuses),
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)
