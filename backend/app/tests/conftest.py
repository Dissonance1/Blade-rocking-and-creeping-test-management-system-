"""
Pytest configuration and shared fixtures for the Blade Rocking test suite.

Fixture hierarchy
-----------------
event_loop
  └── async_engine
        └── db_session
              ├── client (httpx AsyncClient)
              ├── *_user fixtures (super_admin_user, oh_user, …)
              │     └── auth_headers fixture
              ├── sample_blade
              └── sample_blade_with_measurements
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401 — registers every model on Base.metadata
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.base import Base
from app.models.blade import Blade
from app.models.enums import BladeStatus, MeasurementType, RoleName, StationType
from app.models.measurement import Measurement
from app.models.user import Role, User, UserRole
from app.models.workflow import Station

# ---------------------------------------------------------------------------
# Use a dedicated test database to isolate test data from development data.
# Override DATABASE_URL via environment or fall back to the test DB slug.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = str(settings.DATABASE_URL).replace(
    "/" + str(settings.DATABASE_URL).split("/")[-1],
    "/blade_rocking_test",
)

# ---------------------------------------------------------------------------
# Event loop — module-scoped so async_engine can be session-wide
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default asyncio event loop policy for the test session."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
def event_loop(event_loop_policy):
    """
    Session-scoped event loop so the session-scoped ``async_engine`` fixture
    (and everything built on it — ``db_session``, ``client``, etc.) runs on a
    single loop for the whole test session, matching this pytest-asyncio
    version's scoping model (it has no ``loop_scope`` fixture kwarg).
    """
    loop = event_loop_policy.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database engine — one engine per test session for performance
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Create a test-scoped async SQLAlchemy engine against the test database.

    All tables are created at session start and dropped at session end.
    Individual test functions get isolated sessions via the ``db_session``
    fixture which rolls back after each test.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Database session — transaction-scoped rollback after each test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an ``AsyncSession`` that rolls back all writes after each test.

    Uses a savepoint strategy so that the test's own transaction commits
    are visible within the test but are fully unwound at teardown.
    """
    connection = await async_engine.connect()
    transaction = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    session = session_factory()

    # Nested savepoint — each flush creates a sub-transaction that can be
    # rolled back without losing the outer connection transaction.
    await session.begin_nested()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(session_: Any, transaction_: Any) -> None:
        if transaction_.nested and not transaction_._parent.nested:
            session_.begin_nested()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


# ---------------------------------------------------------------------------
# HTTP test client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP client wired to the FastAPI app with the test DB session
    injected via dependency override.
    """
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Content-Type": "application/json"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Station fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def oh_station(db_session: AsyncSession) -> Station:
    """OH (Overhaul) test station."""
    station = Station(
        id=uuid.uuid4(),
        name="OH Station 01",
        code="OH_STATION_TEST_01",
        station_type=StationType.OH,
        is_active=True,
    )
    db_session.add(station)
    await db_session.flush()
    await db_session.refresh(station)
    return station


@pytest_asyncio.fixture
async def assembly_station(db_session: AsyncSession) -> Station:
    """Assembly test station."""
    station = Station(
        id=uuid.uuid4(),
        name="Assembly Shop 01",
        code="ASSEMBLY_TEST_01",
        station_type=StationType.ASSEMBLY,
        is_active=True,
    )
    db_session.add(station)
    await db_session.flush()
    await db_session.refresh(station)
    return station


# ---------------------------------------------------------------------------
# Role fixtures (ensure DB roles exist)
# ---------------------------------------------------------------------------


async def _get_or_create_role(db: AsyncSession, role_name: RoleName) -> Role:
    """Fetch an existing role or create it if absent."""
    from sqlalchemy import select

    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(id=uuid.uuid4(), name=role_name)
        db.add(role)
        await db.flush()
        await db.refresh(role)
    return role


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession,
    *,
    email: str,
    username: str,
    full_name: str,
    role_name: RoleName,
    is_superuser: bool = False,
    station: Station | None = None,
) -> User:
    """Internal helper — create a user with one role assigned."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=username,
        hashed_password=hash_password("Test@123"),
        full_name=full_name,
        is_active=True,
        is_superuser=is_superuser,
        station_id=station.id if station else None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    role = await _get_or_create_role(db, role_name)
    user_role = UserRole(
        user_id=user.id,
        role_id=role.id,
        assigned_at=datetime.now(timezone.utc),
        assigned_by=None,
    )
    db.add(user_role)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def super_admin_user(db_session: AsyncSession) -> User:
    """Super-admin user fixture."""
    return await _make_user(
        db_session,
        email="superadmin.test@example.com",
        username="superadmin_test",
        full_name="Super Admin Test",
        role_name=RoleName.SUPER_ADMIN,
        is_superuser=True,
    )


