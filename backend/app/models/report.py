"""
Report model.

Table: reports

Tracks asynchronously-generated PDF/Excel reports and their lifecycle.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ReportType, ReportStatus


class Report(UUIDPrimaryKeyMixin, Base):
    """
    Metadata record for a generated report file.

    The actual file is stored on disk / object storage; ``file_path``
    contains the path or object key needed to retrieve it.
    ``filter_params`` captures the query parameters used so the same
    report can be reproduced or audited later.
    """

    __tablename__ = "reports"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[ReportType] = mapped_column(
        SAEnum(ReportType, name="reporttype", create_type=True),
        nullable=False,
    )
    status: Mapped[ReportStatus] = mapped_column(
        SAEnum(ReportStatus, name="reportstatus", create_type=True),
        nullable=False,
        default=ReportStatus.PENDING,
        index=True,
    )

    generated_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Storage
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # The JSON filters / parameters used to generate this report
    filter_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)

    # Populated if status == FAILED
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    generated_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[generated_by_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_reports_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Report {self.name} [{self.status.value}]>"


# Deferred imports
from app.models.user import User  # noqa: E402, F401
