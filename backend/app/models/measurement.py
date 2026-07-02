"""
Measurement model.

Table: measurements

Stores weight, static moment, rocking value, creep value, and
height-position data (JSONB) for each measurement session on a blade.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import MeasurementType


class Measurement(UUIDPrimaryKeyMixin, Base):
    """
    A single measurement session for a blade.

    ``height_data`` is stored as JSONB with the shape::

        {"H1": 12.3, "H2": 11.9, "H3": 12.1, ...}

    Keys are height-position labels; values are floating-point readings.
    """

    __tablename__ = "measurements"

    blade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    measurement_type: Mapped[MeasurementType] = mapped_column(
        SAEnum(MeasurementType, name="measurementtype", create_type=True),
        nullable=False,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Core measurement values
    # -----------------------------------------------------------------------
    weight_grams: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    static_moment_gcm: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    rocking_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    creep_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    # -----------------------------------------------------------------------
    # Height-position data  {"H1": 12.3, "H2": 11.9, ...}
    # -----------------------------------------------------------------------
    height_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)

    # -----------------------------------------------------------------------
    # Provenance
    # -----------------------------------------------------------------------
    measured_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True,
    )
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -----------------------------------------------------------------------
    # QA approval
    # -----------------------------------------------------------------------
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    blade: Mapped["Blade"] = relationship(  # type: ignore[name-defined]
        "Blade",
        back_populates="measurements",
        lazy="noload",
    )
    measured_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[measured_by_id],
        lazy="selectin",
    )
    approved_by: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[approved_by_id],
        lazy="selectin",
    )
    station: Mapped["Station | None"] = relationship(  # type: ignore[name-defined]
        "Station",
        foreign_keys=[station_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_measurements_blade_type", "blade_id", "measurement_type"),
        Index("ix_measurements_measured_at", "measured_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Measurement blade={self.blade_id} "
            f"type={self.measurement_type.value} at={self.measured_at}>"
        )


# Deferred imports
from app.models.blade import Blade  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
from app.models.workflow import Station  # noqa: E402, F401