@pytest_asyncio.fixture
async def oh_user(db_session: AsyncSession, oh_station: Station) -> User:
    """OH Operator user fixture."""
    return await _make_user(
        db_session,
        email="oh.operator.test@example.com",
        username="oh_operator_test",
        full_name="OH Operator Test",
        role_name=RoleName.OH_OPERATOR,
        station=oh_station,
    )


@pytest_asyncio.fixture
async def assembly_user(db_session: AsyncSession, assembly_station: Station) -> User:
    """Assembly Operator user fixture."""
    return await _make_user(
        db_session,
        email="assembly.operator.test@example.com",
        username="assembly_operator_test",
        full_name="Assembly Operator Test",
        role_name=RoleName.ASSEMBLY_OPERATOR,
        station=assembly_station,
    )


@pytest_asyncio.fixture
async def qa_user(db_session: AsyncSession) -> User:
    """QA Viewer user fixture."""
    return await _make_user(
        db_session,
        email="qa.viewer.test@example.com",
        username="qa_viewer_test",
        full_name="QA Viewer Test",
        role_name=RoleName.QA_VIEWER,
    )


# ---------------------------------------------------------------------------
# Auth header helper
# ---------------------------------------------------------------------------


def _make_auth_headers(user: User) -> dict[str, str]:
    """Return a Bearer authorization header dict for *user*."""
    role_names = [ur.role.name for ur in user.user_roles]
    token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "roles": role_names,
            "is_superuser": user.is_superuser,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(oh_user: User) -> dict[str, str]:
    """Auth headers for the default OH operator user."""
    return _make_auth_headers(oh_user)


@pytest.fixture
def super_admin_headers(super_admin_user: User) -> dict[str, str]:
    """Auth headers for the super-admin user."""
    return _make_auth_headers(super_admin_user)


@pytest.fixture
def assembly_headers(assembly_user: User) -> dict[str, str]:
    """Auth headers for the assembly operator user."""
    return _make_auth_headers(assembly_user)


@pytest.fixture
def qa_headers(qa_user: User) -> dict[str, str]:
    """Auth headers for the QA viewer user."""
    return _make_auth_headers(qa_user)


# ---------------------------------------------------------------------------
# Blade fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sample_blade(db_session: AsyncSession, oh_user: User) -> Blade:
    """A blade in CREATED status."""
    blade = Blade(
        id=uuid.uuid4(),
        serial_number=f"BLD-TEST-{uuid.uuid4().hex[:8].upper()}",
        melt_number="MELT-001",
        work_order_number="WO-2024-001",
        part_number="PT-4470",
        nomenclature="HP Turbine Blade Stage 1",
        status=BladeStatus.CREATED,
        created_by_id=oh_user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        ocr_mismatch_flag=False,
    )
    db_session.add(blade)
    await db_session.flush()
    await db_session.refresh(blade)
    return blade


@pytest_asyncio.fixture
async def sample_blade_with_measurements(
    db_session: AsyncSession,
    oh_user: User,
    oh_station: Station,
) -> Blade:
    """
    A blade in MEASUREMENTS_RECORDED status with three rocking measurements.

    This fixture is suitable for testing transitions that require measurements
    to be present (e.g., send-to-assembly).
    """
    blade = Blade(
        id=uuid.uuid4(),
        serial_number=f"BLD-MEAS-{uuid.uuid4().hex[:8].upper()}",
        melt_number="MELT-002",
        work_order_number="WO-2024-002",
        part_number="PT-4470",
        nomenclature="HP Turbine Blade Stage 1",
        status=BladeStatus.MEASUREMENTS_RECORDED,
        current_station_id=oh_station.id,
        created_by_id=oh_user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        ocr_mismatch_flag=False,
    )
    db_session.add(blade)
    await db_session.flush()

    # Add three rocking measurements
    for i in range(3):
        m = Measurement(
            id=uuid.uuid4(),
            blade_id=blade.id,
            measurement_type=MeasurementType.INITIAL,
            rocking_value=float(1.23 + i * 0.01),
            weight_grams=250.0 + i * 0.1,
            measured_by_id=oh_user.id,
            station_id=oh_station.id,
        )
        db_session.add(m)

    await db_session.flush()
    await db_session.refresh(blade)
    return blade
