"""
Station, RejectionReason, and WorkflowLog models.

These are defined before blade.py and user.py finish loading because
both FK-reference Station. The Station table is therefore in this module
to break the circular dependency.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BladeStatus, StationType


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------

class Station(UUIDPrimaryKeyMixin, Base):
    """Physical workstation within the repair/overhaul process."""

    __tablename__ = "stations"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    station_type: Mapped[StationType] = mapped_column(
        SAEnum(StationType, name="stationtype", create_type=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships (back-refs populated by other models)
    blades: Mapped[list["Blade"]] = relationship(  # type: ignore[name-defined]
        "Blade",
        foreign_keys="[Blade.current_station_id]",
        back_populates="current_station",
        lazy="noload",
    )
    users: Mapped[list["User"]] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys="[User.station_id]",
        back_populates="station",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<Station {self.code} ({self.station_type.value})>"


# ---------------------------------------------------------------------------
# RejectionReason
# ---------------------------------------------------------------------------

class RejectionReason(UUIDPrimaryKeyMixin, Base):
    """Pre-defined reasons a blade can be rejected."""

    __tablename__ = "rejection_reasons"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    blades: Mapped[list["Blade"]] = relationship(  # type: ignore[name-defined]
        "Blade",
        foreign_keys="[Blade.rejection_reason_id]",
        back_populates="rejection_reason",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<RejectionReason {self.code}>"


# ---------------------------------------------------------------------------
# WorkflowLog
# ---------------------------------------------------------------------------

class WorkflowLog(UUIDPrimaryKeyMixin, Base):
    """Immutable audit trail entry for each blade status transition."""

    __tablename__ = "workflow_logs"

    blade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[BladeStatus | None] = mapped_column(
        SAEnum(BladeStatus, name="bladestatus", create_type=False),
        nullable=True,  # Null on initial creation transition
    )
    to_status: Mapped[BladeStatus] = mapped_column(
        SAEnum(BladeStatus, name="bladestatus", create_type=False),
        nullable=False,
    )
    action_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )

    # Relationships
    blade: Mapped["Blade"] = relationship(  # type: ignore[name-defined]
        "Blade",
        back_populates="workflow_logs",
        lazy="noload",
    )
    action_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[action_by_id],
        lazy="selectin",
    )
    station: Mapped[Station | None] = relationship(
        "Station",
        foreign_keys=[station_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_workflow_logs_blade_ts", "blade_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowLog blade={self.blade_id} {self.from_status}->{self.to_status}>"


# Deferred imports to avoid circular references
from app.models.blade import Blade  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
