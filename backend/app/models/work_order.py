"""
WorkOrder model — the header/common-info record for a set of blades entered
together on the shop floor.

Table: work_orders

One WorkOrder is always exactly one blade_type and (once entry is complete)
exactly BLADES_PER_WORK_ORDER Blade rows. Replaces the old denormalized
batch_number + BatchGroup autofill-cache pattern.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BladeType


class WorkOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Common info entered once for a set of blades, before grid entry starts."""

    __tablename__ = "work_orders"

    work_order_number: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    shop_order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    part_number: Mapped[str] = mapped_column(String(64), nullable=False)
    blade_type: Mapped[BladeType] = mapped_column(
        SAEnum(BladeType, name="bladetype", create_type=False),
        nullable=False,
    )
    engine_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_hours: Mapped[str] = mapped_column(String(64), nullable=False)
    component_hours: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_entry_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    entry_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    entry_completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    blades: Mapped[list["Blade"]] = relationship(  # type: ignore[name-defined]
        "Blade",
        back_populates="work_order",
        lazy="noload",
        order_by="Blade.serial_number",
    )
    created_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    entry_completed_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[entry_completed_by_id],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<WorkOrder {self.work_order_number} [{self.blade_type.value}]>"


# Deferred imports
from app.models.user import User  # noqa: E402, F401
