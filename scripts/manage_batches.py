#!/usr/bin/env python3
"""
Batch management script.

Actions:
  1. Hard-delete BATCH-2024-007 and BATCH-2024-008 (all blades + related rows)
  2. Seed BATCH-2024-002 through BATCH-2024-008:
       002-006  → 90 blades each (full)
       007      → 88 blades  (LPTR)
       008      → 74 blades  (HPTR)

Run:
    docker compose exec backend python scripts/manage_batches.py
"""

import asyncio
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, "/app")

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.blade import Blade
from app.models.batch_group import BatchGroup
from app.models.batch_event import BatchEvent
from app.models.measurement import Measurement
from app.models.slot_allocation import SlotAllocation
from app.models.workflow import WorkflowLog, Station
from app.models.notification import Notification
from app.models.attachment import Attachment
from app.models.user import User
from app.models.enums import BladeStatus, BladeType, MeasurementType

random.seed(42)

# ── Batches to wipe before re-seeding ────────────────────────────────────────
BATCHES_TO_DELETE = ["2", "3", "4", "5", "6", "7", "8",
                     # also wipe old-format names if present
                     "BATCH-2024-002", "BATCH-2024-003", "BATCH-2024-004",
                     "BATCH-2024-005", "BATCH-2024-006", "BATCH-2024-007", "BATCH-2024-008"]

# ── New batch definitions ─────────────────────────────────────────────────────
#  2  LPTR  90 blades  ← complete LPTR batch
#  3  HPTR  90 blades  ← complete HPTR batch
#  4  LPTR  90 blades
#  5  HPTR  90 blades
#  6  LPTR  90 blades
#  7  LPTR  88 blades  (partial)
#  8  HPTR  74 blades  (partial)

