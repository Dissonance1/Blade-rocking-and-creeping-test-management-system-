"""
LPTR two-stage slot allocation & balancing schemas.

Covers the three record types recorded during the LPTR workflow that are
not part of the generic SlotAllocation CRUD: the empty-rotor reading,
per-stage balancing checks, and manual correction/replacement-request
records.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.models.enums import LptrCorrectionType
from app.schemas.base import BaseSchema
from app.schemas.user import UserListItem

# ---------------------------------------------------------------------------
# Empty rotor reading
# ---------------------------------------------------------------------------


class EmptyRotorReadingRequest(BaseSchema):
    """Payload for recording the empty-rotor unbalance position + value."""

    unbalance_slot: int = Field(
        ..., ge=1, description="First-named slot of the reported unbalance position"
    )
    unbalance_value: Decimal = Field(..., gt=0, description="Measured unbalance (grams)")


class EmptyRotorReadingResponse(BaseSchema):
    id: uuid.UUID
    work_order_number: str
    unbalance_slot: int
    unbalance_value: Decimal
    recorded_by: UserListItem
    recorded_at: datetime


# ---------------------------------------------------------------------------
# Balancing check
# ---------------------------------------------------------------------------


class BalancingCheckRequest(BaseSchema):
    """Payload for recording a stage's measured-unbalance balancing check."""

    stage: int = Field(..., description="Which stage this check is for")
    measured_unbalance: Decimal = Field(..., ge=0, description="Measured unbalance (grams)")
    remarks: str | None = Field(default=None, max_length=2048)

    @field_validator("stage")
    @classmethod
    def stage_must_be_1_or_2(cls, v: int) -> int:
        if v not in (1, 2):
            raise ValueError("stage must be 1 or 2")
        return v


class BalancingCheckResponse(BaseSchema):
    id: uuid.UUID
    work_order_number: str
    stage: int
    measured_unbalance: Decimal
    is_pass: bool
    remarks: str | None = None
    recorded_by: UserListItem
    recorded_at: datetime


# ---------------------------------------------------------------------------
# Manual correction
# ---------------------------------------------------------------------------


class ManualCorrectionRequest(BaseSchema):
    """Payload for recording a manual correction / replacement-request."""

    stage: int = Field(..., description="Which stage this correction relates to")
    correction_type: LptrCorrectionType
    description: str = Field(..., min_length=3, max_length=4096)
    blade_id: uuid.UUID | None = Field(
        default=None, description="Optional reference to a specific blade"
    )
    slot_number: str | None = Field(default=None, max_length=32)

    @field_validator("stage")
    @classmethod
    def stage_must_be_1_or_2(cls, v: int) -> int:
        if v not in (1, 2):
            raise ValueError("stage must be 1 or 2")
        return v


class ManualCorrectionResponse(BaseSchema):
    id: uuid.UUID
    work_order_number: str
    stage: int
    correction_type: LptrCorrectionType
    description: str
    blade_id: uuid.UUID | None = None
    slot_number: str | None = None
    recorded_by: UserListItem
    recorded_at: datetime
