"""
Alembic environment configuration.

Supports both:
* **Offline** mode — generates SQL scripts without a live DB connection.
* **Online** mode  — connects to the database and applies migrations directly.

The database URL is read exclusively from the ``DATABASE_URL`` environment
variable (or from ``app.core.config.settings.DATABASE_URL`` when the
application configuration is importable).  This keeps credentials out of
``alembic.ini`` and version control.

Async note
----------
SQLAlchemy 2.x with ``asyncpg`` requires the async engine to be run inside
``asyncio.run()``.  Both ``run_migrations_online`` and helpers are therefore
async, called via :func:`asyncio.run` at module level.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging from the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import all models so that Alembic's autogenerate can detect schema changes.
# ---------------------------------------------------------------------------
# We import Base *after* ensuring all model modules have been imported so
# that their table definitions are registered on the metadata.

try:
    # Import every model module here.  Add new model modules as the project grows.
    import app.models  # noqa: F401  (imports __init__ which re-exports all models)
    from app.models.base import Base  # type: ignore[import]

    target_metadata = Base.metadata
except ImportError:
    # Fallback: if the app package cannot be imported (e.g. during CI bootstrap)
    # set metadata to None — autogenerate will be disabled but migrations still run.
    import warnings

    warnings.warn(
        "Could not import app models. Autogenerate will be disabled.",
        stacklevel=1,
    )
    target_metadata = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Database URL resolution
# ---------------------------------------------------------------------------


def _get_database_url() -> str:
    """
    Return the database URL to use for migrations.

    Resolution order (prefer Pydantic-validated URL to avoid raw-env encoding issues):
    1. ``app.core.config.settings.DATABASE_URL`` — properly URL-encoded by Pydantic.
    2. ``DATABASE_URL`` environment variable (raw, may need manual encoding).
    3. The ``sqlalchemy.url`` value from ``alembic.ini`` (last resort).
    """
    try:
        from app.core.config import settings  # type: ignore[import]

        url = str(settings.DATABASE_URL)
        if url:
            return url
    except Exception:  # noqa: BLE001
        pass

    raw = os.environ.get("DATABASE_URL")
    if raw:
        return raw

    ini_url: str | None = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    raise RuntimeError(
        "No DATABASE_URL found. "
        "Set the DATABASE_URL environment variable before running Alembic."
    )


# ---------------------------------------------------------------------------
# Offline migration mode
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """
    Run migrations in *offline* mode.

    In this mode Alembic emits SQL to stdout (or a file) without opening a
    real database connection.  Useful for generating migration scripts for
    manual review or deployment.
    """
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include schema in comparisons for multi-schema deployments.
        include_schemas=False,
        # Compare server defaults so Alembic detects DEFAULT changes.
        compare_server_default=True,
        # Compare type changes.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration mode (async)
# ---------------------------------------------------------------------------


async def run_async_migrations() -> None:
    """
    Create an async engine and run migrations online.

    Uses ``NullPool`` to avoid connection-pool issues with asyncpg in a
    short-lived script context (each Alembic invocation is one process).
    """
    url = _get_database_url()

    # Overlay the resolved URL on top of the alembic.ini config section.
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def _do_run_migrations(connection: Connection) -> None:
    """Synchronous callback executed inside the async engine's ``run_sync``."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Detect renames accurately.
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        # Render item-level comments in migration files.
        render_as_batch=False,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Entry point for online mode — wraps the async function."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
