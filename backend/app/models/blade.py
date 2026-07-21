"""
Blade model — the central entity of the system.

Table: blades
"""

import uuid

from sqlalchemy import (
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, SoftDeleteMixin
from app.models.enums import BladeStatus, BladeType


class Blade(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """
    Represents a single turbine blade moving through the overhaul
    and rocking/creep test workflow.
    """

    __tablename__ = "blades"

    # -----------------------------------------------------------------------
    # Identity / traceability fields
    # -----------------------------------------------------------------------
    # Positional S.No within its Work Order — server-assigned "01".."90"
    # (zero-padded so text sort order matches numeric order), never manually
    # entered or OCR'd. Unique per work_order_id, not globally.
    serial_number: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    melt_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    work_order_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    shop_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_hours: Mapped[str | None] = mapped_column(String(64), nullable=True)
    component_hours: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -----------------------------------------------------------------------
    # Blade type
    # -----------------------------------------------------------------------
    blade_type: Mapped[BladeType] = mapped_column(
        SAEnum(BladeType, name="bladetype", create_type=True),
        nullable=False,
        default=BladeType.LPTR,
        server_default="LPTR",
    )

    # -----------------------------------------------------------------------
    # Status & routing
    # -----------------------------------------------------------------------
    status: Mapped[BladeStatus] = mapped_column(
        SAEnum(BladeStatus, name="bladestatus", create_type=True),
        nullable=False,
        default=BladeStatus.CREATED,
        index=True,
    )
    current_station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # -----------------------------------------------------------------------
    # OCR verification fields
    # -----------------------------------------------------------------------
    ocr_melt_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocr_mismatch_flag: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    ocr_mismatch_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -----------------------------------------------------------------------
    # Rejection fields
    # -----------------------------------------------------------------------
    rejection_reason_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rejection_reasons.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    work_order: Mapped["WorkOrder"] = relationship(  # type: ignore[name-defined]
        "WorkOrder",
        foreign_keys=[work_order_id],
        back_populates="blades",
        lazy="selectin",
    )
    current_station: Mapped["Station | None"] = relationship(  # type: ignore[name-defined]
        "Station",
        foreign_keys=[current_station_id],
        back_populates="blades",
        lazy="selectin",
    )
    created_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    assigned_to: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[assigned_to_id],
        lazy="selectin",
    )
    rejection_reason: Mapped["RejectionReason | None"] = relationship(  # type: ignore[name-defined]
        "RejectionReason",
        foreign_keys=[rejection_reason_id],
        back_populates="blades",
        lazy="selectin",
    )
    measurements: Mapped[list["Measurement"]] = relationship(  # type: ignore[name-defined]
        "Measurement",
        back_populates="blade",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    slot_allocation: Mapped["SlotAllocation | None"] = relationship(  # type: ignore[name-defined]
        "SlotAllocation",
        back_populates="blade",
        lazy="noload",
        uselist=False,
        primaryjoin="and_(SlotAllocation.blade_id == Blade.id, SlotAllocation.is_active == True)",
    )
    workflow_logs: Mapped[list["WorkflowLog"]] = relationship(  # type: ignore[name-defined]
        "WorkflowLog",
        back_populates="blade",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="WorkflowLog.timestamp",
    )
    attachments: Mapped[list["Attachment"]] = relationship(  # type: ignore[name-defined]
        "Attachment",
        back_populates="blade",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list["Notification"]] = relationship(  # type: ignore[name-defined]
        "Notification",
        back_populates="blade",
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_blades_status_station", "status", "current_station_id"),
        Index("ix_blades_deleted_at", "deleted_at"),
        Index("ix_blades_created_by", "created_by_id"),
        UniqueConstraint(
            "work_order_id", "serial_number",
            name="uq_blade_workorder_serial",
        ),
    )

    @property
    def is_rejected(self) -> bool:
        return self.status == BladeStatus.REJECTED

    @property
    def is_completed(self) -> bool:
        return self.status == BladeStatus.COMPLETED

    def __repr__(self) -> str:
        return f"<Blade {self.serial_number} [{self.status.value}]>"


# Deferred imports
from app.models.work_order import WorkOrder  # noqa: E402, F401
from app.models.workflow import Station, RejectionReason, WorkflowLog  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
from app.models.measurement import Measurement  # noqa: E402, F401
from app.models.slot_allocation import SlotAllocation  # noqa: E402, F401
from app.models.attachment import Attachment  # noqa: E402, F401
from app.models.notification import Notification  # noqa: E402, F401
