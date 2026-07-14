"""
NotificationService — database-backed notification creation, retrieval,
and read-state management, wired to real-time WebSocket delivery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.notifications.events import build_blade_notification_payload
from app.notifications.manager import notification_manager

if TYPE_CHECKING:
    from app.models.blade import Blade
    from app.models.user import User

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
    # Read-state management
    # ------------------------------------------------------------------

    async def mark_read(self, notification_id: UUID, user_id: UUID) -> bool:
        """
        Mark a single notification as read.

        Returns ``True`` when the notification existed and belonged to
        *user_id*; ``False`` otherwise.
        """
        result = await self._db.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self._db.commit()

        updated = result.rowcount > 0
        if updated:
            logger.debug(
                "notification_marked_read",
                notification_id=str(notification_id),
                user_id=str(user_id),
            )
        return updated

    async def mark_all_read(self, user_id: UUID) -> int:
        """
        Mark **all** unread notifications for *user_id* as read.

        Returns the number of rows updated.
        """
        result = await self._db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self._db.commit()

        count: int = result.rowcount
        logger.info(
            "notifications_all_marked_read",
            user_id=str(user_id),
            count=count,
        )
        return count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_user_notifications(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Notification], int]:
        """
        Paginated fetch of notifications for *user_id*, ordered newest first.

        Returns a ``(items, total)`` tuple.
        """
        base_where = Notification.user_id == user_id

        # Total count (separate query for accurate pagination metadata).
        count_result = await self._db.execute(
            select(func.count()).select_from(Notification).where(base_where)
        )
        total: int = count_result.scalar_one()

        # Paginated items.
        items_result = await self._db.execute(
            select(Notification)
            .where(base_where)
            .order_by(Notification.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items: list[Notification] = list(items_result.scalars().all())

        return items, total

    async def get_unread_count(self, user_id: UUID) -> int:
        """Return the number of unread notifications for *user_id*."""
        result = await self._db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Domain event dispatcher
    # ------------------------------------------------------------------

    async def dispatch_blade_event(
        self,
        event_type: str,
        blade: Blade,
        actor: User,
        extra_data: dict | None = None,
    ) -> None:
        """
        React to a blade lifecycle event by:

        1. Determining who should be notified (role-based routing).
        2. Persisting a :class:`~app.models.notification.Notification` for
           each target user.
        3. Pushing the payload via WebSocket.

        Event routing table
        -------------------
        ``blade_received``       → ASSEMBLY_OPERATORs
        ``slot_pending``         → OH_OPERATORs
        ``balancing_done``       → SUPER_ADMINs + ASSEMBLY_OPERATORs
        ``blade_rejected``       → SUPER_ADMINs + blade creator
        ``verification_pending`` → SUPER_ADMINs
        ``workflow_updated``     → blade creator + SUPER_ADMINs
        """
        from app.models.user import User as UserModel  # late import

        payload = build_blade_notification_payload(event_type, blade, actor)
        title: str = payload["message"]
        body: str = payload.get("description", title)

        # Determine which roles should receive the notification.
        target_roles: list[str] = []
        notify_creator: bool = False

        routing: dict[str, tuple[list[str], bool]] = {
            "blade_received": ([ROLE_ASSEMBLY_OPERATOR], False),
            "slot_pending": ([ROLE_OH_OPERATOR], False),
            "balancing_done": ([ROLE_SUPER_ADMIN, ROLE_ASSEMBLY_OPERATOR], False),
            "blade_rejected": ([ROLE_SUPER_ADMIN, ROLE_OH_OPERATOR], True),
            "verification_pending": ([ROLE_SUPER_ADMIN], False),
            "workflow_updated": ([ROLE_SUPER_ADMIN], False),
        }

        if event_type in routing:
            target_roles, notify_creator = routing[event_type]
        else:
            logger.warning("dispatch_blade_event_unknown_type", event_type=event_type)
            target_roles = [ROLE_SUPER_ADMIN]

        # Fetch all active users with any of the target roles via user_roles join
        if target_roles:
            from app.models.user import UserRole as UserRoleModel, Role
            result = await self._db.execute(
                select(UserModel)
                .join(UserRoleModel, UserRoleModel.user_id == UserModel.id)
                .join(Role, Role.id == UserRoleModel.role_id)
                .where(
                    Role.name.in_(target_roles),
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                )
                .distinct()
            )
            role_users: list[UserModel] = list(result.scalars().all())
        else:
            role_users = []

        # Build the full set of target user ids (deduplicated)
        target_user_ids: set[UUID] = {u.id for u in role_users}

        # Notify blade creator if applicable (created_by_id column)
        if notify_creator:
            creator_id = getattr(blade, "created_by_id", None)
            if creator_id:
                target_user_ids.add(creator_id)

        # Exclude the actor from their own notifications where sensible.
        # (Uncomment if desired: target_user_ids.discard(actor.id))

        notification_type_map: dict[str, NotificationType] = {
            "blade_received": NotificationType.BLADE_RECEIVED,
            "slot_pending": NotificationType.SLOT_PENDING,
            "balancing_done": NotificationType.BALANCING_DONE,
            "blade_rejected": NotificationType.BLADE_REJECTED,
            "verification_pending": NotificationType.VERIFICATION_PENDING,
            "workflow_updated": NotificationType.WORKFLOW_UPDATED,
        }
        n_type = notification_type_map.get(event_type, NotificationType.GENERAL)

        logger.info(
            "dispatching_blade_event",
            event_type=event_type,
            blade_id=str(blade.id),
            target_users=len(target_user_ids),
        )

        for user_id in target_user_ids:
            await self.create_notification(
                user_id=user_id,
                title=title,
                body=body,
                notification_type=n_type,
                blade_id=blade.id,
                metadata={**payload, **(extra_data or {})},
            )

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
