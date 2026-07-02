"""
Notification schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import NotificationType
from app.schemas.base import BaseSchema


class NotificationResponse(BaseSchema):
    """Full notification record returned to the client."""

    id: uuid.UUID
    user_id: uuid.UUID | None = Field(
        default=None,
        description="Target user; null indicates a broadcast notification",
    )
    title: str
    body: str
    notification_type: NotificationType
    is_read: bool
    read_at: datetime | None = None
    blade_id: uuid.UUID | None = None
    metadata: dict | None = Field(
        default=None,
        alias="metadata_",
        description="Arbitrary extra data (e.g. deep-link parameters)",
    )
    created_at: datetime
    expires_at: datetime | None = None

    model_config = BaseSchema.model_config.copy()  # type: ignore[assignment]


class NotificationUpdate(BaseSchema):
    """
    Payload for marking one or more notifications as read.

    Either ``is_read`` alone (applied to the notification addressed in the
    URL) or a batch of ``ids`` can be supplied.
    """

    is_read: bool = Field(default=True, description="Mark notification as read/unread")
    read_at: datetime | None = Field(
        default=None,
        description="Explicit read timestamp; defaults to current server time if null",
    )


class NotificationBatchReadRequest(BaseSchema):
    """Mark multiple notifications as read in a single request."""

    ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of notification UUIDs to mark as read",
    )
