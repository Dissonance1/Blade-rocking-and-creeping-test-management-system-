"""
AuditLog model.

Table: audit_logs

Immutable HTTP-request-level and business-action-level audit trail.
Written by middleware and service-layer code respectively.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """
    Immutable record of every HTTP request and/or data mutation.

    HTTP-layer fields (method, path, status_code, ip_address, …) are
    populated by middleware on every request.

    Domain-action fields (action, resource_type, resource_id, changes)
    are optionally populated by service-layer code for mutations that
    require a richer audit trail (e.g. blade status transitions, user
    management operations).
    """

    __tablename__ = "audit_logs"

    # -----------------------------------------------------------------------
    # HTTP layer (always populated)
    # -----------------------------------------------------------------------
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max 45 chars
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_body_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True  # SHA-256 hex digest
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -----------------------------------------------------------------------
    # Domain / business-action layer (optionally populated)
    # -----------------------------------------------------------------------
    action: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # e.g. "blade.status_update"
    resource_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # e.g. "Blade"
    resource_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True  # UUID as string for flexibility
    )
    changes: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None
    )  # {"field": {"old": ..., "new": ...}}

    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_user_ts", "user_id", "timestamp"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog {self.method} {self.path} "
            f"[{self.status_code}] user={self.user_id}>"
        )
