"""
Workflow log and station schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import BladeStatus, StationType
from app.schemas.base import BaseSchema
from app.schemas.user import UserListItem


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------

class StationResponse(BaseSchema):
    """Full station record."""

    id: uuid.UUID
    name: str
    code: str
    station_type: StationType
    is_active: bool
    location: str | None = None


# ---------------------------------------------------------------------------
# WorkflowLog
# ---------------------------------------------------------------------------

class WorkflowLogResponse(BaseSchema):
    """
    A single immutable workflow-log entry recording one status transition.
    """

    id: uuid.UUID
    blade_id: uuid.UUID
    from_status: BladeStatus | None = Field(
        default=None,
        description="Status before the transition (null for initial creation)",
    )
    to_status: BladeStatus = Field(..., description="Status after the transition")
    action_by: UserListItem | None = None
    station: StationResponse | None = None
    remarks: str | None = None
    timestamp: datetime
    metadata: dict | None = Field(
        default=None,
        description="Arbitrary extra data attached to this transition",
        alias="metadata_",
    )

    model_config = BaseSchema.model_config.copy()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# WorkflowHistory (blade info + all log entries)
# ---------------------------------------------------------------------------

class BladeSummaryForHistory(BaseSchema):
    """Minimal blade info embedded in WorkflowHistoryResponse."""

    id: uuid.UUID
    serial_number: str
    melt_number: str | None = None
    status: BladeStatus
    part_number: str | None = None


class WorkflowHistoryResponse(BaseSchema):
    """
    Full workflow history for a single blade.

    Used by the /blades/{id}/workflow endpoint.
    """

    blade: BladeSummaryForHistory
    logs: list[WorkflowLogResponse] = Field(
        ...,
        description="Chronological list of all status transitions for this blade",
    )
    total_transitions: int = Field(
        ..., ge=0, description="Total number of transitions recorded"
    )
