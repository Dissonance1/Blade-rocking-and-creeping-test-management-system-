"""
Measurement schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from app.models.enums import MeasurementType
from app.schemas.base import BaseSchema


# ---------------------------------------------------------------------------
# HeightData sub-schema
# ---------------------------------------------------------------------------

class HeightData(BaseSchema):
    """
    Structured representation of the height-position measurement map stored
    as JSONB in the database.

    Keys are position labels (e.g. ``"H1"``, ``"H2"``); values are the
    measured readings in millimetres (or the relevant unit).

    Example::

        {"H1": 12.34, "H2": 11.95, "H3": 12.10, "H4": 12.05}
    """

    positions: dict[str, float] = Field(
        ...,
        description=(
            "Mapping of height-position label to measurement value. "
            "Keys must match the pattern Hn where n >= 1."
        ),
        examples=[{"H1": 12.34, "H2": 11.95, "H3": 12.10, "H4": 12.05}],
    )

    @field_validator("positions")
    @classmethod
    def validate_position_keys(cls, v: dict[str, float]) -> dict[str, float]:
        import re

        bad = [k for k in v if not re.fullmatch(r"H\d+", k)]
        if bad:
            raise ValueError(
                f"Invalid height-position keys: {bad}. "
                "Keys must match pattern H<n> (e.g. H1, H2, …)."
            )
        return v

    def to_jsonb(self) -> dict[str, float]:
        """Convert to the JSONB-ready dict stored in the database."""
        return self.positions


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class MeasurementCreate(BaseSchema):
    """
    Payload for recording a new measurement session against a blade.

    At least one numeric value (weight, static_moment, rocking, creep,
    or height_data) must be provided.
    """

    blade_id: uuid.UUID | None = Field(
        default=None,
        description="The blade being measured (optional — taken from URL if omitted)",
    )
    measurement_type: MeasurementType = Field(
        ..., description="Stage in the workflow this measurement corresponds to"
    )

    weight_grams: Decimal | None = Field(
        default=None,
        gt=0,
        description="Blade weight in grams",
        examples=[450.25],
    )
    static_moment_gcm: Decimal | None = Field(
        default=None,
        description="Static moment in gram-centimetres",
        examples=[1234.56],
    )
    rocking_value: Decimal | None = Field(
        default=None,
        description="Rocking test value (unit defined by procedure)",
        examples=[0.0023],
    )
    creep_value: Decimal | None = Field(
        default=None,
        description="Creep test value (unit defined by procedure)",
        examples=[0.0015],
    )
    height_data: dict[str, float] | None = Field(
        default=None,
        description="Height-position measurement map e.g. {'H1': 12.3, 'H2': 11.9}",
        examples=[{"H1": 12.34, "H2": 11.95, "H3": 12.10}],
    )
    station_id: uuid.UUID | None = Field(
        default=None,
        description="Station at which the measurement was taken (defaults to operator's station)",
    )
    notes: str | None = Field(
        default=None, max_length=4096, description="Free-text technician notes"
    )

    @model_validator(mode="after")
    def at_least_one_value(self) -> "MeasurementCreate":
        has_value = any(
            [
                self.weight_grams is not None,
                self.static_moment_gcm is not None,
                self.rocking_value is not None,
                self.creep_value is not None,
                self.height_data is not None,
            ]
        )
        if not has_value:
            raise ValueError(
                "At least one measurement value must be provided "
                "(weight_grams, static_moment_gcm, rocking_value, "
                "creep_value, or height_data)."
            )
        return self


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class MeasurementUpdate(BaseSchema):
    """Partial update — used by QA to annotate or approve a measurement."""

    weight_grams: Decimal | None = Field(default=None, gt=0)
    static_moment_gcm: Decimal | None = None
    rocking_value: Decimal | None = None
    creep_value: Decimal | None = None
    height_data: HeightData | None = None
    notes: str | None = Field(default=None, max_length=4096)
    is_approved: bool | None = None


class RockingCreepUpdate(BaseSchema):
    """
    Payload for the dedicated Rocking & Creep entry step (post slot-allocation).

    Blade-type rules (enforced in the endpoint after blade_type is resolved):
      LPTR  → both rocking_value and creep_value are required.
      HPTR  → rocking_value is required; creep_value must be omitted/null.
    """

    rocking_value: Decimal | None = Field(default=None, ge=0)
    creep_value: Decimal | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class MeasurementApproverInfo(BaseSchema):
    id: uuid.UUID
    username: str
    full_name: str | None = None


class MeasurementResponse(BaseSchema):
    """Full measurement record."""

    id: uuid.UUID
    blade_id: uuid.UUID
    measurement_type: MeasurementType

    weight_grams: Decimal | None = None
    static_moment_gcm: Decimal | None = None
    rocking_value: Decimal | None = None
    creep_value: Decimal | None = None
    height_data: dict[str, float] | None = Field(
        default=None,
        description="Raw JSONB dict from the database (position -> value)",
    )

    measured_by: MeasurementApproverInfo
    station_id: uuid.UUID | None = None
    measured_at: datetime
    notes: str | None = None

    is_approved: bool
    approved_by: MeasurementApproverInfo | None = None
    approved_at: datetime | None = None
