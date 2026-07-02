"""
Pydantic I/O schemas for Assembly receipt workflow.

Endpoints: POST /assembly/batches/{id}/receive
           POST /assembly/blades/{id}/verify
           POST /assembly/blades/{id}/accept
           POST /assembly/blades/{id}/modify
           POST /assembly/blades/{id}/reject
           GET  /assembly/batches/{id}/receipt-status
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AssemblyVerificationStatus


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class BatchReceiveBody(BaseModel):
    station_id: uuid.UUID
    notes: str | None = None


class BladeVerifyBody(BaseModel):
    """Measurements captured by the Assembly operator for one blade."""

    station_id: uuid.UUID
    scanned_serial_number: str = Field(..., min_length=1, max_length=64)
    ocr_blade_number: str | None = None
    weight_at_assembly: float | None = Field(
        default=None, ge=0, description="Weight in grams from iScale i-04"
    )
    dti_readings: dict[str, float] | None = Field(
        default=None,
        description='DTI readings per position e.g. {"H1": 1.234, "H2": 1.235}',
    )


class BladeAcceptBody(BaseModel):
    station_id: uuid.UUID
    remarks: str | None = None


class BladeModifyBody(BaseModel):
    """Accept the blade but record that readings were corrected by the operator."""

    station_id: uuid.UUID
    modification_notes: str = Field(..., min_length=1)
    adjusted_weight: float | None = Field(default=None, ge=0)
    adjusted_dti_readings: dict[str, float] | None = None


class BladeRejectBody(BaseModel):
    station_id: uuid.UUID
    rejection_reason: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AssemblyReceiptResponse(BaseModel):
    id: uuid.UUID
    blade_id: uuid.UUID
    batch_group_id: uuid.UUID | None
    scanned_serial_number: str
    ocr_blade_number: str | None
    weight_at_assembly: float | None
    dti_readings: dict[str, float] | None
    oh_weight: float | None
    oh_dti_readings: dict[str, float] | None
    weight_variance_pct: float | None
    dti_max_variance_mm: float | None
    verification_status: AssemblyVerificationStatus
    rejection_reason: str | None
    modification_notes: str | None
    adjusted_weight: float | None
    adjusted_dti_readings: dict[str, float] | None
    verified_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BladeReceiptSummary(BaseModel):
    blade_id: uuid.UUID
    serial_number: str
    verification_status: AssemblyVerificationStatus
    receipt_id: uuid.UUID | None = None


class BatchReceiptStatusResponse(BaseModel):
    batch_id: uuid.UUID
    total_blades: int
    pending: int
    accepted: int
    modified: int
    rejected: int
    all_decided: bool
    blades: list[BladeReceiptSummary]
