"""
Assembly station schemas — batch receipt, per-blade verification, set-making.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.models.enums import AssemblyVerificationStatus, BladeStatus, BladeType
from app.schemas.base import BaseSchema


# ---------------------------------------------------------------------------
# Batch receipt
# ---------------------------------------------------------------------------

class BatchReceiveRequest(BaseSchema):
    station_id: uuid.UUID | None = Field(default=None, description="Assembly station UUID (optional)")
    notes: str | None = Field(default=None, max_length=512)


class BatchReceiptResponse(BaseSchema):
    id: uuid.UUID
    work_order_number: str
    received_at: datetime
    received_by_id: uuid.UUID
    station_id: uuid.UUID | None
    total_expected: int
    notes: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Batch progress summary
# ---------------------------------------------------------------------------

class BatchProgressResponse(BaseSchema):
    work_order_number: str
    total_expected: int
    assembly_received: int    # blades with status ASSEMBLY_RECEIVED
    assembly_verified: int    # accepted + modified
    assembly_rejected: int    # rejected at Assembly
    pending: int              # still ASSEMBLY_RECEIVED, not yet scanned
    set_making_ready: bool    # True when assembly_verified == total_expected

    # HPTR never leaves OH, so its "set making ready" gate is independent of
    # the Assembly-side fields above: ready once every HPTR blade in the
    # batch has reached MEASUREMENTS_RECORDED.
    hptr_total: int = 0
    hptr_measurements_recorded: int = 0
    hptr_set_making_ready: bool = False


# ---------------------------------------------------------------------------
# Per-blade verification submission
# ---------------------------------------------------------------------------

class BladeVerifyRequest(BaseSchema):
    """
    Payload sent when Assembly operator scans a blade.

    All measurement fields are optional — operator may supply what hardware
    has captured so far and call the endpoint again after DTI readings arrive.
    """
    qr_scan_result: str | None = Field(
        default=None, max_length=256,
        description="Raw text decoded from QR code on the blade"
    )
    ocr_blade_number: str | None = Field(
        default=None, max_length=64,
        description="Blade number captured by OCR camera at Assembly"
    )
    assembly_weight: float | None = Field(
        default=None, ge=0,
        description="Weight read from iScale at Assembly (grams)"
    )
    assembly_dti_h1: float | None = Field(default=None)
    assembly_dti_h2: float | None = Field(default=None)
    assembly_dti_h3: float | None = Field(default=None)
    assembly_dti_h4: float | None = Field(default=None)


class BladeAcceptRequest(BaseSchema):
    """Accept a blade, optionally overriding readings with corrected values."""
    notes: str | None = Field(default=None, max_length=512)
    # Override fields — only provided when operator corrects a reading
    assembly_weight: float | None = Field(default=None, ge=0)
    assembly_dti_h1: float | None = Field(default=None)
    assembly_dti_h2: float | None = Field(default=None)
    assembly_dti_h3: float | None = Field(default=None)
    assembly_dti_h4: float | None = Field(default=None)


class BladeRejectRequest(BaseSchema):
    notes: str = Field(..., min_length=1, max_length=512,
                       description="Reason for rejection (required)")


class AssemblyBladeRecordResponse(BaseSchema):
    id: uuid.UUID
    blade_id: uuid.UUID
    batch_receipt_id: uuid.UUID
    # scan
    qr_scan_result: str | None
    ocr_blade_number: str | None
    # Assembly measurements
    assembly_weight: float | None
    assembly_dti_h1: float | None
    assembly_dti_h2: float | None
    assembly_dti_h3: float | None
    assembly_dti_h4: float | None
    # OH snapshot
    oh_weight: float | None
    oh_dti_h1: float | None
    oh_dti_h2: float | None
    oh_dti_h3: float | None
    oh_dti_h4: float | None
    # delta
    weight_delta: float | None
    # decision
    status: AssemblyVerificationStatus
    verification_notes: str | None
    verified_by_id: uuid.UUID | None
    verified_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Validation result (returned by /verify before accept/reject decision)
# ---------------------------------------------------------------------------

class FieldValidation(BaseSchema):
    field: str
    oh_value: float | None
    assembly_value: float | None
    delta: float | None
    within_tolerance: bool
    tolerance_used: float | None


class BladeVerifyResponse(BaseSchema):
    record: AssemblyBladeRecordResponse
    # Identity check
    serial_number_match: bool
    ocr_match: bool
    # Field-level validation
    validations: list[FieldValidation]
    all_within_tolerance: bool
    # Suggested action
    suggested_action: str   # "ACCEPT" | "REVIEW" | "REJECT"


# ---------------------------------------------------------------------------
# Set-making trigger
# ---------------------------------------------------------------------------

class StartSetMakingRequest(BaseSchema):
    notes: str | None = Field(default=None, max_length=512)


class SetMakingResponse(BaseSchema):
    work_order_number: str
    status: str   # "INITIATED"
    total_blades: int
    message: str


# ---------------------------------------------------------------------------
# OH sync schemas (used by Assembly to pull data from OH PC over LAN)
# ---------------------------------------------------------------------------

class OHBladeSnapshot(BaseSchema):
    """Minimal blade snapshot exposed by OH /sync/blades endpoint."""
    id: uuid.UUID
    serial_number: str
    blade_type: BladeType
    status: BladeStatus
    weight: float | None       # latest measurement weight
    dti_h1: float | None
    dti_h2: float | None
    dti_h3: float | None
    dti_h4: float | None
    part_number: str | None
    work_order_number: str | None
    created_at: datetime


class OHSyncResponse(BaseSchema):
    station_id: str
    station_name: str
    synced_at: datetime
    blade_count: int
    blades: list[OHBladeSnapshot]
