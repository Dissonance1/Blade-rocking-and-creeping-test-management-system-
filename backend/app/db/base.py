from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    """Project-wide SQLAlchemy declarative base with async attribute support."""

    # Allow subclasses to declare additional type annotations transparently.
    type_annotation_map: dict[Any, Any] = {}


# ---------------------------------------------------------------------------
# Re-usable mixins
# ---------------------------------------------------------------------------


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds soft-delete support via ``deleted_at`` / ``is_deleted``."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
        index=True,
    )

    def soft_delete(self) -> None:
        """Mark the record as deleted without removing it from the database."""
        self.deleted_at = datetime.now(timezone.utc)
        self.is_deleted = True

    def restore(self) -> None:
        """Undo a soft delete."""
        self.deleted_at = None
        self.is_deleted = False


class AuditMixin:
    """Tracks which user created and last updated the record.

    Both columns are nullable so that records created by automated processes
    (migrations, seed data) or unauthenticated flows are still valid.
    """

    created_by: Mapped[str | None] = mapped_column(
        String(36),  # UUID stored as string for portability
        nullable=True,
        default=None,
        comment="UUID of the user who created this record",
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        default=None,
        comment="UUID of the user who last modified this record",
    )
