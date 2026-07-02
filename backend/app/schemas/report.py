"""
Report schemas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field, model_validator

from app.models.enums import BladeStatus, ReportStatus, ReportType
from app.schemas.base import BaseSchema
from app.schemas.user import UserListItem


# ---------------------------------------------------------------------------
# Filter sub-schema (embedded in ReportGenerateRequest and ReportResponse)
# ---------------------------------------------------------------------------

class ReportFilterParams(BaseSchema):
    """
    Serialisable filter criteria stored in the report's ``filter_params``
    JSONB column so the same report can be reproduced later.
    """

    date_from: date | None = Field(
        default=None, description="Include blades created on or after this date"
    )
    date_to: date | None = Field(
        default=None, description="Include blades created on or before this date"
    )
    status: list[BladeStatus] | None = Field(
        default=None, description="Filter by one or more blade statuses"
    )
    station_ids: list[uuid.UUID] | None = Field(
        default=None, description="Filter by one or more stations"
    )
    serial_number: str | None = Field(
        default=None, description="Partial serial number filter (ILIKE)"
    )
    part_number: str | None = None
    include_rejected: bool = Field(
        default=True, description="Whether to include rejected blades"
    )

    @model_validator(mode="after")
    def date_range_valid(self) -> "ReportFilterParams":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


# ---------------------------------------------------------------------------
# Generate request
# ---------------------------------------------------------------------------

class ReportGenerateRequest(BaseSchema):
    """
    Payload for requesting a new report.

    Report generation is asynchronous; the endpoint returns a
    ``ReportResponse`` with ``status=PENDING`` immediately, and the
    actual file is available once ``status=READY``.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable report name",
        examples=["Monthly Blade Summary – May 2026"],
    )
    report_type: ReportType = Field(
        ..., description="Output format: PDF or EXCEL"
    )
    filters: ReportFilterParams = Field(
        default_factory=ReportFilterParams,
        description="Filter criteria applied when generating the report",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class ReportResponse(BaseSchema):
    """Full report metadata record."""

    id: uuid.UUID
    name: str
    report_type: ReportType
    status: ReportStatus

    generated_by: UserListItem | None = None
    created_at: datetime
    completed_at: datetime | None = None

    file_path: str | None = Field(
        default=None,
        description="Storage path/key of the generated file (available when status=READY)",
    )
    file_size_bytes: int | None = None
    filter_params: dict | None = Field(
        default=None,
        description="Serialised ReportFilterParams used to generate this report",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details when status=FAILED",
    )
