"""
Blade schemas — create, update, read, search, and workflow-transition payloads.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.models.enums import BladeStatus, BladeType
from app.schemas.base import BaseSchema
from app.schemas.measurement import MeasurementResponse
from app.schemas.user import UserListItem


# ---------------------------------------------------------------------------
# Sub-schemas embedded in BladeResponse
# ---------------------------------------------------------------------------

class StationSummary(BaseSchema):
    id: uuid.UUID
    name: str
    code: str


class RejectionReasonSummary(BaseSchema):
    id: uuid.UUID
    code: str
    description: str


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class BladeUpdate(BaseSchema):
    """
    Partial update for a blade record.

    Only supply fields that should change; all are optional.
    Status transitions must go through BladeStatusUpdate to ensure
    workflow-log creation.
    """

    melt_number: str | None = Field(default=None, max_length=64)
    work_order_number: str | None = Field(default=None, max_length=64)
    shop_order_number: str | None = Field(default=None, max_length=64)
    part_number: str | None = Field(default=None, max_length=64)
    nomenclature: str | None = Field(default=None, max_length=128)
    engine_number: str | None = Field(default=None, max_length=64)
    running_hours: Decimal | None = Field(default=None, ge=0)
    engine_hours: str | None = Field(default=None, max_length=64)
    component_hours: str | None = Field(default=None, max_length=64)
    assigned_to_id: uuid.UUID | None = None

    # OCR correction (operator can override mismatched OCR fields)
    ocr_mismatch_notes: str | None = None


# ---------------------------------------------------------------------------
# Status transition
# ---------------------------------------------------------------------------

class BladeStatusUpdate(BaseSchema):
    """
    Payload for transitioning a blade to a new workflow status.

    ``remarks`` are appended to the WorkflowLog entry created alongside
    the transition.
    """

    status: BladeStatus = Field(
        ..., description="The target status the blade should transition to"
    )
    remarks: str | None = Field(
        default=None,
        max_length=2048,
        description="Optional operator notes for this transition",
    )
    station_id: uuid.UUID | None = Field(
        default=None,
        description="Override destination station; defaults to the current user's station",
    )


class SendToAssemblyRequest(BaseSchema):
    """
    Payload for the dedicated 'Send to Assembly' action.

    This triggers a SENT_TO_ASSEMBLY status transition, notifies the
    Assembly team, and locks further OH measurements.
    """

    remarks: str | None = Field(
        default=None,
        max_length=2048,
        description="Optional handover notes from OH operator to Assembly team",
        examples=["All measurements within spec. Blade cleaned and tagged."],
    )
    target_station_id: uuid.UUID | None = Field(
        default=None,
        description="Assembly station to route the blade to (optional override)",
    )


class RejectBladeRequest(BaseSchema):
    """Payload for rejecting a blade."""

    rejection_reason_id: uuid.UUID = Field(
        ..., description="Pre-defined rejection reason ID"
    )
    rejection_notes: str | None = Field(
        default=None,
        max_length=4096,
        description="Detailed rejection notes (will appear in reports)",
    )


# ---------------------------------------------------------------------------
# Search / filter params
# ---------------------------------------------------------------------------

class BladeSearchParams(BaseSchema):
    """
    Query-parameter schema for the blade list / search endpoint.

    All fields are optional.  Non-null fields are combined with AND logic.
    """

    model_config = BaseSchema.model_config.copy()  # type: ignore[assignment]

    serial_number: str | None = Field(
        default=None,
        description="Partial or exact serial number (case-insensitive ILIKE)",
    )
    melt_number: str | None = Field(
        default=None, description="Partial or exact melt number"
    )
    work_order_number: str | None = None
    part_number: str | None = None
    status: BladeStatus | None = Field(
        default=None, description="Filter by exact blade status"
    )
    station_id: uuid.UUID | None = Field(
        default=None, description="Filter by current station"
    )
    assigned_to_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    ocr_mismatch_only: bool = Field(
        default=False, description="If true, return only blades with OCR mismatches"
    )
    date_from: date | None = Field(
        default=None, description="Filter blades created on or after this date (UTC)"
    )
    date_to: date | None = Field(
        default=None, description="Filter blades created on or before this date (UTC)"
    )
    # Pagination
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    sort_by: str = Field(
        default="created_at",
        description="Column name to sort by",
        examples=["created_at", "serial_number", "status"],
    )
    sort_desc: bool = Field(default=True, description="Sort descending if true")

    @model_validator(mode="after")
    def date_range_valid(self) -> "BladeSearchParams":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class BladeListItem(BaseSchema):
    """Lightweight summary used in paginated list responses."""

    id: uuid.UUID
    serial_number: str
    melt_number: str | None = None
    work_order_number: str | None = None
    shop_order_number: str | None = None
    part_number: str | None = None
    nomenclature: str | None = None
    engine_number: str | None = None
    running_hours: float | None = None
    status: BladeStatus
    ocr_mismatch_flag: bool
    current_station: StationSummary | None = None
    assigned_to: UserListItem | None = None
    created_at: datetime
    updated_at: datetime
    blade_type: BladeType = BladeType.LPTR
    # Latest INITIAL measurement values (populated by list endpoint)
    weight_grams: float | None = None
    static_moment_gcm: float | None = None


class BladeResponse(BaseSchema):
    """Full blade record returned by GET /blades/{id}."""

    id: uuid.UUID
    serial_number: str
    melt_number: str | None = None
    work_order_number: str | None = None
    shop_order_number: str | None = None
    part_number: str | None = None
    nomenclature: str | None = None
    engine_number: str | None = None
    running_hours: Decimal | None = None
    engine_hours: str | None = None
    component_hours: str | None = None

    blade_type: BladeType = BladeType.LPTR
    status: BladeStatus
    current_station: StationSummary | None = None
    created_by: UserListItem
    assigned_to: UserListItem | None = None

    # OCR
    ocr_melt_number: str | None = None
    ocr_mismatch_flag: bool
    ocr_mismatch_notes: str | None = None

    # Rejection
    rejection_reason: RejectionReasonSummary | None = None
    rejection_notes: str | None = None

    measurements: list[MeasurementResponse] | None = None

    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
