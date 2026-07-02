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
from app.core.security import hash_password
from app.models.blade import Blade
from app.models.enums import BladeStatus, BladeType, RoleName, StationType
from app.models.user import Role, User, UserRole
from app.models.batch_group import BatchGroup
from app.models.workflow import RejectionReason, Station

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

REJECTION_REASONS = [
    {
        "code": "OCR_MISMATCH",
        "description": "OCR Mismatch — scanned serial/melt number does not match records",
    },
    {
        "code": "WEIGHT_OOT",
        "description": "Weight Out of Tolerance — blade weight exceeds allowable limits",
    },
    {
        "code": "VISUAL_DEFECT",
        "description": "Visual Defect — cracks, erosion, corrosion, or FOD damage detected",
    },
    {
        "code": "MISSING_DOCS",
        "description": "Missing Documentation — required traveller or certificate not present",
    },
    {
        "code": "ROCKING_OOT",
        "description": "Rocking Value Out of Tolerance — exceeds serviceable limits",
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


async def _get_or_create_rejection_reason(
    db: AsyncSession, data: dict
) -> RejectionReason:
    result = await db.execute(
        select(RejectionReason).where(RejectionReason.code == data["code"])
    )
    rr = result.scalar_one_or_none()
    if rr:
        _log_exists(f"RejectionReason {data['code']}")
        return rr
    rr = RejectionReason(
        id=uuid.uuid4(),
        code=data["code"],
        description=data["description"],
        is_active=True,
    )
    db.add(rr)
    await db.flush()
    _log_created(f"RejectionReason {data['code']}")
    return rr


async def _create_sample_blades(
    db: AsyncSession,
    oh_user: User,
    oh_station: Station,
) -> None:
    """
    Create 10 batches of blades in OH_INSPECTION status.

    Batch number format: {work_order}_{engine_no_stripped}_{part_suffix}_{DDMMYY}

    Batches 1-3  → 90 blades each   (OH)
    Batches 4-5  → 88 / 78 blades   (OH)
    Batches 6-10 → 90 blades each   (OH)
    """

    WORK_ORDER   = "45786"
    ENGINE_NO    = "14-587-63"
    ENGINE_STRIP = "1458763"        # hyphens removed
    PART_NUMBER  = "104.04.02.020"
    PART_SUFFIX  = "02020"          # last five digits, dots removed
    NOMENCLATURE = "HP Turbine Blade Stage 1"

    # (date_suffix_DDMMYY, blade_count)
    BATCH_SPECS = [
        ("180626", 90),
        ("190626", 90),
        ("200626", 90),
        ("210626", 88),
        ("220626", 78),
        ("230626", 90),
        ("240626", 90),
        ("250626", 90),
        ("260626", 90),
        ("270626", 90),
    ]

    total_blades = 0
    total_batches = 0

    for batch_idx, (date_sfx, blade_count) in enumerate(BATCH_SPECS, start=1):
        bn = f"{WORK_ORDER}_{ENGINE_STRIP}_{PART_SUFFIX}_{date_sfx}"

        existing_bg = (
            await db.execute(select(BatchGroup).where(BatchGroup.batch_number == bn))
        ).scalar_one_or_none()
        if not existing_bg:
            db.add(BatchGroup(
                batch_number=bn,
                work_order_number=WORK_ORDER,
                part_number=PART_NUMBER,
                engine_number=ENGINE_NO,
                nomenclature=NOMENCLATURE,
            ))
            total_batches += 1
            _log_created(f"BatchGroup {bn}  ({blade_count} blades)")
        else:
            _log_exists(f"BatchGroup {bn}")

        created_in_batch = 0
        for blade_idx in range(1, blade_count + 1):
            serial = f"SN{batch_idx:02d}{blade_idx:04d}"
            existing = (
                await db.execute(select(Blade).where(Blade.serial_number == serial))
            ).scalar_one_or_none()
            if existing:
                continue

            blade = Blade(
                id=uuid.uuid4(),
                serial_number=serial,
                melt_number=f"MLT{batch_idx:02d}{blade_idx:04d}",
                work_order_number=WORK_ORDER,
                shop_order_number=f"SO{WORK_ORDER}",
                part_number=PART_NUMBER,
                nomenclature=NOMENCLATURE,
                engine_number=ENGINE_NO,
                batch_number=bn,
                engine_hours=str(round(random.uniform(500, 5000), 2)),
                component_hours=str(round(random.uniform(200, 3000), 2)),
                blade_type=BladeType.LPTR if blade_idx % 2 != 0 else BladeType.HPTR,
                status=BladeStatus.OH_INSPECTION,
                current_station_id=oh_station.id,
                created_by_id=oh_user.id,
                ocr_mismatch_flag=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(blade)
            created_in_batch += 1
            total_blades += 1

            # Flush every 50 blades to avoid huge in-memory batches
            if total_blades % 50 == 0:
                await db.flush()

        if created_in_batch:
            _log_created(f"  {created_in_batch} blade(s) created")

    await db.flush()
    print(
        f"\n  Total: {total_blades} blade(s) across {total_batches} batch(es) created."
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
            # Rejection reasons
            # ----------------------------------------------------------------
            print("\n--- Rejection Reasons ---")
            rejection_reasons: list[RejectionReason] = []
            for rr_data in REJECTION_REASONS:
                rr = await _get_or_create_rejection_reason(db, rr_data)
                rejection_reasons.append(rr)

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
