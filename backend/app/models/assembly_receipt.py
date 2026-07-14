"""
AssemblyBatchReceipt — records when an Assembly operator marks a work
order as physically received at the 720 Hanger station.

One receipt per work order.  Created by ASSEMBLY_OPERATOR via
POST /api/v1/assembly/work-orders/{work_order_number}/receive.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import BLADES_PER_WORK_ORDER
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AssemblyBatchReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One receipt record per batch, created when Assembly confirms arrival."""

    __tablename__ = "assembly_batch_receipts"

    work_order_number: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    received_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    total_expected: Mapped[int] = mapped_column(
        Integer, nullable=False, default=BLADES_PER_WORK_ORDER,
        comment="Expected blade count for this work order (one blade type)"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── relationships ────────────────────────────────────────────────────────
    received_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[received_by_id], lazy="selectin"
    )
    station: Mapped["Station | None"] = relationship(  # type: ignore[name-defined]
        "Station", foreign_keys=[station_id], lazy="selectin"
    )
    blade_records: Mapped[list["AssemblyBladeRecord"]] = relationship(  # type: ignore[name-defined]
        "AssemblyBladeRecord",
        back_populates="batch_receipt",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AssemblyBatchReceipt work_order={self.work_order_number}>"


from app.models.user import User  # noqa: E402, F401
from app.models.workflow import Station  # noqa: E402, F401
from app.models.assembly_blade_record import AssemblyBladeRecord  # noqa: E402, F401
