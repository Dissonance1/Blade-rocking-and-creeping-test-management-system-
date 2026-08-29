"""
One-off import of HPTR_0083.xlsx into a new Work Order "0083".

Reuses app.services.excel_import.parse_work_order_rows (the same parser the
in-app "Upload Excel" button uses) to read S.No / Melt Number / raw Weight
from the sheet, then writes Blade + Measurement rows directly — this
predates the "Upload Excel" button existing end-to-end in the running app,
so it goes straight to the DB the same way scripts/import_hptr_16_96_317.py
already does for the sibling file.

Scope: serial number, melt number, and weight data only. Weight (g) and
Static Moment are derived server-side via WEIGHT_TO_GRAMS_FACTOR /
STATIC_MOMENT_FACTOR, exactly matching the sheet's own W*1.57 / *20
formulas. Slot allocation and rocking values are entered separately later
through the normal Assembly / Rocking & Creep Entry workflows, so blades
are left at OH_INSPECTION with no SlotAllocation rows and rocking_value=None.

Work Order header fields (work_order_number aside) are not present in the
sheet — per explicit instruction, work_order_number="0083" and every other
header field is the literal placeholder "TBD" pending real values.

Idempotent like scripts/seed_data.py: safe to re-run, existing rows are
reported with [EXISTS] rather than duplicated.

Usage (run inside the oh_backend container, which already has DATABASE_URL
and all backend dependencies)::

    docker exec oh_backend python scripts/import_hptr_0083.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if _BACKEND_DIR.exists() and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
elif str(_REPO_ROOT) not in sys.path:
    # Running inside the backend container, where the container root IS the
    # backend directory (no nested backend/ subfolder to find).
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.constants import STATIC_MOMENT_FACTOR, WEIGHT_TO_GRAMS_FACTOR
from app.models.blade import Blade
from app.models.enums import BladeStatus, BladeType, MeasurementType, RoleName, StationType
from app.models.measurement import Measurement
from app.models.user import Role, User, UserRole
from app.models.work_order import WorkOrder
from app.models.workflow import Station
from app.services.excel_import import parse_work_order_rows

XLSX_PATH = _REPO_ROOT / "HPTR_0083.xlsx"

WORK_ORDER_NUMBER = "0083"
SHOP_ORDER_NUMBER = "TBD"
PART_NUMBER = "TBD"
ENGINE_NUMBER = "TBD"
ENGINE_HOURS = "TBD"
COMPONENT_HOURS = None

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def _log_created(label: str) -> None:
    print(f"  {GREEN}[CREATED]{RESET}  {label}")


def _log_exists(label: str) -> None:
    print(f"  {YELLOW}[EXISTS] {RESET}  {label}")


def _log_skipped(label: str) -> None:
    print(f"  {RED}[SKIPPED]{RESET}  {label}")


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
        component_hours=COMPONENT_HOURS,
        created_by_id=created_by.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(work_order)
    await db.flush()
    _log_created(f"WorkOrder {WORK_ORDER_NUMBER}  (HPTR, from HPTR_0083.xlsx)")
    return work_order


async def _import_blades(
    db: AsyncSession,
    work_order: WorkOrder,
    oh_user: User,
    oh_station: Station,
    rows: list[tuple[int, object]],
) -> None:
    created_blades = 0
    created_measurements = 0

    for s_no, row_update in rows:
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
                melt_number=row_update.melt_number,
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
        elif row_update.melt_number and not blade.melt_number:
            blade.melt_number = row_update.melt_number

        if row_update.raw_weight is not None:
            existing_measurement = (
                await db.execute(
                    select(Measurement).where(
                        Measurement.blade_id == blade.id,
                        Measurement.measurement_type == MeasurementType.INITIAL,
                    )
                )
            ).scalar_one_or_none()

            if existing_measurement is None:
                weight_grams = round(row_update.raw_weight * WEIGHT_TO_GRAMS_FACTOR, 4)
                static_moment_gcm = round(weight_grams * STATIC_MOMENT_FACTOR, 4)
                db.add(
                    Measurement(
                        id=uuid.uuid4(),
                        blade_id=blade.id,
                        measurement_type=MeasurementType.INITIAL,
                        weight_grams=weight_grams,
                        static_moment_gcm=static_moment_gcm,
                        rocking_value=None,
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


async def import_hptr_0083() -> None:
    if not XLSX_PATH.exists():
        raise SystemExit(f"Missing {XLSX_PATH}")

    parsed = parse_work_order_rows(XLSX_PATH.read_bytes())
    if parsed.errors:
        print(f"\n{YELLOW}Parse warnings ({len(parsed.errors)}):{RESET}")
        for err in parsed.errors:
            _log_skipped(f"Sheet row {err.row}: {err.message}")
    if not parsed.rows:
        raise SystemExit("No valid rows parsed from HPTR_0083.xlsx — aborting")

    engine = create_async_engine(settings.database_url_str, echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    print("\n=== HPTR_0083.xlsx Import ===\n")
    print(f"Target DB: {settings.database_url_str}\n")
    print("Placeholder WorkOrder fields (not present in the spreadsheet):")
    print(f"  work_order_number = {WORK_ORDER_NUMBER!r}")
    print(f"  shop_order_number = {SHOP_ORDER_NUMBER!r}  (TBD)")
    print(f"  part_number       = {PART_NUMBER!r}  (TBD)")
    print(f"  engine_number     = {ENGINE_NUMBER!r}  (TBD)")
    print(f"  engine_hours      = {ENGINE_HOURS!r}  (TBD)")
    print(f"\nParsed {len(parsed.rows)} valid row(s) from the sheet.")
    print("Slot allocation and rocking values are NOT set — enter those")
    print("separately via the Assign-Slot and Rocking & Creep Entry screens.\n")

    async with session_factory() as db:
        try:
            oh_station = await _get_or_create_oh_station(db)
            oh_user = await _get_or_create_oh_user(db, oh_station)
            work_order = await _get_or_create_work_order(db, oh_user)

            print("\n--- Blades & Measurements ---")
            await _import_blades(db, work_order, oh_user, oh_station, parsed.rows)

            await db.commit()
            print("\n=== Import complete ===\n")
        except Exception:
            await db.rollback()
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(import_hptr_0083())
