"""
Generic asynchronous repository base class.

Provides a consistent CRUD interface over SQLAlchemy 2.x ``AsyncSession``
that all concrete repositories can inherit from without repeating boilerplate.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

ModelT = TypeVar("ModelT", bound=DeclarativeBase)
CreateSchemaT = TypeVar("CreateSchemaT")
UpdateSchemaT = TypeVar("UpdateSchemaT")


class BaseRepository(Generic[ModelT, CreateSchemaT, UpdateSchemaT]):
    """
    Async repository base class.

    Sub-classes must override ``model`` with the concrete SQLAlchemy model
    class they manage::

        class BladeRepository(BaseRepository[Blade, BladeCreate, BladeUpdate]):
            model = Blade
    """

    model: type[ModelT]  # overridden by every concrete sub-class

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Single-record fetch
    # ------------------------------------------------------------------

    async def get(self, id: uuid.UUID) -> ModelT | None:
        """Return the record with *id*, or ``None`` if not found / soft-deleted."""
        stmt = select(self.model).where(
            self.model.id == id,  # type: ignore[attr-defined]
            self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(self, schema: CreateSchemaT, **kwargs: Any) -> ModelT:
        """
        Persist a new record from a Pydantic *schema*.

        Extra keyword arguments are merged in and override schema fields —
        useful for injecting server-side values such as ``created_by_id``.
        """
        data = schema.model_dump(exclude_unset=False)  # type: ignore[union-attr]
        data.update(kwargs)

        # Drop keys that the model does not have
        model_columns = {c.key for c in self.model.__table__.columns}  # type: ignore[attr-defined]
        data = {k: v for k, v in data.items() if k in model_columns}

        instance: ModelT = self.model(**data)  # type: ignore[call-arg]
        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)

        log.debug(
            "repository.create",
            model=self.model.__name__,
            id=str(getattr(instance, "id", None)),
        )
        return instance

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update(
        self,
        id: uuid.UUID,
        schema: UpdateSchemaT,
    ) -> ModelT | None:
        """
        Apply a partial update from *schema* (only set fields are written).

        Returns the refreshed instance, or ``None`` if the record was not found.
        """
        instance = await self.get(id)
        if instance is None:
            return None

        update_data = schema.model_dump(exclude_unset=True)  # type: ignore[union-attr]
        for field, value in update_data.items():
            if hasattr(instance, field):
                setattr(instance, field, value)

        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)

        log.debug(
            "repository.update",
            model=self.model.__name__,
            id=str(id),
            fields=list(update_data.keys()),
        )
        return instance

    # ------------------------------------------------------------------
    # Soft-delete
    # ------------------------------------------------------------------

    async def soft_delete(self, id: uuid.UUID, deleted_by: uuid.UUID) -> bool:
        """
        Mark the record as deleted by setting ``deleted_at`` to *now*.

        Returns ``True`` if the row existed and was deleted, ``False`` if it
        was already missing or already deleted.
        """
        from datetime import datetime, timezone

        instance = await self.get(id)
        if instance is None:
            log.warning("repository.soft_delete.not_found", model=self.model.__name__, id=str(id))
            return False

        instance.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        self.db.add(instance)
        await self.db.flush()

        log.info(
            "repository.soft_delete",
            model=self.model.__name__,
            id=str(id),
            deleted_by=str(deleted_by),
        )
        return True

    # ------------------------------------------------------------------
    # Existence check
    # ------------------------------------------------------------------

    async def exists(self, id: uuid.UUID) -> bool:
        """Return ``True`` if a non-deleted record with *id* exists."""
        stmt = (
            select(func.count())
            .select_from(self.model)  # type: ignore[arg-type]
            .where(
                self.model.id == id,  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
        )
        count: int = (await self.db.execute(stmt)).scalar_one()
        return count > 0
