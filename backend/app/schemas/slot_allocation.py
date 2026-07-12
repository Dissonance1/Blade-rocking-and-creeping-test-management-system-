"""
Slot allocation schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.models.enums import BladeType
from app.schemas.base import BaseSchema
from app.schemas.user import UserListItem


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SlotAssignRequest(BaseSchema):
    """
    Payload for assigning a blade to an assembly slot.

    ``slot_number`` is the human-readable slot identifier stamped on the
    rotor jig (e.g. "A-12", "B-03").  ``position`` is the ordinal
    integer used for sorting/balancing algorithms.
    """

    blade_id: uuid.UUID = Field(..., description="UUID of the blade to assign")
    slot_number: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Slot identifier on the assembly jig",
        examples=["A-12", "B-03"],
    )
    position: int | None = Field(
        default=None, ge=1, description="Ordinal position within the rotor (1-based)"
    )
    group_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional balancing group identifier",
        examples=["GROUP-1"],
    )
    remarks: str | None = Field(
        default=None, max_length=2048, description="Optional technician remarks"
    )

    @field_validator("slot_number")
    @classmethod
    def slot_number_upper(cls, v: str) -> str:
        return v.strip().upper()


class SlotReassignRequest(BaseSchema):
    """
    Payload for moving a blade from its current slot to a new one.

    The previous slot allocation row is deactivated (is_active=False)
    and a new row is created with ``previous_slot_number`` set for
    audit purposes.
    """

    blade_id: uuid.UUID = Field(..., description="UUID of the blade to reassign")
    new_slot_number: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="New target slot identifier",
        examples=["C-07"],
    )
    new_position: int | None = Field(
        default=None, ge=1, description="New ordinal position in the rotor"
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=2048,
        description="Mandatory reason for the reassignment (audit trail)",
    )

    @field_validator("new_slot_number")
    @classmethod
    def new_slot_upper(cls, v: str) -> str:
        return v.strip().upper()


class SlotSwapRequest(BaseSchema):
    """
    Payload for swapping the blades occupying two already-saved slots.

    Used to correct a blade that fails physical balancing testing after
    save, where both slots are occupied so a simple reassign (which
    requires an empty target) doesn't apply. Both allocations are
    deactivated and replaced with two new rows carrying the swapped slot
    numbers; both are reset to unbalanced since they're now in new physical
    positions and must be re-tested.
    """

    slot_number_a: str = Field(..., min_length=1, max_length=32)
    slot_number_b: str = Field(..., min_length=1, max_length=32)
    blade_type: BladeType
    batch_number: str = Field(
        ...,
        description="Scopes the lookup to this batch's allocations only",
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=2048,
        description="Mandatory reason for the swap (audit trail)",
    )

    @field_validator("slot_number_a", "slot_number_b")
    @classmethod
    def slot_number_upper(cls, v: str) -> str:
        return v.strip().upper()


class BalancingUpdateRequest(BaseSchema):
    """
    Payload for recording the balancing outcome of a slot allocation.
    """

    is_balanced: bool = Field(..., description="Whether the blade is now balanced")
    unbalance_value: Decimal | None = Field(
        default=None,
        description="Residual unbalance value (if not fully balanced)",
    )
    balancing_remarks: str | None = Field(
        default=None, max_length=2048
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SlotAllocationResponse(BaseSchema):
    """Full slot allocation record."""

    id: uuid.UUID
    blade_id: uuid.UUID
    slot_number: str
    position: int | None = None
    group_id: str | None = None

    allocated_by: UserListItem
    allocated_at: datetime

    is_active: bool
    balancing_remarks: str | None = None
    is_balanced: bool
    unbalance_value: Decimal | None = None

    previous_slot_number: str | None = Field(
        default=None,
        description="Slot number before the last reassignment (audit trail)",
    )
