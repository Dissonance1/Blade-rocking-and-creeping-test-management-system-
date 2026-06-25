"""
Notification model.

Table: notifications

Supports targeted (user_id set) and broadcast (user_id NULL) notifications.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import NotificationType


class Notification(UUIDPrimaryKeyMixin, Base):
    """
    In-app notification for a specific user or broadcast to all users.

    When ``user_id`` is NULL the notification is treated as a system-wide
    broadcast that any authenticated user may see.
    """

    __tablename__ = "notifications"

    # NULL => broadcast
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    notification_type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, name="notificationtype", create_type=True),
        nullable=False,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Read state
    # -----------------------------------------------------------------------
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -----------------------------------------------------------------------
    # Optional association with a blade
    # -----------------------------------------------------------------------
    blade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Arbitrary extra data (e.g. deep-link params)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    user: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[user_id],
        lazy="noload",
    )
    blade: Mapped["Blade | None"] = relationship(  # type: ignore[name-defined]
        "Blade",
        foreign_keys=[blade_id],
        back_populates="notifications",
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification [{self.notification_type.value}] "
            f"user={self.user_id} read={self.is_read}>"
        )


# Deferred imports
from app.models.user import User  # noqa: E402, F401
from app.models.blade import Blade  # noqa: E402, F401
