"""
WorkOrderRepository — database operations for the WorkOrder header entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_order import WorkOrder
from app.repositories.base import BaseRepository
from app.schemas.work_order import WorkOrderCreate

log = structlog.get_logger(__name__)


class WorkOrderRepository(BaseRepository[WorkOrder, WorkOrderCreate, Any]):
    """Async repository for the ``work_orders`` table."""

    model = WorkOrder

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    async def get_by_number(self, work_order_number: str) -> WorkOrder | None:
        """Return the WorkOrder matching *work_order_number*, if any."""
        stmt = select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_header(
        self,
        data: WorkOrderCreate,
        created_by_id: uuid.UUID,
    ) -> WorkOrder:
        """Persist a new WorkOrder header row."""
        component_hours = data.component_hours or data.engine_hours
        work_order = WorkOrder(
            work_order_number=data.work_order_number,
            shop_order_number=data.shop_order_number,
            part_number=data.part_number,
            blade_type=data.blade_type,
            engine_number=data.engine_number,
            engine_hours=data.engine_hours,
            component_hours=component_hours,
            created_by_id=created_by_id,
        )
        self.db.add(work_order)
        await self.db.flush()
        await self.db.refresh(work_order)
        log.info(
            "work_order_repository.created",
            work_order_number=work_order.work_order_number,
        )
        return work_order

    async def mark_complete(self, work_order: WorkOrder, completed_by_id: uuid.UUID) -> WorkOrder:
        """Mark *work_order* as entry-complete (idempotent)."""
        if not work_order.is_entry_complete:
            work_order.is_entry_complete = True
            work_order.entry_completed_at = datetime.now(timezone.utc)
            work_order.entry_completed_by_id = completed_by_id
            self.db.add(work_order)
            await self.db.flush()
            await self.db.refresh(work_order)
        return work_order
