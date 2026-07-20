"""
LptrManualCorrection model.

Table: lptr_manual_corrections

Traceability record for an operator-controlled manual action taken after
a balancing check fails (Step 7 of the LPTR slot allocation workflow):
re-arranging blades, a minor approved balancing adjustment, or a
manufacturer replacement blade request. The software never acts on these
automatically — it only records them.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import LptrCorrectionType


class LptrManualCorrection(UUIDPrimaryKeyMixin, Base):
    """One manual correction/replacement-request record for an LPTR work order."""

    __tablename__ = "lptr_manual_corrections"

    work_order_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    correction_type: Mapped[LptrCorrectionType] = mapped_column(
        SAEnum(LptrCorrectionType, name="lptrcorrectiontype", create_type=True),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    blade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="SET NULL"),
        nullable=True,
    )
    slot_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    recorded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    blade: Mapped["Blade | None"] = relationship(  # type: ignore[name-defined]
        "Blade", foreign_keys=[blade_id], lazy="selectin"
    )
    recorded_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[recorded_by_id], lazy="selectin"
    )

    __table_args__ = (
        Index("ix_lptr_manual_corrections_wo_stage", "work_order_number", "stage"),
    )

    def __repr__(self) -> str:
        return (
            f"<LptrManualCorrection work_order={self.work_order_number} "
            f"stage={self.stage} type={self.correction_type.value}>"
        )


from app.models.blade import Blade  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
