"""
Notification endpoints.

GET  /notifications/                          — list user notifications (paginated)
GET  /notifications/unread-count              — badge count
POST /notifications/{notification_id}/read    — mark single as read
POST /notifications/read-all                  — mark all as read
WS   /notifications/ws/notifications          — WebSocket for real-time push
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import decode_token
from app.db.session import get_db, AsyncSessionLocal
from app.notifications.manager import notification_manager
from app.schemas.base import PaginatedResponse, StatusResponse
from app.schemas.notification import NotificationResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=PaginatedResponse[NotificationResponse],
    status_code=status.HTTP_200_OK,
    summary="List notifications for the current user",
)
async def list_notifications(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False, description="Return only unread notifications"),
) -> Any:
    """
    Return a paginated list of notifications for the authenticated user.

    Notifications are ordered: unread first, then by creation date
    descending.  Pass ``unread_only=true`` to filter out already-read items.
    """
    from app.models.notification import Notification

    from sqlalchemy import or_
    # Include notifications targeted to this user OR broadcast (user_id=NULL)
    user_filter = or_(
        Notification.user_id == current_user.id,
        Notification.user_id.is_(None),
    )
    conditions = [user_filter]
    if unread_only:
        conditions.append(Notification.is_read.is_(False))

    total: int = (
        await db.execute(
            select(func.count()).select_from(Notification).where(*conditions)
        )
    ).scalar_one()

    items = list(
        (
            await db.execute(
                select(Notification)
                .where(*conditions)
                .order_by(
                    Notification.is_read.asc(),   # unread first
                    Notification.created_at.desc(),
                )
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    page = skip // limit + 1 if limit > 0 else 1
    return PaginatedResponse(items=items, total=total, page=page, page_size=limit)


# ---------------------------------------------------------------------------
# GET /unread-count
# ---------------------------------------------------------------------------


@router.get(
    "/unread-count",
    status_code=status.HTTP_200_OK,
    summary="Get the count of unread notifications",
)
async def unread_count(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Return the number of unread notifications for the current user.
    Suitable for driving a badge/counter in the UI header.
    """
    from app.models.notification import Notification
    from sqlalchemy import or_

    count: int = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                or_(
                    Notification.user_id == current_user.id,
                    Notification.user_id.is_(None),
                ),
                Notification.is_read.is_(False),
            )
        )
    ).scalar_one()

    return {"unread_count": count}


# ---------------------------------------------------------------------------
# POST /{notification_id}/read
# ---------------------------------------------------------------------------


@router.post(
    "/{notification_id}/read",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a single notification as read",
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Mark the specified notification as read for the current user.

    Accepts both user-targeted and broadcast (user_id=NULL) notifications.
    """
    from app.models.notification import Notification
    from datetime import datetime, timezone
    from sqlalchemy import or_

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id.is_(None),
            ),
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found",
        )

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()

    return StatusResponse(message="Notification marked as read")


# ---------------------------------------------------------------------------
# POST /read-all
# ---------------------------------------------------------------------------


@router.post(
    "/read-all",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications as read",
)
async def mark_all_read(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Mark every unread notification visible to the current user as read.
    Includes both user-targeted notifications and broadcast (user_id=NULL) ones.
    """
    from app.models.notification import Notification
    from datetime import datetime, timezone
    from sqlalchemy import update, or_

    result = await db.execute(
        update(Notification)
        .where(
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id.is_(None),
            ),
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )

    count: int = result.rowcount
    await db.commit()

    logger.info("all_notifications_marked_read", user_id=str(current_user.id), count=count)
    return StatusResponse(message=f"{count} notification(s) marked as read")


# ---------------------------------------------------------------------------
# WebSocket: /ws/notifications
# ---------------------------------------------------------------------------


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time notification delivery.

    **Authentication**: The client must pass a valid JWT access token as
    a query parameter: ``?token=<access_token>``.

    **Protocol**:
    - On successful connect the server sends a ``{"event": "connected"}``
      message.
    - The server pushes ``{"event": "notification", "data": {...}}``
      messages whenever a new notification is created for the user.
    - The client may send a ``{"type": "ping"}`` heartbeat; the server
      replies with ``{"type": "pong"}``.
    - The connection is closed with code 4001 if the token is invalid.
    """
    # Extract and validate JWT from query param
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return

    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    from uuid import UUID

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        await websocket.close(code=4001, reason="Malformed token subject")
        return

    # Verify user still exists
    async with AsyncSessionLocal() as db:
        from app.models.user import User
        from sqlalchemy import select as sa_select

        user_result = await db.execute(
            sa_select(User).where(User.id == user_id, User.is_active.is_(True))
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            await websocket.close(code=4001, reason="User not found or inactive")
            return

    await notification_manager.connect(websocket, user_id)
    await websocket.send_json(
        {"event": "connected", "user_id": str(user_id)}
    )

    logger.info("websocket_notifications_opened", user_id=str(user_id))

    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket_notifications_closed", user_id=str(user_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("websocket_notifications_error", user_id=str(user_id), error=str(exc))
    finally:
        await notification_manager.disconnect(websocket, user_id)
