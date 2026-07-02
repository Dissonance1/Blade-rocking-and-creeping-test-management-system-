"""
Reset all batch/blade data then seed two full batches:
  - LPTR batch: 90 LPTR blades with all fields + INITIAL measurements
  - HPTR batch: 90 HPTR blades with all fields + INITIAL measurements

Each blade has:
  Serial Number, Melt Number, Work Order, Shop Order, Part Number,
  Nomenclature, Engine Number, Engine Hours, Component Hours,
  Weight (g), Static Moment (g·cm), H1, H2, H3, H4 (mm)

Blade status → MEASUREMENTS_RECORDED (ready to send to assembly)

Usage (from project root, with .env loaded):
    python scripts/reset_and_seed_full.py
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.batch_group import BatchGroup
from app.models.blade import Blade
from app.models.enums import BladeStatus, BladeType, MeasurementType
from app.models.measurement import Measurement
from app.models.user import User
from app.models.workflow import Station

# ─── Colour helpers ──────────────────────────────────────────────────────────

G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
B = "\033[94m"
RESET = "\033[0m"

# ─── Deterministic RNG ───────────────────────────────────────────────────────

rng = random.Random(42)


def _f(lo: float, hi: float, dp: int = 3) -> float:
    return round(rng.uniform(lo, hi), dp)


# ─── Blade specs ─────────────────────────────────────────────────────────────

LPTR_BATCH = {
    "batch_number":    "45786_1458763_01010_260626",
    "work_order":      "45786",
    "shop_order":      "SO45786-L",
    "engine_number":   "14-587-63",
    "part_number":     "104.04.01.010",
    "nomenclature":    "LP Turbine Rotor Blade Stage 2",
    "blade_type":      BladeType.LPTR,
    "count":           90,
    "prefix":          "LPTR",
    # Measurement ranges
    "weight_lo":       148.0,   "weight_hi":      162.0,
    "sm_lo":           320.0,   "sm_hi":          480.0,
    "h1_nom":          12.412,  "h2_nom":         11.934,
    "h3_nom":          12.211,  "h4_nom":         11.673,
    "h_tol":           0.060,
    # Lifecycle hours
    "eng_hrs_lo":      2500,    "eng_hrs_hi":     4800,
    "comp_hrs_lo":     1800,    "comp_hrs_hi":    3600,
}

HPTR_BATCH = {
    "batch_number":    "45786_1458763_02021_260626",
    "work_order":      "45786",
    "shop_order":      "SO45786-H",
    "engine_number":   "14-587-63",
    "part_number":     "104.04.02.021",
    "nomenclature":    "HP Turbine Rotor Blade Stage 1",
    "blade_type":      BladeType.HPTR,
    "count":           90,
    "prefix":          "HPTR",
    "weight_lo":       208.0,   "weight_hi":      228.0,
    "sm_lo":           450.0,   "sm_hi":          660.0,
    "h1_nom":          13.521,  "h2_nom":         13.044,
    "h3_nom":          13.302,  "h4_nom":         12.887,
    "h_tol":           0.055,
    "eng_hrs_lo":      1800,    "eng_hrs_hi":     4200,
    "comp_hrs_lo":     1200,    "comp_hrs_hi":    3000,
}


def _blade_weight(spec: dict) -> float:
    return _f(spec["weight_lo"], spec["weight_hi"], 2)


def _blade_sm(spec: dict, weight: float) -> float:
    # Static moment roughly correlated with weight (CG × weight)
    cg = _f(2.05, 3.20, 3)
    return round(weight * cg, 2)


def _blade_heights(spec: dict) -> dict[str, float]:
    return {
        "H1": round(spec["h1_nom"] + _f(-spec["h_tol"], spec["h_tol"], 4), 3),
        "H2": round(spec["h2_nom"] + _f(-spec["h_tol"], spec["h_tol"], 4), 3),
        "H3": round(spec["h3_nom"] + _f(-spec["h_tol"], spec["h_tol"], 4), 3),
        "H4": round(spec["h4_nom"] + _f(-spec["h_tol"], spec["h_tol"], 4), 3),
    }


# ─── Reset helpers ───────────────────────────────────────────────────────────

TABLES_TO_WIPE = [
    # Most-derived first (FK constraints)
    "slot_allocations",
    "assembly_blade_records",
    "assembly_batch_receipts",
    "batch_events",
    "measurements",
    "workflow_logs",
    "attachments",
    "blades",
    "batch_groups",
]


async def _reset(db: AsyncSession) -> None:
    print(f"\n{R}--- Wiping batch/blade data ---{RESET}")
    for table in TABLES_TO_WIPE:
        result = await db.execute(text(f"DELETE FROM {table}"))
        print(f"  Deleted {result.rowcount:4d} rows from {table}")
    await db.flush()
    print(f"  {G}Reset complete.{RESET}")


# ─── Seed helpers ─────────────────────────────────────────────────────────────

async def _seed_batch(
    db: AsyncSession,
    spec: dict,
    oh_user: User,
    oh_station: Station,
) -> None:
    bn = spec["batch_number"]
    btype = spec["blade_type"]
    count = spec["count"]

    print(f"\n{B}--- Seeding {btype.value} batch: {bn} ({count} blades) ---{RESET}")

    # BatchGroup
    bg = BatchGroup(
        batch_number=bn,
        work_order_number=spec["work_order"],
        part_number=spec["part_number"],
        engine_number=spec["engine_number"],
        nomenclature=spec["nomenclature"],
    )
    db.add(bg)
    await db.flush()

    now = datetime.now(timezone.utc)

    for i in range(1, count + 1):
        serial = f"SN-{spec['prefix']}-{i:03d}"
        melt   = f"MLT-{spec['prefix']}-{i:03d}"
        eng_h  = str(round(_f(spec["eng_hrs_lo"], spec["eng_hrs_hi"], 0)))
        comp_h = str(round(_f(spec["comp_hrs_lo"], spec["comp_hrs_hi"], 0)))

        blade = Blade(
            id=uuid.uuid4(),
            serial_number=serial,
            melt_number=melt,
            work_order_number=spec["work_order"],
            shop_order_number=spec["shop_order"],
            part_number=spec["part_number"],
            nomenclature=spec["nomenclature"],
            engine_number=spec["engine_number"],
            engine_hours=eng_h,
            component_hours=comp_h,
            batch_number=bn,
            blade_type=btype,
            status=BladeStatus.MEASUREMENTS_RECORDED,
            current_station_id=oh_station.id,
            created_by_id=oh_user.id,
            ocr_mismatch_flag=False,
            created_at=now,
            updated_at=now,
        )
        db.add(blade)
        await db.flush()  # get blade.id

        weight = _blade_weight(spec)
        sm     = _blade_sm(spec, weight)
        hdata  = _blade_heights(spec)

        meas = Measurement(
            id=uuid.uuid4(),
            blade_id=blade.id,
            measurement_type=MeasurementType.INITIAL,
            weight_grams=weight,
            static_moment_gcm=sm,
            height_data=hdata,
            measured_by_id=oh_user.id,
            station_id=oh_station.id,
            measured_at=now,
            is_approved=True,
            approved_by_id=oh_user.id,
            approved_at=now,
            notes="Seeded measurement — all values within spec",
        )
        db.add(meas)

        if i % 30 == 0:
            await db.flush()
            print(f"  {G}[{i}/{count}]{RESET} blades created …")

    await db.flush()
    print(f"  {G}[{count}/{count}]{RESET} {btype.value} batch complete — {count} blades, {count} measurements")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(settings.database_url_str, echo=False, future=True)
    Session = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)

    print("\n=== Blade Rocking — Full Reset & Seed ===")
    print(f"Target DB: {settings.database_url_str}\n")

    async with Session() as db:
        try:
            # Resolve OH user and station (must already exist from initial seed)
            oh_user = (await db.execute(
                select(User).where(User.email == "oh.operator@bladerocking.com")
            )).scalar_one_or_none()
            if oh_user is None:
                print(f"{R}[ERROR] oh.operator@bladerocking.com not found. Run seed_data.py first.{RESET}")
                return

            oh_station = (await db.execute(
                select(Station).where(Station.code == "OH_STATION_01")
            )).scalar_one_or_none()
            if oh_station is None:
                print(f"{R}[ERROR] OH_STATION_01 not found. Run seed_data.py first.{RESET}")
                return

            # 1 — wipe
            await _reset(db)

            # 2 — seed LPTR batch
            await _seed_batch(db, LPTR_BATCH, oh_user, oh_station)

            # 3 — seed HPTR batch
            await _seed_batch(db, HPTR_BATCH, oh_user, oh_station)

            await db.commit()
            print(f"\n{G}=== Done — 2 batches, 180 blades, 180 measurements ===\n{RESET}")

        except Exception as exc:
            await db.rollback()
            print(f"\n{R}[ERROR] {exc}{RESET}")
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
