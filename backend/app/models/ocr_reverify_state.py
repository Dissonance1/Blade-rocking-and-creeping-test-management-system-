"""
OCRReverifyState model.

Table: ocr_reverify_state

Tracks, per OCR-scan attachment, how many consecutive weekly re-verification
passes the *currently deployed* model has gotten right in a row. Once an
image proves stable (see consecutive_correct threshold in
finetune/reverify_dataset.py), it's skipped in future weekly re-checks to
keep the growing corpus affordable to re-verify — except on a periodic full
sweep, which ignores this and re-checks everything.

One row per attachment (1:1) — the primary key IS the attachment's id.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OCRReverifyState(Base):
    """Per-attachment re-verification history for the OCR retraining pipeline."""

    __tablename__ = "ocr_reverify_state"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attachments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    consecutive_correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_result_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<OCRReverifyState attachment={self.attachment_id} "
            f"consecutive_correct={self.consecutive_correct}>"
        )
