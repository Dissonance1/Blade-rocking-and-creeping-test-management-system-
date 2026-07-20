"""
LptrBalancingCheck model.

Table: lptr_balancing_checks

Records the measured-unbalance outcome of physically installing a stage's
blades on the rotor (Step 6 / Step 10 of the LPTR slot allocation
workflow). Append-only log — a stage may be re-checked after a manual
correction, so there is no uniqueness constraint; the latest row per
(work_order_number, stage) is the current outcome.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

LPTR_UNBALANCE_LIMIT_G = 7.1


class LptrBalancingCheck(UUIDPrimaryKeyMixin, Base):
    """One measured-unbalance check for one stage of one LPTR work order."""

    __tablename__ = "lptr_balancing_checks"

    work_order_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    measured_unbalance: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    is_pass: Mapped[bool] = mapped_column(Boolean, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    __table_args__ = (
        CheckConstraint("stage IN (1, 2)", name="ck_lptr_balancing_checks_stage"),
        Index("ix_lptr_balancing_checks_wo_stage", "work_order_number", "stage"),
    )

    def __repr__(self) -> str:
        return (
            f"<LptrBalancingCheck work_order={self.work_order_number} "
            f"stage={self.stage} pass={self.is_pass}>"
        )


from app.models.user import User  # noqa: E402, F401
