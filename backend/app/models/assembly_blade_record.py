"""
AssemblyBladeRecord — per-blade verification record at the Assembly station.

Created when the Assembly operator scans a blade QR code and submits
the OCR / weight / DTI readings captured at 720 Hanger.  Stores both
the Assembly-measured values and a snapshot of the OH-recorded values
for side-by-side comparison.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AssemblyVerificationStatus


class AssemblyBladeRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Verification record for one blade at Assembly.

    ``oh_*`` columns are a snapshot of what OH recorded; they never change.
    ``assembly_*`` columns hold what was measured at 720 Hanger.
    ``status`` reflects the operator's decision: ACCEPTED / MODIFIED / REJECTED.
    """

    __tablename__ = "assembly_blade_records"

    # ── foreign keys ─────────────────────────────────────────────────────────
    blade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assembly_batch_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── scan / OCR fields ─────────────────────────────────────────────────────
    qr_scan_result: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
        comment="Raw text from QR code scan"
    )
    ocr_blade_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="Blade number read by OCR camera at Assembly"
    )

    # ── Assembly-measured values ──────────────────────────────────────────────
    assembly_weight: Mapped[float | None] = mapped_column(
        Numeric(12, 4), nullable=True,
        comment="Weight captured at Assembly iScale (grams)"
    )

    # ── OH snapshot (captured at receipt time) ────────────────────────────────
    oh_weight: Mapped[float | None] = mapped_column(
        Numeric(12, 4), nullable=True,
        comment="Weight recorded at OH (snapshot)"
    )

    # ── deltas (computed and stored for quick filtering) ─────────────────────
    weight_delta: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="assembly_weight - oh_weight"
    )

    # ── operator decision ─────────────────────────────────────────────────────
    status: Mapped[AssemblyVerificationStatus] = mapped_column(
        SAEnum(AssemblyVerificationStatus, name="assemblyverificationstatus", create_type=True),
        nullable=False,
        default=AssemblyVerificationStatus.PENDING,
        index=True,
    )
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── relationships ─────────────────────────────────────────────────────────
    blade: Mapped["Blade"] = relationship(  # type: ignore[name-defined]
        "Blade", foreign_keys=[blade_id], lazy="selectin"
    )
    batch_receipt: Mapped["AssemblyBatchReceipt"] = relationship(  # type: ignore[name-defined]
        "AssemblyBatchReceipt",
        foreign_keys=[batch_receipt_id],
        back_populates="blade_records",
        lazy="selectin",
    )
    verified_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[verified_by_id], lazy="selectin"
    )

    __table_args__ = (
        Index("ix_assembly_blade_records_blade_receipt", "blade_id", "batch_receipt_id"),
    )

    def __repr__(self) -> str:
        return f"<AssemblyBladeRecord blade={self.blade_id} status={self.status.value}>"


from app.models.blade import Blade  # noqa: E402, F401
from app.models.assembly_receipt import AssemblyBatchReceipt  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