BATCH_CONFIGS = [
    dict(number="2", count=90, blade_type=BladeType.LPTR,
         engine="CF6-80C2-SN20002", wo="WO-2024-CF6-002", so="SO-720-2024-002",
         pn="PN-LPT-S3-002", nom="LPT Stage 3 Rotor Blade"),
    dict(number="3", count=90, blade_type=BladeType.HPTR,
         engine="CFM56-7B-SN20003", wo="WO-2024-CFM-003", so="SO-720-2024-003",
         pn="PN-HPT-S1-003", nom="HPT Stage 1 Rotor Blade"),
    dict(number="4", count=90, blade_type=BladeType.LPTR,
         engine="CF6-80C2-SN20004", wo="WO-2024-CF6-004", so="SO-720-2024-004",
         pn="PN-LPT-S3-004", nom="LPT Stage 3 Rotor Blade"),
    dict(number="5", count=90, blade_type=BladeType.HPTR,
         engine="PW4000-SN20005",   wo="WO-2024-PW4-005", so="SO-720-2024-005",
         pn="PN-HPT-S2-005", nom="HPT Stage 2 Rotor Blade"),
    dict(number="6", count=90, blade_type=BladeType.LPTR,
         engine="CF6-80C2-SN20006", wo="WO-2024-CF6-006", so="SO-720-2024-006",
         pn="PN-LPT-S4-006", nom="LPT Stage 4 Rotor Blade"),
    dict(number="7", count=88, blade_type=BladeType.LPTR,
         engine="CF6-80C2-SN20007", wo="WO-2024-CF6-007", so="SO-720-2024-007",
         pn="PN-LPT-S3-007", nom="LPT Stage 3 Rotor Blade"),
    dict(number="8", count=74, blade_type=BladeType.HPTR,
         engine="PW4000-SN20008",   wo="WO-2024-PW4-008", so="SO-720-2024-008",
         pn="PN-HPT-S1-008", nom="HPT Stage 1 Rotor Blade"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slot(blade_idx: int) -> tuple[str, str]:
    """
    Assign slot number using groups of 12.
    Blade 1-12 → A-01…A-12, 13-24 → B-01…B-12, etc.
    """
    g = (blade_idx - 1) // 12
    p = (blade_idx - 1) % 12 + 1
    letter = chr(ord("A") + g)
    return f"{letter}-{p:02d}", letter


def _weight(blade_type: BladeType) -> float:
    if blade_type == BladeType.LPTR:
        return round(random.uniform(142.0, 148.0), 4)
    return round(random.uniform(86.0, 94.0), 4)


def _height_data() -> dict:
    base = random.uniform(142.5, 144.5)
    return {f"H{i}": round(base + random.uniform(-0.4, 0.4), 3) for i in range(1, 6)}


# ── Delete batch ──────────────────────────────────────────────────────────────

async def delete_batch(session: AsyncSession, batch_num: str) -> None:
    res = await session.execute(
        select(Blade.id).where(Blade.batch_number == batch_num)
    )
    ids = [r[0] for r in res.fetchall()]

    if ids:
        for Model in (WorkflowLog, Measurement, SlotAllocation, Notification, Attachment):
            await session.execute(delete(Model).where(Model.blade_id.in_(ids)))
        await session.execute(delete(Blade).where(Blade.id.in_(ids)))

    await session.execute(delete(BatchGroup).where(BatchGroup.batch_number == batch_num))
    await session.execute(delete(BatchEvent).where(BatchEvent.batch_number == batch_num))
    print(f"  [DELETED] {batch_num}  ({len(ids)} blades removed)")


# ── Create batch ──────────────────────────────────────────────────────────────

async def create_batch(
    session: AsyncSession,
    cfg: dict,
    admin_id,
    station_id,
) -> None:
    batch_num = cfg["number"]
    blade_count = cfg["count"]
    blade_type = cfg["blade_type"]
    batch_idx = int(batch_num)  # 2 … 8
    now = datetime.now(timezone.utc)

    # BatchGroup row
    session.add(BatchGroup(
        id=uuid4(),
        batch_number=batch_num,
        work_order_number=cfg["wo"],
        part_number=cfg["pn"],
        engine_number=cfg["engine"],
        nomenclature=cfg["nom"],
    ))

    # One blade record + measurement + slot + workflow log per blade
    for i in range(1, blade_count + 1):
        blade_id = uuid4()
        wt = _weight(blade_type)
        sm = round(wt * 1.57 * 20, 4)
        slot_num, group_id = _slot(i)

        # Blade
        session.add(Blade(
            id=blade_id,
            serial_number=f"{batch_idx}-{i}",
            melt_number=f"MLT-{batch_idx}-{i}",
            work_order_number=cfg["wo"],
            shop_order_number=cfg["so"],
            part_number=cfg["pn"],
            nomenclature=cfg["nom"],
            engine_number=cfg["engine"],
            batch_number=batch_num,
            engine_hours=str(random.randint(1200, 2800)),
            component_hours=str(random.randint(400, 900)),
            blade_type=blade_type,
            status=BladeStatus.MEASUREMENTS_RECORDED,
            current_station_id=station_id,
            created_by_id=admin_id,
            assigned_to_id=admin_id,
            ocr_mismatch_flag=False,
        ))

        # Measurement (INITIAL, approved)
        session.add(Measurement(
            id=uuid4(),
            blade_id=blade_id,
            measurement_type=MeasurementType.INITIAL,
            weight_grams=Decimal(str(wt)),
            static_moment_gcm=Decimal(str(sm)),
            rocking_value=Decimal(str(round(random.uniform(0.008, 0.025), 6))),
            creep_value=Decimal(str(round(random.uniform(0.004, 0.012), 6)))
                        if blade_type == BladeType.LPTR else None,
            height_data=_height_data(),
            measured_by_id=admin_id,
            station_id=station_id,
            is_approved=True,
            approved_by_id=admin_id,
            approved_at=now,
            notes="Auto-generated by manage_batches.py",
        ))

        # Slot allocation (balanced)
        session.add(SlotAllocation(
            id=uuid4(),
            blade_id=blade_id,
            slot_number=slot_num,
            position=i,
            group_id=group_id,
            allocated_by_id=admin_id,
            is_active=True,
            is_balanced=True,
            unbalance_value=Decimal(str(round(random.uniform(0.0001, 0.005), 6))),
            balancing_remarks="Within specification — batch seed",
        ))

        # Workflow log (CREATED → MEASUREMENTS_RECORDED)
        session.add(WorkflowLog(
            id=uuid4(),
            blade_id=blade_id,
            from_status=BladeStatus.CREATED,
            to_status=BladeStatus.MEASUREMENTS_RECORDED,
            action_by_id=admin_id,
            station_id=station_id,
            remarks="Batch seeded — all checks passed",
        ))

    await session.commit()
    label = "LPTR — full" if blade_type == BladeType.LPTR and blade_count == 90 else \
            "HPTR — full" if blade_type == BladeType.HPTR and blade_count == 90 else \
            f"{blade_type.value} — partial"
    print(f"  [CREATED] {batch_num}  {blade_count} blades  ({label})")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Resolve admin user
        res = await session.execute(
            select(User).where(User.is_superuser == True).limit(1)
        )
        admin = res.scalar_one_or_none()
        if not admin:
            res = await session.execute(select(User).limit(1))
            admin = res.scalar_one()
        print(f"User    : {admin.email}")

        # Resolve OH station
        res = await session.execute(select(Station).limit(1))
        station = res.scalar_one_or_none()
        station_id = station.id if station else None
        print(f"Station : {station.name if station else 'none'}\n")

        # Step 1 — delete old batches
        print("=== Deleting old batches ===")
        for bn in BATCHES_TO_DELETE:
            await delete_batch(session, bn)
        await session.commit()

        # Step 2 — create new batches
        print("\n=== Creating new batches ===")
        for cfg in BATCH_CONFIGS:
            res = await session.execute(
                select(BatchGroup).where(BatchGroup.batch_number == cfg["number"])
            )
            if res.scalar_one_or_none():
                print(f"  [EXISTS]  {cfg['number']} — skipping")
                continue
            await create_batch(session, cfg, admin.id, station_id)

    print("\n✓  All done.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
