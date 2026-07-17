"""
Measurement schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.models.enums import MeasurementType
from app.schemas.base import BaseSchema


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class MeasurementCreate(BaseSchema):
    """
    Payload for recording a new measurement session against a blade.

    At least one numeric value (weight, static_moment, rocking, or creep)
    must be provided.
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
            ]
        )
        if not has_value:
            raise ValueError(
                "At least one measurement value must be provided "
                "(weight_grams, static_moment_gcm, rocking_value, "
                "or creep_value)."
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
    notes: str | None = Field(default=None, max_length=4096)
    is_approved: bool | None = None


class RockingCreepUpdate(BaseSchema):
    """
    Payload for the dedicated Rocking & Creep entry step (post slot-allocation).

    Only one physical gauge is shared between the Rocking and Creep columns,
    so operators feed whichever value is still missing whenever the gauge is
    free — the other value may already exist, arrive later, or come from a
    different session entirely.

    Blade-type rules (enforced in the endpoint after blade_type is resolved):
      LPTR  → at least one of rocking_value / creep_value must be provided;
              each is saved independently and the other may follow later.
      HPTR  → rocking_value is required; creep_value must be omitted/null
              (HPTR has no creep measurement).
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

    measured_by: MeasurementApproverInfo
    station_id: uuid.UUID | None = None
    measured_at: datetime
    notes: str | None = None

    is_approved: bool
    approved_by: MeasurementApproverInfo | None = None
    approved_at: datetime | None = None
