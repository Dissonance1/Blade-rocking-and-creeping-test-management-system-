"""
BladeService — business-logic orchestrator for all blade lifecycle operations.

Sits between the HTTP layer (routers) and the data layer (repositories +
workflow engine).  Every public method is a single unit of work that should
be called inside one ``AsyncSession`` transaction.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BladeStatus, RoleName
from app.repositories.blade_repository import BladeRepository
from app.repositories.measurement_repository import MeasurementRepository
from app.repositories.slot_repository import SlotRepository
from app.schemas.blade import BladeCreate, BladeUpdate
from app.schemas.measurement import MeasurementCreate
from app.schemas.slot_allocation import SlotAssignRequest
from app.workflows.state_machine import WorkflowEngine, WorkflowTransitionError

if TYPE_CHECKING:
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.slot_allocation import SlotAllocation
    from app.models.user import User
    from app.models.workflow import WorkflowLog
    from app.schemas.workflow import WorkflowHistoryResponse

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# States in which new measurements are accepted
# ---------------------------------------------------------------------------
_MEASUREMENT_ELIGIBLE_STATUSES: frozenset[BladeStatus] = frozenset(
    {
        BladeStatus.OH_INSPECTION,
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.RETURNED_TO_OH,
        BladeStatus.FINAL_VERIFICATION,
    }
)

# ---------------------------------------------------------------------------
# States from which a rejection is allowed (mirrors the state machine)
# ---------------------------------------------------------------------------
_REJECTABLE_STATUSES: frozenset[BladeStatus] = frozenset(
    {
        BladeStatus.OH_INSPECTION,
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.RETURNED_TO_OH,
        BladeStatus.FINAL_VERIFICATION,
    }
)


# ---------------------------------------------------------------------------
# Role-check helper
# ---------------------------------------------------------------------------

def _require_role(user: "User", *roles: RoleName) -> None:
    """Raise HTTP 403 if *user* does not hold any of *roles*."""
    if user.is_superuser:
        return
    user_role_names = {ur.role.name for ur in user.user_roles}
    if not user_role_names.intersection(set(roles)):
        allowed = ", ".join(r.value for r in roles)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation requires one of the following roles: {allowed}.",
        )


# ---------------------------------------------------------------------------
# BladeService
# ---------------------------------------------------------------------------


class BladeService:
    """
    Orchestrates blade lifecycle operations.

    Parameters
    ----------
    db:
        An open ``AsyncSession`` (caller is responsible for
        commit/rollback/close lifecycle).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._blade_repo = BladeRepository(db)
        self._measurement_repo = MeasurementRepository(db)
        self._slot_repo = SlotRepository(db)
        self._workflow_engine = WorkflowEngine(db)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_blade(
        self,
        data: BladeCreate,
        created_by: "User",
    ) -> "Blade":
        """
        Register a new blade and immediately advance it to ``OH_INSPECTION``.

        1. Validate ``serial_number`` uniqueness.
        2. Persist the blade with ``CREATED`` status.
        3. Transition to ``OH_INSPECTION``.

        Raises
        ------
        HTTPException(409)
            If a blade with the same serial number already exists.
        """
        existing = await self._blade_repo.get_by_serial(data.serial_number)
        if existing is not None:
            log.warning(
                "blade_service.create.duplicate_serial",
                serial_number=data.serial_number,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Blade with serial number '{data.serial_number}' already exists.",
            )

        station_id = data.station_id or (
            created_by.station_id  # default to operator's station
        )

        blade = await self._blade_repo.create(
            data,
            created_by_id=created_by.id,
            status=BladeStatus.CREATED,
            current_station_id=station_id,
        )

        log.info(
            "blade_service.created",
            blade_id=str(blade.id),
            serial=blade.serial_number,
            created_by=str(created_by.id),
        )

        # Immediately advance to OH_INSPECTION
        blade, _ = await self._workflow_engine.transition(
            blade=blade,
            to_status=BladeStatus.OH_INSPECTION,
            user=created_by,
            station_id=blade.current_station_id or created_by.station_id or blade.id,
            remarks="Blade registered — initial OH inspection opened.",
        )
        return blade

    # ------------------------------------------------------------------
    # Send to Assembly
    # ------------------------------------------------------------------

    async def send_to_assembly(
        self,
        blade_id: uuid.UUID,
        user: "User",
        remarks: str | None = None,
    ) -> "Blade":
        """
        Transition ``MEASUREMENTS_RECORDED`` → ``SENT_TO_ASSEMBLY``.

        Validates that:
        * The calling user holds the ``OH_OPERATOR`` role.
        * At least one measurement exists for the blade.

        Raises
        ------
        HTTPException(403)
            Role check failure.
        HTTPException(404)
            Blade not found.
        HTTPException(422)
            No measurements recorded.
        HTTPException(409)
            Transition not permitted by state machine.
        """
        _require_role(user, RoleName.OH_OPERATOR, RoleName.SUPER_ADMIN)

        blade = await self._get_blade_or_404(blade_id)

        measurements = await self._measurement_repo.get_by_blade(blade_id)
        if not measurements:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot send blade to assembly: no measurements have been recorded.",
            )

        blade, _ = await self._do_transition(
            blade=blade,
            to_status=BladeStatus.SENT_TO_ASSEMBLY,
            user=user,
            remarks=remarks,
        )
        log.info(
            "blade_service.sent_to_assembly",
            blade_id=str(blade_id),
            user_id=str(user.id),
        )
        return blade

    # ------------------------------------------------------------------
    # Assign Slot
    # ------------------------------------------------------------------

    async def assign_slot(
        self,
        blade_id: uuid.UUID,
        slot_data: SlotAssignRequest,
        user: "User",
    ) -> "SlotAllocation":
        """
        Assign *blade_id* to an assembly slot and transition to ``SLOT_ASSIGNED``.

        1. Role-guard (``ASSEMBLY_OPERATOR``).
        2. Verify the slot is not already occupied.
        3. Deactivate any pre-existing allocation for this blade.
        4. Create a new :class:`~app.models.slot_allocation.SlotAllocation`.
        5. Transition blade to ``SLOT_ASSIGNED``.

        Returns the new ``SlotAllocation``.

        Raises
        ------
        HTTPException(403)  role check
        HTTPException(404)  blade not found
        HTTPException(409)  slot_number already occupied
        HTTPException(409)  transition not permitted
        """
        _require_role(user, RoleName.ASSEMBLY_OPERATOR, RoleName.SUPER_ADMIN)

        blade = await self._get_blade_or_404(blade_id)

        # Slot-number uniqueness check
        occupying = await self._slot_repo.get_by_slot_number(slot_data.slot_number)
        if occupying is not None and occupying.blade_id != blade_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Slot '{slot_data.slot_number}' is already occupied "
                    f"by blade {occupying.blade_id}."
                ),
            )

        # Deactivate old allocation (if any)
        await self._slot_repo.deactivate_blade_slot(blade_id, user.id)

        # Create new allocation
        from app.models.slot_allocation import SlotAllocation

        allocation = SlotAllocation(
            blade_id=blade_id,
            slot_number=slot_data.slot_number,
            position=slot_data.position,
            group_id=slot_data.group_id,
            allocated_by_id=user.id,
            is_active=True,
        )
        self.db.add(allocation)
        await self.db.flush()
        await self.db.refresh(allocation)

        # Transition blade status
        await self._do_transition(
            blade=blade,
            to_status=BladeStatus.SLOT_ASSIGNED,
            user=user,
            remarks=slot_data.remarks or f"Assigned to slot {slot_data.slot_number}.",
        )

        log.info(
            "blade_service.slot_assigned",
            blade_id=str(blade_id),
            slot_number=slot_data.slot_number,
            user_id=str(user.id),
        )
        return allocation

    # ------------------------------------------------------------------
    # Return to OH
    # ------------------------------------------------------------------

    async def return_to_oh(
        self,
        blade_id: uuid.UUID,
        user: "User",
        remarks: str | None = None,
    ) -> "Blade":
        """
        Transition from a balancing state to ``RETURNED_TO_OH``.

        Valid source states (per state machine):
        ``SLOT_ASSIGNED``, ``BALANCING_IN_PROGRESS``, ``BALANCING_COMPLETED``.
        """
        blade = await self._get_blade_or_404(blade_id)
        blade, _ = await self._do_transition(
            blade=blade,
            to_status=BladeStatus.RETURNED_TO_OH,
            user=user,
            remarks=remarks,
        )
        log.info(
            "blade_service.returned_to_oh",
            blade_id=str(blade_id),
            user_id=str(user.id),
        )
        return blade

    # ------------------------------------------------------------------
    # Complete
    # ------------------------------------------------------------------

    async def complete_blade(
        self,
        blade_id: uuid.UUID,
        user: "User",
        remarks: str | None = None,
    ) -> "Blade":
        """
        Transition ``FINAL_VERIFICATION`` → ``COMPLETED``.

        Raises
        ------
        HTTPException(404)  blade not found
        HTTPException(409)  transition not permitted
        """
        blade = await self._get_blade_or_404(blade_id)
        blade, _ = await self._do_transition(
            blade=blade,
            to_status=BladeStatus.COMPLETED,
            user=user,
            remarks=remarks or "Final verification passed — blade completed.",
        )
        log.info(
            "blade_service.completed",
            blade_id=str(blade_id),
            user_id=str(user.id),
        )
        return blade

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    async def reject_blade(
        self,
        blade_id: uuid.UUID,
        user: "User",
        reason_id: uuid.UUID,
        notes: str,
    ) -> "Blade":
        """
        Transition to ``REJECTED`` from any valid current state.

        Persists ``rejection_reason_id`` and ``rejection_notes`` on the blade.

        Raises
        ------
        HTTPException(404)  blade not found
        HTTPException(409)  blade cannot be rejected from its current state
        """
        blade = await self._get_blade_or_404(blade_id)

        # Persist rejection metadata before the status change
        blade.rejection_reason_id = reason_id
        blade.rejection_notes = notes
        self.db.add(blade)
        await self.db.flush()

        blade, _ = await self._do_transition(
            blade=blade,
            to_status=BladeStatus.REJECTED,
            user=user,
            remarks=notes,
        )
        log.info(
            "blade_service.rejected",
            blade_id=str(blade_id),
            reason_id=str(reason_id),
            user_id=str(user.id),
        )
        return blade

    # ------------------------------------------------------------------
    # Reopen
    # ------------------------------------------------------------------

    async def reopen_blade(
        self,
        blade_id: uuid.UUID,
        user: "User",
        remarks: str | None = None,
    ) -> "Blade":
        """
        Transition ``REJECTED`` → ``REOPENED`` → ``OH_INSPECTION``.

        The two-step transition ensures a ``WorkflowLog`` entry is created for
        each intermediate state, giving QA a clear audit trail.

        Raises
        ------
        HTTPException(404)  blade not found
        HTTPException(409)  blade is not in REJECTED state
        """
        blade = await self._get_blade_or_404(blade_id)

        # Clear rejection metadata
        blade.rejection_reason_id = None
        blade.rejection_notes = None
        self.db.add(blade)
        await self.db.flush()

        # Step 1: REJECTED → REOPENED
        blade, _ = await self._do_transition(
            blade=blade,
            to_status=BladeStatus.REOPENED,
            user=user,
            remarks=remarks or "Blade reopened for re-inspection.",
        )

        # Step 2: REOPENED → OH_INSPECTION
        blade, _ = await self._do_transition(
            blade=blade,
            to_status=BladeStatus.OH_INSPECTION,
            user=user,
            remarks="Re-entered OH inspection after reopening.",
        )

        log.info(
            "blade_service.reopened",
            blade_id=str(blade_id),
            user_id=str(user.id),
        )
        return blade

    # ------------------------------------------------------------------
    # Workflow history
    # ------------------------------------------------------------------

    async def get_blade_history(
        self,
        blade_id: uuid.UUID,
    ) -> "WorkflowHistoryResponse":
        """
        Return the full workflow history for *blade_id*.

        Raises
        ------
        HTTPException(404)  blade not found
        """
        from app.schemas.workflow import (
            BladeSummaryForHistory,
            WorkflowHistoryResponse,
            WorkflowLogResponse,
        )

        blade = await self._blade_repo.get_with_measurements(blade_id)
        if blade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blade {blade_id} not found.",
            )

        logs = [WorkflowLogResponse.model_validate(wl) for wl in blade.workflow_logs]
        return WorkflowHistoryResponse(
            blade=BladeSummaryForHistory.model_validate(blade),
            logs=logs,
            total_transitions=len(logs),
        )

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------

    async def add_measurement(
        self,
        blade_id: uuid.UUID,
        data: MeasurementCreate,
        user: "User",
    ) -> "Measurement":
        """
        Record a new measurement for *blade_id*.

        Rules:
        * The blade must be in an eligible state (``OH_INSPECTION``,
          ``MEASUREMENTS_RECORDED``, ``RETURNED_TO_OH``,
          ``FINAL_VERIFICATION``).
        * If the blade is in ``OH_INSPECTION`` and this is its first
          measurement, auto-advance to ``MEASUREMENTS_RECORDED``.

        Raises
        ------
        HTTPException(404)  blade not found
        HTTPException(422)  blade not in a measurement-eligible state
        """
        blade = await self._get_blade_or_404(blade_id)

        if blade.status not in _MEASUREMENT_ELIGIBLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Measurements cannot be added when blade is in '{blade.status.value}' state. "
                    f"Eligible states: {[s.value for s in _MEASUREMENT_ELIGIBLE_STATUSES]}."
                ),
            )

        station_id = data.station_id or user.station_id
        measurement = await self._measurement_repo.create(
            data,
            measured_by_id=user.id,
            station_id=station_id,
        )

        log.info(
            "blade_service.measurement_added",
            blade_id=str(blade_id),
            measurement_id=str(measurement.id),
            measurement_type=measurement.measurement_type.value,
            user_id=str(user.id),
        )

        # Auto-transition OH_INSPECTION → MEASUREMENTS_RECORDED
        if blade.status == BladeStatus.OH_INSPECTION:
            await self._do_transition(
                blade=blade,
                to_status=BladeStatus.MEASUREMENTS_RECORDED,
                user=user,
                remarks="Auto-transitioned after first measurement recorded.",
            )

        return measurement

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_blade_or_404(self, blade_id: uuid.UUID) -> "Blade":
        blade = await self._blade_repo.get(blade_id)
        if blade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blade {blade_id} not found.",
            )
        return blade

    async def _do_transition(
        self,
        blade: "Blade",
        to_status: BladeStatus,
        user: "User",
        remarks: str | None = None,
    ) -> tuple["Blade", "WorkflowLog"]:
        """Thin wrapper around WorkflowEngine.transition that maps the domain
        exception to an HTTP 409."""
        station_id = (
            blade.current_station_id
            or user.station_id
            or blade.id  # last-resort fallback — avoids a null FK
        )
        try:
            return await self._workflow_engine.transition(
                blade=blade,
                to_status=to_status,
                user=user,
                station_id=station_id,
                remarks=remarks,
            )
        except WorkflowTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
