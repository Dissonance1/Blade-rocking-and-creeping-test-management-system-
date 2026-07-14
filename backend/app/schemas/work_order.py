"""
WorkOrder schemas — grid-entry create/resume/autosave/complete payloads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.enums import BladeType
from app.schemas.base import BaseSchema


# ---------------------------------------------------------------------------
# Create ("common info" / Phase A — Start Blade Entry)
# ---------------------------------------------------------------------------

class WorkOrderCreate(BaseSchema):
    """Common info entered once, before the 90-row grid is scaffolded."""

    work_order_number: str = Field(..., min_length=1, max_length=64, examples=["WO-2024-0099"])
    shop_order_number: str = Field(..., min_length=1, max_length=64, examples=["SO-0456"])
    part_number: str = Field(..., min_length=1, max_length=64, examples=["PT-JT9D-1A"])
    blade_type: BladeType = Field(..., description="HPTR or LPTR — fixed for all 90 blades")
    engine_number: str | None = Field(
        default=None,
        max_length=64,
        description="Append _1, _2, ... for repeat visits of the same engine",
        examples=["ENG-20240012", "ENG-20240012_1"],
    )
    engine_hours: str = Field(
        ..., max_length=64, description="Engine hours in HH:MM:SS format"
    )
    component_hours: str | None = Field(
        default=None,
        max_length=64,
        description="Component hours in HH:MM:SS format; defaults to engine_hours if not set",
    )

    @field_validator("work_order_number", "shop_order_number", "part_number")
    @classmethod
    def strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


# ---------------------------------------------------------------------------
# Autosave (per-row)
# ---------------------------------------------------------------------------

class WorkOrderRowUpdate(BaseSchema):
    """
    Idempotent per-row autosave payload for ``PUT
    /work-orders/{work_order_number}/rows/{s_no}``.

    Only supplied fields are applied. ``weight_grams``/``static_moment_gcm``
    are always recomputed server-side from ``raw_weight`` and are never
    accepted from the client.
    """

    melt_number: str | None = Field(default=None, max_length=64)
    ocr_melt_number: str | None = Field(default=None, max_length=64)
    ocr_mismatch_flag: bool | None = None
    ocr_mismatch_notes: str | None = None
    raw_weight: float | None = Field(
        default=None, ge=0, description="Raw scale reading in kg"
    )


# ---------------------------------------------------------------------------
# Response: one grid row
# ---------------------------------------------------------------------------

class WorkOrderRowResponse(BaseSchema):
    s_no: int
    blade_id: uuid.UUID
    melt_number: str | None = None
    ocr_melt_number: str | None = None
    ocr_mismatch_flag: bool = False
    raw_weight: float | None = None
    weight_grams: float | None = None
    static_moment_gcm: float | None = None
    is_complete: bool


# ---------------------------------------------------------------------------
# Response: resume/detail
# ---------------------------------------------------------------------------

class WorkOrderDetailResponse(BaseSchema):
    work_order_number: str
    shop_order_number: str
    part_number: str
    blade_type: BladeType
    engine_number: str | None = None
    engine_hours: str
    component_hours: str | None = None
    is_entry_complete: bool
    entry_completed_at: datetime | None = None
    rows: list[WorkOrderRowResponse]
    first_incomplete_s_no: int | None = Field(
        default=None,
        description="Lowest S.No still incomplete, or null if all rows are complete",
    )


# ---------------------------------------------------------------------------
# Response: complete
# ---------------------------------------------------------------------------

class WorkOrderCompleteResponse(BaseSchema):
    work_order_number: str
    status: str
    blade_ids: list[uuid.UUID]
    completed_at: datetime
