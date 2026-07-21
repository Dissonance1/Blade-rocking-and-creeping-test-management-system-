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

from app.models.enums import BladeStatus, BladeType

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
    },
    BladeStatus.MEASUREMENTS_RECORDED: {
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.REJECTED,
    },
    # Assembly receipt flow (720 Hanger)
    BladeStatus.SENT_TO_ASSEMBLY: {
        BladeStatus.ASSEMBLY_RECEIVED,   # batch marked received at Assembly
        BladeStatus.SLOT_ASSIGNED,       # batch bulk slot assignment (skips per-blade verify)
        BladeStatus.REJECTED,
    },
    BladeStatus.ASSEMBLY_RECEIVED: {
        BladeStatus.ASSEMBLY_VERIFIED,   # per-blade: scan → accept/modify
        BladeStatus.SLOT_ASSIGNED,       # batch bulk slot assignment (skips per-blade verify)
        BladeStatus.REJECTED,            # per-blade: reject at Assembly
    },
    BladeStatus.ASSEMBLY_VERIFIED: {
        BladeStatus.SLOT_ASSIGNED,       # set-making complete → assign slot
        BladeStatus.REJECTED,
    },
    # Balancing & return flow
    BladeStatus.SLOT_ASSIGNED: {
        BladeStatus.BALANCING_IN_PROGRESS,
        BladeStatus.BALANCING_COMPLETED,  # operator can report "balanced" directly, skipping the in-progress step
        BladeStatus.RETURNED_TO_OH,
    },
    BladeStatus.BALANCING_IN_PROGRESS: {
        BladeStatus.BALANCING_COMPLETED,
        BladeStatus.RETURNED_TO_OH,
    },
    BladeStatus.BALANCING_COMPLETED: {BladeStatus.RETURNED_TO_OH},
    BladeStatus.RETURNED_TO_OH: {
        BladeStatus.SLOT_ASSIGNED,       # rework: re-slot after returning to OH
        BladeStatus.FINAL_VERIFICATION,
        BladeStatus.REJECTED,
    },
    BladeStatus.FINAL_VERIFICATION: {
        BladeStatus.COMPLETED,
        BladeStatus.REJECTED,
    },
    BladeStatus.REJECTED: {BladeStatus.REOPENED},
    BladeStatus.REOPENED: {BladeStatus.OH_INSPECTION},
    BladeStatus.COMPLETED: set(),
}

# ---------------------------------------------------------------------------
# Blade-type-conditional extra edges
#
# HPTR blades never leave OH — they skip the assembly-transit statuses
# entirely. These edges are additive on top of ALLOWED_TRANSITIONS and only
# apply when the blade's type matches; LPTR blades must not gain them.
# ---------------------------------------------------------------------------

EXTRA_TRANSITIONS_BY_TYPE: dict[BladeType, dict[BladeStatus, set[BladeStatus]]] = {
    BladeType.HPTR: {
        BladeStatus.MEASUREMENTS_RECORDED: {BladeStatus.SLOT_ASSIGNED},
        BladeStatus.BALANCING_COMPLETED: {
            BladeStatus.FINAL_VERIFICATION,
            # Physical balancing testing found the set still unbalanced —
            # OH rejects the saved slot allocation and redoes it from scratch.
            BladeStatus.MEASUREMENTS_RECORDED,
        },
        BladeStatus.SLOT_ASSIGNED: {BladeStatus.MEASUREMENTS_RECORDED},
        BladeStatus.BALANCING_IN_PROGRESS: {BladeStatus.MEASUREMENTS_RECORDED},
    },
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

        if not await self.can_transition(from_status, to_status, blade.blade_type):
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

        return updated_blade, workflow_log

    # ------------------------------------------------------------------
    # Guard helpers
    # ------------------------------------------------------------------

    async def can_transition(
        self,
        from_status: BladeStatus,
        to_status: BladeStatus,
        blade_type: BladeType | None = None,
    ) -> bool:
        """Return ``True`` if moving from *from_status* → *to_status* is allowed.

        *blade_type* additionally unlocks the HPTR-only shortcut edges in
        ``EXTRA_TRANSITIONS_BY_TYPE`` (e.g. skipping the assembly-transit
        statuses). Omitting it preserves the base, type-agnostic map.
        """
        if to_status in ALLOWED_TRANSITIONS.get(from_status, set()):
            return True
        if blade_type is not None:
            extra = EXTRA_TRANSITIONS_BY_TYPE.get(blade_type, {})
            if to_status in extra.get(from_status, set()):
                return True
        return False

    @staticmethod
    def get_allowed_transitions(status: BladeStatus) -> set[BladeStatus]:
        """Return the set of statuses reachable from *status*."""
        return set(ALLOWED_TRANSITIONS.get(status, set()))
