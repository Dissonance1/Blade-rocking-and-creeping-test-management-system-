from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.models.base import Base

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "future": True,
    # Connection pool tuned for production Postgres workloads.
    "pool_size": 10,
    "max_overflow": 20,
    "pool_pre_ping": True,          # Discard stale connections before use.
    "pool_recycle": 3600,           # Recycle connections every hour.
    "pool_timeout": 30,             # Wait at most 30 s for a pool slot.
    "connect_args": {
        "server_settings": {
            "application_name": settings.APP_NAME,
            "jit": "off",           # Disable JIT for short OLTP queries.
        },
        "command_timeout": 60,
    },
}

engine: AsyncEngine = create_async_engine(
    settings.database_url_str,
    **_engine_kwargs,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncSession:  # type: ignore[return]
    """Yield a database session for the duration of a single request.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Development helper
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all tables declared in the metadata.

    Intended for development / test environments only.  Production deployments
    should use Alembic migrations.
    """
    if settings.ENVIRONMENT == "prod":
        logger.warning(
            "init_db called in production environment — skipping table creation. "
            "Use Alembic migrations instead."
        )
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables initialised", environment=settings.ENVIRONMENT)
