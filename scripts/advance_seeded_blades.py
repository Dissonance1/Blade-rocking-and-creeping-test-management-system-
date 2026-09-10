"""
Advance seed_data.py's blades to MEASUREMENTS_RECORDED.

seed_data.py creates Work Orders + 90 Blade rows each (with an INITIAL
measurement) and marks ``work_order.is_entry_complete = True``, but leaves
``blade.status`` at OH_INSPECTION — it never calls the real
POST /work-orders/{wo}/complete transition, so the blades never became
eligible for Slot Allocation (HPTR) / Send to Assembly (LPTR).

This script closes that gap the same way the real endpoint would
(WorkOrderService.complete -> WorkflowEngine.transition), for every work
order that's marked entry-complete but whose blades are still sitting at
CREATED/OH_INSPECTION.

Usage (from project root, venv activated, same DATABASE_URL as the app):
    python scripts/advance_seeded_blades.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.blade import Blade
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.enums import BladeStatus
from app.workflows.state_machine import WorkflowEngine

GREEN = "\033[92m"
RESET = "\033[0m"


async def main() -> None:
    engine = create_async_engine(settings.database_url_str, echo=False, future=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        oh_user = (
            await db.execute(select(User).where(User.email == "oh.operator@bladerocking.com"))
        ).scalar_one_or_none()
        if oh_user is None:
            print("[ERROR] oh.operator@bladerocking.com not found. Run scripts/seed_data.py first.")
            return

        work_orders = (
            await db.execute(select(WorkOrder).where(WorkOrder.is_entry_complete.is_(True)))
        ).scalars().all()

        wf = WorkflowEngine(db)
        total_advanced = 0

        for wo in work_orders:
            blades = (
                await db.execute(
                    select(Blade).where(
                        Blade.work_order_id == wo.id,
                        Blade.status.in_([BladeStatus.CREATED, BladeStatus.OH_INSPECTION]),
                    )
                )
            ).scalars().all()
            if not blades:
                continue

            advanced_here = 0
            for blade in blades:
                if blade.status == BladeStatus.CREATED:
                    blade, _ = await wf.transition(
                        blade=blade,
                        to_status=BladeStatus.OH_INSPECTION,
                        user=oh_user,
                        station_id=oh_user.station_id,
                        remarks="Backfill: seed data advance.",
                    )
                if blade.status == BladeStatus.OH_INSPECTION:
                    blade, _ = await wf.transition(
                        blade=blade,
                        to_status=BladeStatus.MEASUREMENTS_RECORDED,
                        user=oh_user,
                        station_id=oh_user.station_id,
                        remarks="Backfill: seed data advance.",
                    )
                advanced_here += 1
            total_advanced += advanced_here
            print(f"  {GREEN}[ADVANCED]{RESET} {wo.work_order_number}: {advanced_here} blade(s) -> MEASUREMENTS_RECORDED")

        await db.commit()
        print(f"\n  Total: {total_advanced} blade(s) advanced across {len(work_orders)} work order(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
