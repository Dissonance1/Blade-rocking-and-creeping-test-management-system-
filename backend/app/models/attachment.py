"""
Attachment model.

Table: attachments

Stores metadata for files uploaded against a blade (images, documents,
OCR scans). Binary content is stored externally; only the path/key is
kept here.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import AttachmentType


class Attachment(UUIDPrimaryKeyMixin, Base):
    """
    File attachment associated with a blade record.

    ``original_filename`` is the name supplied by the client.
    ``filename`` is the sanitised/unique name used on-disk.
    ``file_path`` is the storage path or object-storage key.
    """

    __tablename__ = "attachments"

    blade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Storage identity
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)

    # Provenance
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attachment_type: Mapped[AttachmentType] = mapped_column(
        SAEnum(AttachmentType, name="attachmenttype", create_type=True),
        nullable=False,
        index=True,
    )

    # OCR provenance — populated only for attachment_type=OCR_SCAN, captured
    # at scan time so the image, the OCR's raw detection, and (via blade_id)
    # the operator-confirmed ground truth can later be exported as a
    # matched training/eval dataset.
    ocr_field_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_detected_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    blade: Mapped["Blade"] = relationship(  # type: ignore[name-defined]
        "Blade",
        back_populates="attachments",
        lazy="noload",
    )
    uploaded_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[uploaded_by_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_attachments_blade_type", "blade_id", "attachment_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Attachment {self.original_filename} "
            f"[{self.attachment_type.value}] blade={self.blade_id}>"
        )


# Deferred imports
from app.models.blade import Blade  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
