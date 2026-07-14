"""
NotificationService — database-backed notification creation and
role-based broadcast helpers, wired to real-time WebSocket delivery.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.notifications.manager import notification_manager

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Role constants — mirrored here to avoid circular imports with models.
# ---------------------------------------------------------------------------
ROLE_ASSEMBLY_OPERATOR = "ASSEMBLY_OPERATOR"
ROLE_OH_OPERATOR = "OH_OPERATOR"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"


class NotificationService:
    """
    High-level service for managing notifications.

    Handles persistence (via SQLAlchemy async session) *and* real-time
    delivery (via :data:`~app.notifications.manager.notification_manager`).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    async def create_notification(
        self,
        user_id: UUID | None,
        title: str,
        body: str,
        notification_type: NotificationType,
        blade_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> Notification:
        """
        Persist a notification record and push it to the user's WebSocket
        connections (if any are open).

        *user_id* may be ``None`` for system-wide / broadcast notifications
        that are not tied to a specific user.
        """
        notification = Notification(
            user_id=user_id,
            title=title,
            body=body,
            notification_type=notification_type,
            blade_id=blade_id,
            metadata_=metadata or {},
            is_read=False,
        )
        self._db.add(notification)
        await self._db.commit()
        await self._db.refresh(notification)

        logger.info(
            "notification_created",
            notification_id=str(notification.id),
            user_id=str(user_id) if user_id else None,
            notification_type=notification_type.value,
        )

        # Push real-time delivery when a target user is known.
        if user_id is not None:
            payload = {
                "event": "notification",
                "data": {
                    "id": str(notification.id),
                    "title": notification.title,
                    "body": notification.body,
                    "type": notification_type.value,
                    "blade_id": str(blade_id) if blade_id else None,
                    "metadata": metadata or {},
                    "is_read": False,
                    "created_at": notification.created_at.isoformat(),
                },
            }
            await notification_manager.send_to_user(user_id, payload)

        return notification

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    async def notify_roles(
        self,
        roles: list[str],
        title: str,
        body: str,
        notification_type: NotificationType = NotificationType.GENERAL,
        metadata: dict | None = None,
    ) -> None:
        """Send one notification to every active user that has any of *roles*."""
        from app.models.user import User as UserModel, UserRole as UserRoleModel, Role

        result = await self._db.execute(
            select(UserModel)
            .join(UserRoleModel, UserRoleModel.user_id == UserModel.id)
            .join(Role, Role.id == UserRoleModel.role_id)
            .where(
                Role.name.in_(roles),
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
            )
            .distinct()
        )
        for user in result.scalars().all():
            await self.create_notification(
                user_id=user.id,
                title=title,
                body=body,
                notification_type=notification_type,
                blade_id=None,
                metadata=metadata or {},
            )

    async def notify_batch_received(
        self,
        work_order_number: str,
        blade_count: int,
        operator_display: str,
    ) -> None:
        """ONE notification to OH + Super Admin when Assembly marks a work order received."""
        await self.notify_roles(
            roles=[ROLE_OH_OPERATOR, ROLE_SUPER_ADMIN],
            title=f"Work Order {work_order_number} received at Assembly",
            body=(
                f"Work Order {work_order_number} ({blade_count} blade{'s' if blade_count != 1 else ''}) "
                f"has been received at Assembly by {operator_display}."
            ),
            notification_type=NotificationType.BLADE_RECEIVED,
            metadata={"work_order_number": work_order_number, "blade_count": blade_count},
        )
