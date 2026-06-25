"""
SlotRepository — database operations for the SlotAllocation entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.slot_allocation import SlotAllocation
from app.repositories.base import BaseRepository
from app.schemas.slot_allocation import SlotAssignRequest, SlotReassignRequest

log = structlog.get_logger(__name__)


class SlotRepository(BaseRepository[SlotAllocation, SlotAssignRequest, SlotReassignRequest]):
    """Async repository for the ``slot_allocations`` table."""

    model = SlotAllocation

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    # ------------------------------------------------------------------
    # Active-allocation queries
    # ------------------------------------------------------------------

    async def get_active_by_blade(self, blade_id: uuid.UUID) -> SlotAllocation | None:
        """Return the currently active :class:`SlotAllocation` for *blade_id*."""
        stmt = select(SlotAllocation).where(
            SlotAllocation.blade_id == blade_id,
            SlotAllocation.is_active.is_(True),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slot_number(self, slot_number: str) -> SlotAllocation | None:
        """
        Return the active allocation occupying *slot_number*, or ``None``.

        Only the active row is returned; historical (deactivated) allocations
        for the same slot are ignored.
        """
        stmt = select(SlotAllocation).where(
            SlotAllocation.slot_number == slot_number.upper(),
            SlotAllocation.is_active.is_(True),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_active_slots(self) -> list[SlotAllocation]:
        """Return every currently-active slot allocation across all blades."""
        stmt = select(SlotAllocation).where(SlotAllocation.is_active.is_(True))
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)

    # ------------------------------------------------------------------
    # Deactivation
    # ------------------------------------------------------------------

    async def deactivate_blade_slot(
        self,
        blade_id: uuid.UUID,
        deactivated_by: uuid.UUID,
    ) -> bool:
        """
        Deactivate the active slot allocation for *blade_id*.

        Returns ``True`` if a row was deactivated, ``False`` if no active
        allocation existed.

        The deactivated row is preserved for audit; only ``is_active`` flips
        to ``False``.
        """
        allocation = await self.get_active_by_blade(blade_id)
        if allocation is None:
            log.debug(
                "slot_repository.deactivate.no_active_slot",
                blade_id=str(blade_id),
            )
            return False

        allocation.is_active = False
        self.db.add(allocation)
        await self.db.flush()

        log.info(
            "slot_repository.deactivated",
            blade_id=str(blade_id),
            slot_number=allocation.slot_number,
            deactivated_by=str(deactivated_by),
        )
        return True
