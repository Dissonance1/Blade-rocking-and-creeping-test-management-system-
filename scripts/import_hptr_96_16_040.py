"""
One-off import of the real HPTR_96-16-040.xls dataset into a new Work Order.

Reads the parsed JSON (see `_parse_hptr_xls.py`) rather than the .xls
directly, since the legacy BIFF8 format needs `xlrd`, which is not a backend
dependency — the parse step runs standalone with system Python + xlrd.

Idempotent like scripts/seed_data.py: safe to re-run, existing rows are
reported with [EXISTS] rather than duplicated.

Usage::

    DATABASE_URL=postgresql+asyncpg://blade_user:<password>@localhost:5432/blade_rocking \\
        backend/.venv/bin/python scripts/import_hptr_96_16_040.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.blade import Blade
from app.models.enums import BladeStatus, BladeType, MeasurementType, RoleName, StationType
from app.models.measurement import Measurement
from app.models.user import Role, User, UserRole
from app.models.work_order import WorkOrder
from app.models.workflow import Station

PARSED_JSON = Path(__file__).resolve().parent.parent / "hptr_96_16_040_parsed.json"

# Placeholder fields not present in the spreadsheet — the sheet only has
# per-blade Sl.No/Melt No./Weight/Static Moment/Rocking. Flagged clearly here
# and in the printed output so they're easy to find and correct later.
WORK_ORDER_NUMBER = "96-16-040_HPTR"
SHOP_ORDER_NUMBER = "SO_96-16-040"
PART_NUMBER = "TBD"
ENGINE_NUMBER = "96-16-040"
ENGINE_HOURS = "TBD"

GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _log_created(label: str) -> None:
    print(f"  {GREEN}[CREATED]{RESET}  {label}")


def _log_exists(label: str) -> None:
    print(f"  {YELLOW}[EXISTS] {RESET}  {label}")


async def _get_or_create_role(db: AsyncSession, role_name: RoleName) -> Role:
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role:
        return role
    role = Role(id=uuid.uuid4(), name=role_name)
    db.add(role)
    await db.flush()
    return role


async def _get_or_create_oh_station(db: AsyncSession) -> Station:
    result = await db.execute(select(Station).where(Station.code == "OH_STATION_01"))
    station = result.scalar_one_or_none()
    if station:
        _log_exists("Station OH_STATION_01")
        return station
    station = Station(
        id=uuid.uuid4(),
        name="OH Station 01",
        code="OH_STATION_01",
        station_type=StationType.OH,
        location="Bay A, Building 1",
        is_active=True,
    )
    db.add(station)
    await db.flush()
    _log_created("Station OH_STATION_01")
    return station


async def _get_or_create_oh_user(db: AsyncSession, station: Station) -> User:
    email = "oh.operator@bladerocking.com"
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        _log_exists(f"User {email}")
        return user

    from app.core.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email=email,
        username="oh.operator",
        hashed_password=hash_password("Test@123"),
        full_name="OH Operator",
        is_active=True,
        is_superuser=False,
        station_id=station.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    role = await _get_or_create_role(db, RoleName.OH_OPERATOR)
    db.add(
        UserRole(
            user_id=user.id,
            role_id=role.id,
            assigned_at=datetime.now(timezone.utc),
            assigned_by=None,
        )
    )
    await db.flush()
    _log_created(f"User {email} [OH_OPERATOR]")
    return user


async def _get_or_create_work_order(db: AsyncSession, created_by: User) -> WorkOrder:
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.work_order_number == WORK_ORDER_NUMBER)
    )
    work_order = result.scalar_one_or_none()
    if work_order:
        _log_exists(f"WorkOrder {WORK_ORDER_NUMBER}")
        return work_order

    work_order = WorkOrder(
        id=uuid.uuid4(),
        work_order_number=WORK_ORDER_NUMBER,
        shop_order_number=SHOP_ORDER_NUMBER,
        part_number=PART_NUMBER,
        blade_type=BladeType.HPTR,
        engine_number=ENGINE_NUMBER,
        engine_hours=ENGINE_HOURS,
        component_hours=None,
        created_by_id=created_by.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(work_order)
    await db.flush()
    _log_created(f"WorkOrder {WORK_ORDER_NUMBER}  (HPTR, 90 blades, from HPTR_96-16-040.xls)")
    return work_order


async def _import_blades(
    db: AsyncSession,
    work_order: WorkOrder,
    oh_user: User,
    oh_station: Station,
    rows: list[dict],
) -> None:
    created_blades = 0
    created_measurements = 0

    for row in rows:
        serial = f"{row['sl_no']:02d}"
        blade = (
            await db.execute(
                select(Blade).where(
                    Blade.work_order_id == work_order.id,
                    Blade.serial_number == serial,
                )
            )
        ).scalar_one_or_none()

        if blade is None:
            blade = Blade(
                id=uuid.uuid4(),
                serial_number=serial,
                melt_number=row["melt_number"],
                work_order_id=work_order.id,
                work_order_number=work_order.work_order_number,
                shop_order_number=work_order.shop_order_number,
                part_number=work_order.part_number,
                engine_number=work_order.engine_number,
                engine_hours=work_order.engine_hours,
                component_hours=work_order.component_hours,
                blade_type=BladeType.HPTR,
                status=BladeStatus.OH_INSPECTION,
                current_station_id=oh_station.id,
                created_by_id=oh_user.id,
                ocr_mismatch_flag=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(blade)
            await db.flush()
            created_blades += 1

        existing_measurement = (
            await db.execute(
                select(Measurement).where(
                    Measurement.blade_id == blade.id,
                    Measurement.measurement_type == MeasurementType.INITIAL,
                )
            )
        ).scalar_one_or_none()

        if existing_measurement is None:
            db.add(
                Measurement(
                    id=uuid.uuid4(),
                    blade_id=blade.id,
                    measurement_type=MeasurementType.INITIAL,
                    weight_grams=row["weight_actual_gm"],
                    static_moment_gcm=row["static_moment_gcm"],
                    rocking_value=row["rocking_mm"],
                    creep_value=None,
                    measured_by_id=oh_user.id,
                    station_id=oh_station.id,
                    measured_at=datetime.now(timezone.utc),
                )
            )
            await db.flush()
            created_measurements += 1

    print(f"  Blades created:      {created_blades} / {len(rows)}")
    print(f"  Measurements created: {created_measurements} / {len(rows)}")


async def import_hptr() -> None:
    if not PARSED_JSON.exists():
        raise SystemExit(f"Missing {PARSED_JSON} — run _parse_hptr_xls.py first")

    rows = json.loads(PARSED_JSON.read_text(encoding="utf-8"))
    if len(rows) != 90:
        raise SystemExit(f"Expected 90 blades, parsed {len(rows)} — aborting")

    engine = create_async_engine(settings.database_url_str, echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    print("\n=== HPTR_96-16-040.xls Import ===\n")
    print(f"Target DB: {settings.database_url_str}\n")
    print("Placeholder WorkOrder fields (not present in the spreadsheet):")
    print(f"  shop_order_number = {SHOP_ORDER_NUMBER!r}")
    print(f"  part_number       = {PART_NUMBER!r}")
    print(f"  engine_number     = {ENGINE_NUMBER!r}")
    print(f"  engine_hours      = {ENGINE_HOURS!r}\n")

    async with session_factory() as db:
        try:
            oh_station = await _get_or_create_oh_station(db)
            oh_user = await _get_or_create_oh_user(db, oh_station)
            work_order = await _get_or_create_work_order(db, oh_user)

            print("\n--- Blades & Measurements ---")
            await _import_blades(db, work_order, oh_user, oh_station, rows)

            await db.commit()
            print("\n=== Import complete ===\n")
        except Exception:
            await db.rollback()
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(import_hptr())
