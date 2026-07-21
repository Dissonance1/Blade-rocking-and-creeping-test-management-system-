"""
Development database seed script.

Creates a representative set of stations, users, rejection reasons, and
sample blades so that the system is immediately usable after a fresh
``docker-compose up``.

Usage::

    # From the project root (venv activated):
    python scripts/seed_data.py

    # Or via Make:
    make seed

Environment
-----------
The script reads the same ``.env`` file as the FastAPI application.  Set
``DATABASE_URL`` to point to the target database before running.

Idempotency
-----------
Every resource is looked up by a natural key before insertion.  Running the
script multiple times will not create duplicates; it will report existing
records with ``[EXISTS]`` and newly created ones with ``[CREATED]``.
"""

from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure the backend package is importable when running from the project root
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.constants import STATIC_MOMENT_FACTOR
from app.core.security import hash_password
from app.models.blade import Blade
from app.models.enums import BladeStatus, BladeType, MeasurementType, RoleName, StationType
from app.models.measurement import Measurement
from app.models.user import Role, User, UserRole
from app.models.work_order import WorkOrder
from app.models.workflow import Station

# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

STATIONS = [
    {
        "name": "OH Station 01",
        "code": "OH_STATION_01",
        "station_type": StationType.OH,
        "location": "Bay A, Building 1",
    },
    {
        "name": "Assembly Shop 01",
        "code": "ASSEMBLY_SHOP_01",
        "station_type": StationType.ASSEMBLY,
        "location": "Bay B, Building 2",
    },
    {
        "name": "QA Lab 01",
        "code": "QA_LAB_01",
        "station_type": StationType.QA,
        "location": "Ground Floor, Building 3",
    },
]

USERS = [
    {
        "email": "admin@bladerocking.com",
        "username": "admin",
        "password": "Admin@123",
        "full_name": "System Administrator",
        "role": RoleName.SUPER_ADMIN,
        "is_superuser": True,
        "station_code": None,
    },
    {
        "email": "oh.operator@bladerocking.com",
        "username": "oh.operator",
        "password": "Test@123",
        "full_name": "OH Operator",
        "role": RoleName.OH_OPERATOR,
        "is_superuser": False,
        "station_code": "OH_STATION_01",
    },
    {
        "email": "assembly@bladerocking.com",
        "username": "assembly.operator",
        "password": "Test@123",
        "full_name": "Assembly Operator",
        "role": RoleName.ASSEMBLY_OPERATOR,
        "is_superuser": False,
        "station_code": "ASSEMBLY_SHOP_01",
    },
    {
        "email": "qa.viewer@bladerocking.com",
        "username": "qa.viewer",
        "password": "Test@123",
        "full_name": "QA Viewer",
        "role": RoleName.QA_VIEWER,
        "is_superuser": False,
        "station_code": None,
    },
]

# ---------------------------------------------------------------------------
# Colour helpers for terminal output
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _log_created(label: str) -> None:
    print(f"  {GREEN}[CREATED]{RESET}  {label}")


