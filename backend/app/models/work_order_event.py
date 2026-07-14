"""
WorkOrderEvent model — records Assembly-initiated actions on a work order.

RECEIVED_BY_ASSEMBLY, ACCEPTED, REJECTED, MODIFIED are persisted here.
CREATED and SENT_TO_ASSEMBLY statuses are inferred from blade data.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import BatchEventType


class WorkOrderEvent(UUIDPrimaryKeyMixin, Base):
    """Immutable record of an Assembly action on a work order."""

    __tablename__ = "work_order_events"

    work_order_number: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    event_type: Mapped[BatchEventType] = mapped_column(
        SAEnum(BatchEventType, name="batcheventtype", create_type=True),
        nullable=False,
    )
    action_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    action_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[action_by_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_work_order_events_wo_ts", "work_order_number", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<WorkOrderEvent {self.work_order_number} {self.event_type.value}>"


from app.models.user import User  # noqa: E402, F401
