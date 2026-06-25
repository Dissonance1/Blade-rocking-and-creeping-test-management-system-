"""
BatchGroup model — stores batch number → work order / part / engine / nomenclature mappings.
Allows auto-fill of identity fields when a known batch number is re-used.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BatchGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "batch_groups"

    batch_number: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    work_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nomenclature: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:
        return f"<BatchGroup {self.batch_number}>"
