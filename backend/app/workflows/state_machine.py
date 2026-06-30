"""
Blade workflow state machine.

This module is the single authoritative source for:

1. The ``ALLOWED_TRANSITIONS`` adjacency map — which ``BladeStatus`` values
   may follow which.
2. ``WorkflowTransitionError`` — the domain exception raised when a caller
   requests an invalid transition.
3. ``WorkflowEngine`` — the service object that validates, persists, and
   broadcasts every status change.

Design notes
------------
* The engine owns the DB interaction for ``WorkflowLog`` creation but
  delegates the ``Blade.status`` mutation to
  ``BladeRepository.update_status`` so that the repository remains the only
  place that writes to ``blades.status``.
* Notification dispatch is fire-and-forget via an event-queue helper to
  avoid blocking the HTTP response.  If the notification sub-system is
  unavailable the transition still commits.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BladeStatus

if TYPE_CHECKING:
    from app.models.blade import Blade
    from app.models.user import User
    from app.models.workflow import WorkflowLog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Transition map
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[BladeStatus, set[BladeStatus]] = {
    BladeStatus.CREATED: {BladeStatus.OH_INSPECTION},
    BladeStatus.OH_INSPECTION: {
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.REJECTED,
        BladeStatus.ON_HOLD,
    },
    BladeStatus.MEASUREMENTS_RECORDED: {
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.REJECTED,
        BladeStatus.ON_HOLD,
    },
    # Assembly receipt flow (720 Hanger)
    BladeStatus.SENT_TO_ASSEMBLY: {
        BladeStatus.ASSEMBLY_RECEIVED,   # batch marked received at Assembly
        BladeStatus.REJECTED,
    },
    BladeStatus.ASSEMBLY_RECEIVED: {
        BladeStatus.ASSEMBLY_VERIFIED,   # per-blade: scan → accept/modify
        BladeStatus.REJECTED,            # per-blade: reject at Assembly
        BladeStatus.ON_HOLD,
    },
    BladeStatus.ASSEMBLY_VERIFIED: {
        BladeStatus.SLOT_ASSIGNED,       # set-making complete → assign slot
        BladeStatus.REJECTED,
    },
    # Balancing & return flow
    BladeStatus.SLOT_ASSIGNED: {
        BladeStatus.BALANCING_IN_PROGRESS,
        BladeStatus.RETURNED_TO_OH,
    },
    BladeStatus.BALANCING_IN_PROGRESS: {
        BladeStatus.BALANCING_COMPLETED,
        BladeStatus.RETURNED_TO_OH,
    },
    BladeStatus.BALANCING_COMPLETED: {BladeStatus.RETURNED_TO_OH},
    BladeStatus.RETURNED_TO_OH: {
        BladeStatus.FINAL_VERIFICATION,
        BladeStatus.REJECTED,
    },
    BladeStatus.FINAL_VERIFICATION: {
        BladeStatus.COMPLETED,
        BladeStatus.REJECTED,
    },
    BladeStatus.REJECTED: {BladeStatus.REOPENED},
    BladeStatus.ON_HOLD: {
        BladeStatus.OH_INSPECTION,
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.ASSEMBLY_RECEIVED,
    },
    BladeStatus.REOPENED: {BladeStatus.OH_INSPECTION},
    BladeStatus.COMPLETED: set(),
}

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class WorkflowTransitionError(Exception):
    """
    Raised when a requested workflow transition is not permitted.

    Attributes
    ----------
    current:
        The blade's current ``BladeStatus``.
    requested:
        The ``BladeStatus`` the caller attempted to move to.
    """

    def __init__(self, current: BladeStatus, requested: BladeStatus) -> None:
        self.current = current
        self.requested = requested
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        allowed_labels = ", ".join(s.value for s in sorted(allowed, key=lambda x: x.value))
        super().__init__(
            f"Cannot transition blade from '{current.value}' to '{requested.value}'. "
            f"Allowed next states: [{allowed_labels or 'none'}]."
        )


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """
    Orchestrates blade status transitions.

    Responsibilities
    ----------------
    1. Validate that the requested transition is in ``ALLOWED_TRANSITIONS``.
    2. Persist the new ``Blade.status`` via ``BladeRepository``.
    3. Insert an immutable ``WorkflowLog`` row.
    4. Dispatch an async notification event (best-effort).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Core transition
    # ------------------------------------------------------------------

    async def transition(
        self,
        blade: "Blade",
        to_status: BladeStatus,
        user: "User",
        station_id: uuid.UUID | None,
        remarks: str | None = None,
    ) -> tuple["Blade", "WorkflowLog"]:
        """
        Attempt to transition *blade* to *to_status*.

        Parameters
        ----------
        blade:
            The ``Blade`` ORM instance (must be attached to the session).
        to_status:
            The target ``BladeStatus``.
        user:
            The ``User`` performing the transition (audit trail).
        station_id:
            The station from which the action originates.
        remarks:
            Optional free-text notes appended to the workflow log.

        Returns
        -------
        tuple[Blade, WorkflowLog]
            The refreshed blade and the newly created log entry.

        Raises
        ------
        WorkflowTransitionError
            If the transition is not listed in ``ALLOWED_TRANSITIONS``.
        """
        from app.models.workflow import WorkflowLog  # avoid circular import
        from app.repositories.blade_repository import BladeRepository

        from_status = blade.status

        if not await self.can_transition(from_status, to_status):
            log.warning(
                "workflow.invalid_transition",
                blade_id=str(blade.id),
                from_status=from_status.value,
                to_status=to_status.value,
                user_id=str(user.id),
            )
            raise WorkflowTransitionError(current=from_status, requested=to_status)

        log.info(
            "workflow.transition.begin",
            blade_id=str(blade.id),
            from_status=from_status.value,
            to_status=to_status.value,
            user_id=str(user.id),
            station_id=str(station_id) if station_id else None,
        )

        # 1. Update blade status
        blade_repo = BladeRepository(self.db)
        updated_blade = await blade_repo.update_status(blade.id, to_status, user.id)

        # 2. Create workflow log
        workflow_log = WorkflowLog(
            blade_id=blade.id,
            from_status=from_status,
            to_status=to_status,
            action_by_id=user.id,
            station_id=station_id,
            remarks=remarks,
            timestamp=datetime.now(timezone.utc),
        )
        self.db.add(workflow_log)
        await self.db.flush()
        await self.db.refresh(workflow_log)

        log.info(
            "workflow.transition.complete",
            blade_id=str(blade.id),
            log_id=str(workflow_log.id),
            from_status=from_status.value,
            to_status=to_status.value,
        )

        # 3. Dispatch notification (best-effort, non-blocking)
        await self._dispatch_notification(
            blade=updated_blade,
            from_status=from_status,
            to_status=to_status,
            user=user,
            station_id=station_id,
        )

        return updated_blade, workflow_log

    # ------------------------------------------------------------------
    # Guard helpers
    # ------------------------------------------------------------------

    async def can_transition(
        self,
        from_status: BladeStatus,
        to_status: BladeStatus,
    ) -> bool:
        """Return ``True`` if moving from *from_status* → *to_status* is allowed."""
        return to_status in ALLOWED_TRANSITIONS.get(from_status, set())

    @staticmethod
    def get_allowed_transitions(status: BladeStatus) -> set[BladeStatus]:
        """Return the set of statuses reachable from *status*."""
        return set(ALLOWED_TRANSITIONS.get(status, set()))

    # ------------------------------------------------------------------
    # Notification helper
    # ------------------------------------------------------------------

    async def _dispatch_notification(
        self,
        blade: "Blade",
        from_status: BladeStatus,
        to_status: BladeStatus,
        user: "User",
        station_id: uuid.UUID,
    ) -> None:
        """
        Fire-and-forget notification event.

        The notification payload is intentionally minimal; downstream
        consumers should re-fetch full blade data as needed.  If notification
        dispatch raises an exception it is caught and logged so that the
        calling transaction is not rolled back.
        """
        try:
            from app.models.enums import NotificationType
            from app.models.notification import Notification

            # Map transitions to notification types
            _transition_to_notification: dict[BladeStatus, NotificationType] = {
                # ASSEMBLY_RECEIVED omitted — assembly_service fires one batch-level notification instead
                BladeStatus.ASSEMBLY_VERIFIED: NotificationType.WORKFLOW_UPDATED,
                BladeStatus.SLOT_ASSIGNED: NotificationType.SLOT_PENDING,
                BladeStatus.BALANCING_COMPLETED: NotificationType.BALANCING_DONE,
                BladeStatus.REJECTED: NotificationType.BLADE_REJECTED,
                BladeStatus.FINAL_VERIFICATION: NotificationType.VERIFICATION_PENDING,
            }

            notif_type = _transition_to_notification.get(to_status)
            if notif_type is None:
                return  # No notification for this transition

            notification = Notification(
                blade_id=blade.id,
                notification_type=notif_type,
                title=f"Blade {blade.serial_number}: {to_status.value}",
                body=(
                    f"Blade {blade.serial_number} transitioned "
                    f"from {from_status.value} to {to_status.value}."
                ),
            )
            self.db.add(notification)
            await self.db.flush()

            log.debug(
                "workflow.notification_dispatched",
                blade_id=str(blade.id),
                notification_type=notif_type.value,
            )

        except Exception as exc:  # noqa: BLE001
            log.error(
                "workflow.notification_dispatch_failed",
                blade_id=str(blade.id),
                to_status=to_status.value,
                error=str(exc),
                exc_info=True,
            )