def _log_exists(label: str) -> None:
    print(f"  {YELLOW}[EXISTS] {RESET}  {label}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_or_create_station(db: AsyncSession, data: dict) -> Station:
    result = await db.execute(select(Station).where(Station.code == data["code"]))
    station = result.scalar_one_or_none()
    if station:
        _log_exists(f"Station {data['code']}")
        return station
    station = Station(
        id=uuid.uuid4(),
        name=data["name"],
        code=data["code"],
        station_type=data["station_type"],
        location=data.get("location"),
        is_active=True,
    )
    db.add(station)
    await db.flush()
    _log_created(f"Station {data['code']}")
    return station


async def _get_or_create_role(db: AsyncSession, role_name: RoleName) -> Role:
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role:
        return role
    role = Role(id=uuid.uuid4(), name=role_name)
    db.add(role)
    await db.flush()
    _log_created(f"Role {role_name.value}")
    return role


async def _get_or_create_user(
    db: AsyncSession,
    data: dict,
    station_map: dict[str, Station],
    admin_id: uuid.UUID | None,
) -> User:
    result = await db.execute(select(User).where(User.email == data["email"]))
    user = result.scalar_one_or_none()

    if user:
        _log_exists(f"User {data['email']}")
        return user

    station_id: uuid.UUID | None = None
    if data["station_code"]:
        station_id = station_map[data["station_code"]].id

    user = User(
        id=uuid.uuid4(),
        email=data["email"],
        username=data["username"],
        hashed_password=hash_password(data["password"]),
        full_name=data["full_name"],
        is_active=True,
        is_superuser=data["is_superuser"],
        station_id=station_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Assign role
    role = await _get_or_create_role(db, data["role"])
    user_role = UserRole(
        user_id=user.id,
        role_id=role.id,
        assigned_at=datetime.now(timezone.utc),
        assigned_by=admin_id,
    )
    db.add(user_role)
    await db.flush()

    _log_created(f"User {data['email']} [{data['role'].value}]")
    return user


async def _create_sample_blades(
    db: AsyncSession,
    oh_user: User,
    oh_station: Station,
) -> None:
    """
    Create sample Work Orders — each a full 90-blade, single-blade-type
    scaffold in OH_INSPECTION status, alternating LPTR/HPTR across the set.

    Work Order Number format: {work_order}_{engine_no_stripped}_{part_suffix}_{DDMMYY}
    """

    ENGINE_NO    = "14-587-63"
    ENGINE_STRIP = "1458763"        # hyphens removed
    PART_NUMBER  = "104.04.02.020"
    PART_SUFFIX  = "02020"          # last five digits, dots removed
    BLADES_PER_WORK_ORDER = 90

    # (date_suffix_DDMMYY, blade_type) — 5 LPTR + 5 HPTR work orders
    WORK_ORDER_SPECS = [
        ("180626", BladeType.LPTR),
        ("190626", BladeType.HPTR),
        ("200626", BladeType.LPTR),
        ("210626", BladeType.HPTR),
        ("220626", BladeType.LPTR),
        ("230626", BladeType.HPTR),
        ("240626", BladeType.LPTR),
        ("250626", BladeType.HPTR),
        ("260626", BladeType.LPTR),
        ("270626", BladeType.HPTR),
    ]

    total_blades = 0
    total_work_orders = 0

    for wo_idx, (date_sfx, blade_type) in enumerate(WORK_ORDER_SPECS, start=1):
        base = f"{ENGINE_STRIP}_{PART_SUFFIX}_{date_sfx}"
        wo_number = f"{base}_{blade_type.value}"

        work_order = (
            await db.execute(select(WorkOrder).where(WorkOrder.work_order_number == wo_number))
        ).scalar_one_or_none()
        if work_order is None:
            work_order = WorkOrder(
                id=uuid.uuid4(),
                work_order_number=wo_number,
                shop_order_number=f"SO{base}",
                part_number=PART_NUMBER,
                blade_type=blade_type,
                engine_number=ENGINE_NO,
                engine_hours=f"{round(random.uniform(500, 5000), 2)}:00:00",
                component_hours=f"{round(random.uniform(200, 3000), 2)}:00:00",
                created_by_id=oh_user.id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(work_order)
            await db.flush()
            total_work_orders += 1
            _log_created(f"WorkOrder {wo_number}  ({blade_type.value}, {BLADES_PER_WORK_ORDER} blades)")
        else:
            _log_exists(f"WorkOrder {wo_number}")

        created_in_wo = 0
        for s_no in range(1, BLADES_PER_WORK_ORDER + 1):
            serial = f"{s_no:02d}"
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
                    melt_number=f"MLT{wo_idx:02d}{s_no:04d}",
                    work_order_id=work_order.id,
                    work_order_number=wo_number,
                    shop_order_number=work_order.shop_order_number,
                    part_number=PART_NUMBER,
                    engine_number=ENGINE_NO,
                    engine_hours=work_order.engine_hours,
                    component_hours=work_order.component_hours,
                    blade_type=blade_type,
                    status=BladeStatus.OH_INSPECTION,
                    current_station_id=oh_station.id,
                    created_by_id=oh_user.id,
                    ocr_mismatch_flag=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(blade)
                await db.flush()
                created_in_wo += 1
                total_blades += 1

            existing_measurement = (
                await db.execute(
                    select(Measurement).where(
                        Measurement.blade_id == blade.id,
                        Measurement.measurement_type == MeasurementType.INITIAL,
                    )
                )
            ).scalar_one_or_none()

            if existing_measurement is None:
                # Mirrors the entry-grid weight capture (weight_grams ->
                # static_moment_gcm) plus the post-slot-allocation rocking/creep
                # entry — LPTR requires both rocking and creep, HPTR rocking only.
                weight_grams = round(random.uniform(150.0, 260.0), 4)
                db.add(
                    Measurement(
                        id=uuid.uuid4(),
                        blade_id=blade.id,
                        measurement_type=MeasurementType.INITIAL,
                        weight_grams=weight_grams,
                        static_moment_gcm=round(weight_grams * STATIC_MOMENT_FACTOR, 4),
                        rocking_value=round(random.uniform(0.015, 0.045), 6),
                        creep_value=(
                            round(random.uniform(0.05, 0.25), 6)
                            if blade_type == BladeType.LPTR
                            else None
                        ),
                        measured_by_id=oh_user.id,
                        station_id=oh_station.id,
                        measured_at=datetime.now(timezone.utc),
                    )
                )

            # Flush every 50 blades to avoid huge in-memory batches
            if total_blades % 50 == 0:
                await db.flush()

        if created_in_wo:
            _log_created(f"  {created_in_wo} blade(s) created")

        # All BLADES_PER_WORK_ORDER rows now have melt_number + weight —
        # mark entry complete so the OH Queue offers "Send to Assembly"
        # instead of "Continue Blade Entry".
        if not work_order.is_entry_complete:
            work_order.is_entry_complete = True
            work_order.entry_completed_by_id = oh_user.id
            work_order.entry_completed_at = datetime.now(timezone.utc)
            db.add(work_order)

    await db.flush()
    print(
        f"\n  Total: {total_blades} blade(s) across {total_work_orders} work order(s) created."
    )


# ---------------------------------------------------------------------------
# Main seeding orchestrator
# ---------------------------------------------------------------------------


async def seed() -> None:
    """Run all seed operations inside a single transaction."""
    engine = create_async_engine(settings.database_url_str, echo=False, future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    print("\n=== Blade Rocking — Database Seed ===\n")
    print(f"Target DB: {settings.database_url_str}\n")

    async with session_factory() as db:
        try:
            # ----------------------------------------------------------------
            # Stations
            # ----------------------------------------------------------------
            print("--- Stations ---")
            station_map: dict[str, Station] = {}
            for station_data in STATIONS:
                station = await _get_or_create_station(db, station_data)
                station_map[station_data["code"]] = station

            # ----------------------------------------------------------------
            # Ensure all roles exist
            # ----------------------------------------------------------------
            print("\n--- Roles ---")
            for rn in RoleName:
                await _get_or_create_role(db, rn)

            # ----------------------------------------------------------------
            # Users
            # ----------------------------------------------------------------
            print("\n--- Users ---")
            user_map: dict[str, User] = {}
            admin_id: uuid.UUID | None = None

            for user_data in USERS:
                user = await _get_or_create_user(db, user_data, station_map, admin_id)
                user_map[user_data["email"]] = user
                if user_data["email"] == "admin@bladerocking.com":
                    admin_id = user.id

            # ----------------------------------------------------------------
            # Sample blades
            # ----------------------------------------------------------------
            print("\n--- Sample Blades ---")
            oh_user = user_map["oh.operator@bladerocking.com"]
            oh_station = station_map["OH_STATION_01"]
            await _create_sample_blades(
                db=db,
                oh_user=oh_user,
                oh_station=oh_station,
            )

            await db.commit()
            print("\n=== Seed complete ===\n")

        except Exception as exc:
            await db.rollback()
            print(f"\n[ERROR] Seed failed: {exc}")
            raise

    await engine.dispose()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(seed())
