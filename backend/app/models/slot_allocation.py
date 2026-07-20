"""
SlotAllocation model.

Table: slot_allocations

Tracks which assembly slot a blade has been assigned to.
Only one allocation per blade may be active (is_active=True) at a time;
previous allocations are preserved for audit.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class SlotAllocation(UUIDPrimaryKeyMixin, Base):
    """
    Assignment of a blade to a numbered assembly slot.

    ``is_active`` is True for the current live assignment; historical
    reassignments keep their rows with is_active=False.  The
    ``previous_slot_number`` column on the replacement row records
    which slot was vacated, providing a lightweight audit trail without
    a separate history table.
    """

    __tablename__ = "slot_allocations"

    blade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_number: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="LPTR two-stage allocation stage (1 or 2) this row came from; null for HPTR/legacy rows",
    )

    # -----------------------------------------------------------------------
    # Who allocated and when
    # -----------------------------------------------------------------------
    allocated_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -----------------------------------------------------------------------
    # State
    # -----------------------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    # -----------------------------------------------------------------------
    # Balancing outcome
    # -----------------------------------------------------------------------
    balancing_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_balanced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unbalance_value: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )

    # -----------------------------------------------------------------------
    # Reassignment audit trail
    # -----------------------------------------------------------------------
    previous_slot_number: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    blade: Mapped["Blade"] = relationship(  # type: ignore[name-defined]
        "Blade",
        back_populates="slot_allocation",
        lazy="noload",
    )
    allocated_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[allocated_by_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_slot_allocations_blade_active", "blade_id", "is_active"),
        Index("ix_slot_allocations_slot_active", "slot_number", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<SlotAllocation blade={self.blade_id} "
            f"slot={self.slot_number} active={self.is_active}>"
        )


# Deferred imports
from app.models.blade import Blade  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
