"""
LptrEmptyRotorReading model.

Table: lptr_empty_rotor_readings

The empty-rotor balancing reading taken before any LPTR blades are
installed (Step 1 of the LPTR slot allocation workflow). One reading per
work order — it is the input the stage-1 target-weight calculation
depends on, so it must be recorded before stage-1 allocation can run.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class LptrEmptyRotorReading(UUIDPrimaryKeyMixin, Base):
    """Empty-rotor unbalance position + value for one LPTR work order."""

    __tablename__ = "lptr_empty_rotor_readings"

    work_order_number: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    unbalance_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    unbalance_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)

    recorded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recorded_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[recorded_by_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<LptrEmptyRotorReading work_order={self.work_order_number} "
            f"slot={self.unbalance_slot}>"
        )


from app.models.user import User  # noqa: E402, F401
