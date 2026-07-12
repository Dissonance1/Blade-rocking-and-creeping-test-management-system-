"""
Unit tests for the blade workflow state machine.

These tests exercise the pure Python logic in ``app.workflows.state_machine``
without touching the database — ``WorkflowEngine.transition`` is tested at the
service/integration level; here we focus on:

1. Transition validity (ALLOWED_TRANSITIONS map)
2. WorkflowTransitionError message formatting
3. WorkflowEngine.can_transition() (async guard)
4. WorkflowEngine.get_allowed_transitions() (static helper)
5. Terminal state enforcement (COMPLETED has no outbound transitions)
6. REJECTED → REOPENED → OH_INSPECTION reopen path
"""

from __future__ import annotations

import pytest

from app.models.enums import BladeStatus, BladeType
from app.workflows.state_machine import (
    ALLOWED_TRANSITIONS,
    EXTRA_TRANSITIONS_BY_TYPE,
    WorkflowEngine,
    WorkflowTransitionError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_STATUSES = list(BladeStatus)


def _all_invalid_targets(source: BladeStatus) -> list[BladeStatus]:
    """Return every status that is NOT a valid next state from *source*."""
    allowed = ALLOWED_TRANSITIONS.get(source, set())
    return [s for s in ALL_STATUSES if s not in allowed]


# ---------------------------------------------------------------------------
# 1. Allowed transitions — parametrize over every (from, to) pair in the map
# ---------------------------------------------------------------------------

VALID_TRANSITION_PAIRS: list[tuple[BladeStatus, BladeStatus]] = [
    (src, tgt)
    for src, targets in ALLOWED_TRANSITIONS.items()
    for tgt in targets
]


@pytest.mark.parametrize("from_status,to_status", VALID_TRANSITION_PAIRS)
def test_allowed_transitions_are_in_map(
    from_status: BladeStatus, to_status: BladeStatus
) -> None:
    """Every pair in ALLOWED_TRANSITIONS is recognised as valid."""
    assert to_status in ALLOWED_TRANSITIONS[from_status], (
        f"{from_status.value} → {to_status.value} should be allowed"
    )


# ---------------------------------------------------------------------------
# 2. Invalid transitions raise WorkflowTransitionError
# ---------------------------------------------------------------------------

# Build a representative (but not exhaustive) set of invalid pairs.
INVALID_TRANSITION_PAIRS: list[tuple[BladeStatus, BladeStatus]] = [
    (BladeStatus.CREATED, BladeStatus.COMPLETED),
    (BladeStatus.CREATED, BladeStatus.REJECTED),
    (BladeStatus.CREATED, BladeStatus.BALANCING_IN_PROGRESS),
    (BladeStatus.OH_INSPECTION, BladeStatus.COMPLETED),
    (BladeStatus.OH_INSPECTION, BladeStatus.BALANCING_COMPLETED),
    (BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.COMPLETED),
    (BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.FINAL_VERIFICATION),
    (BladeStatus.SENT_TO_ASSEMBLY, BladeStatus.MEASUREMENTS_RECORDED),
    (BladeStatus.SENT_TO_ASSEMBLY, BladeStatus.COMPLETED),
    (BladeStatus.BALANCING_COMPLETED, BladeStatus.COMPLETED),
    (BladeStatus.COMPLETED, BladeStatus.OH_INSPECTION),
    (BladeStatus.COMPLETED, BladeStatus.REJECTED),
    (BladeStatus.REJECTED, BladeStatus.OH_INSPECTION),   # must go through REOPENED
    (BladeStatus.REOPENED, BladeStatus.COMPLETED),
]


@pytest.mark.parametrize("from_status,to_status", INVALID_TRANSITION_PAIRS)
def test_invalid_transitions_not_in_map(
    from_status: BladeStatus, to_status: BladeStatus
) -> None:
    """Each invalid pair must NOT appear in ALLOWED_TRANSITIONS."""
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    assert to_status not in allowed, (
        f"{from_status.value} → {to_status.value} should be FORBIDDEN"
    )


# ---------------------------------------------------------------------------
# 3. WorkflowTransitionError carries useful attributes
# ---------------------------------------------------------------------------


def test_workflow_transition_error_attributes() -> None:
    """The exception stores current/requested and includes them in its message."""
    exc = WorkflowTransitionError(
        current=BladeStatus.CREATED,
        requested=BladeStatus.COMPLETED,
    )
    assert exc.current == BladeStatus.CREATED
    assert exc.requested == BladeStatus.COMPLETED
    assert "CREATED" in str(exc)
    assert "COMPLETED" in str(exc)


def test_workflow_transition_error_lists_allowed_states() -> None:
    """The error message enumerates the allowed next states."""
    exc = WorkflowTransitionError(
        current=BladeStatus.OH_INSPECTION,
        requested=BladeStatus.COMPLETED,
    )
    msg = str(exc)
    # OH_INSPECTION allows MEASUREMENTS_RECORDED, REJECTED, ON_HOLD
    assert "MEASUREMENTS_RECORDED" in msg or "REJECTED" in msg


def test_workflow_transition_error_terminal_state_message() -> None:
    """Error message for a terminal state should say 'none'."""
    exc = WorkflowTransitionError(
        current=BladeStatus.COMPLETED,
        requested=BladeStatus.OH_INSPECTION,
    )
    assert "none" in str(exc).lower()


# ---------------------------------------------------------------------------
# 4. Terminal state: COMPLETED has no outbound transitions
# ---------------------------------------------------------------------------


def test_terminal_state_completed_has_no_transitions() -> None:
    """COMPLETED must be in the map with an empty target set."""
    assert BladeStatus.COMPLETED in ALLOWED_TRANSITIONS
    assert ALLOWED_TRANSITIONS[BladeStatus.COMPLETED] == set()


def test_terminal_state_get_allowed_transitions_returns_empty() -> None:
    """WorkflowEngine.get_allowed_transitions returns empty set for COMPLETED."""
    result = WorkflowEngine.get_allowed_transitions(BladeStatus.COMPLETED)
    assert result == set()


# ---------------------------------------------------------------------------
# 5. REJECTED → REOPENED → OH_INSPECTION (reopen path)
# ---------------------------------------------------------------------------


def test_rejected_can_transition_to_reopened() -> None:
    """A REJECTED blade can be moved to REOPENED."""
    assert BladeStatus.REOPENED in ALLOWED_TRANSITIONS[BladeStatus.REJECTED]


def test_reopened_can_transition_to_oh_inspection() -> None:
    """A REOPENED blade goes back to OH_INSPECTION for re-inspection."""
    assert BladeStatus.OH_INSPECTION in ALLOWED_TRANSITIONS[BladeStatus.REOPENED]


def test_reopened_cannot_skip_to_completed() -> None:
    """A REOPENED blade cannot jump directly to COMPLETED."""
    assert BladeStatus.COMPLETED not in ALLOWED_TRANSITIONS[BladeStatus.REOPENED]


def test_rejected_cannot_go_directly_to_oh_inspection() -> None:
    """REJECTED must pass through REOPENED before OH_INSPECTION."""
    assert BladeStatus.OH_INSPECTION not in ALLOWED_TRANSITIONS[BladeStatus.REJECTED]


# ---------------------------------------------------------------------------
# 6. WorkflowEngine.get_allowed_transitions — static helper
# ---------------------------------------------------------------------------

GET_ALLOWED_CASES: list[tuple[BladeStatus, set[BladeStatus]]] = [
    (
        BladeStatus.CREATED,
        {BladeStatus.OH_INSPECTION},
    ),
    (
        BladeStatus.OH_INSPECTION,
        {BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.REJECTED, BladeStatus.ON_HOLD},
    ),
    (
        BladeStatus.MEASUREMENTS_RECORDED,
        {BladeStatus.SENT_TO_ASSEMBLY, BladeStatus.REJECTED, BladeStatus.ON_HOLD},
    ),
    (
        BladeStatus.SENT_TO_ASSEMBLY,
        {BladeStatus.ASSEMBLY_RECEIVED, BladeStatus.SLOT_ASSIGNED, BladeStatus.REJECTED},
    ),
    (
        BladeStatus.SLOT_ASSIGNED,
        {BladeStatus.BALANCING_IN_PROGRESS, BladeStatus.RETURNED_TO_OH},
    ),
    (
        BladeStatus.BALANCING_IN_PROGRESS,
        {BladeStatus.BALANCING_COMPLETED, BladeStatus.RETURNED_TO_OH},
    ),
    (
        BladeStatus.BALANCING_COMPLETED,
        {BladeStatus.RETURNED_TO_OH},
    ),
    (
        BladeStatus.RETURNED_TO_OH,
        {BladeStatus.SLOT_ASSIGNED, BladeStatus.FINAL_VERIFICATION, BladeStatus.REJECTED},
    ),
    (
        BladeStatus.FINAL_VERIFICATION,
        {BladeStatus.COMPLETED, BladeStatus.REJECTED},
    ),
    (
        BladeStatus.REJECTED,
        {BladeStatus.REOPENED},
    ),
    (
        BladeStatus.ON_HOLD,
        {BladeStatus.OH_INSPECTION, BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.ASSEMBLY_RECEIVED},
    ),
    (
        BladeStatus.REOPENED,
        {BladeStatus.OH_INSPECTION},
    ),
    (
        BladeStatus.COMPLETED,
        set(),
    ),
]


@pytest.mark.parametrize("status,expected", GET_ALLOWED_CASES)
def test_get_allowed_transitions(
    status: BladeStatus, expected: set[BladeStatus]
) -> None:
    """get_allowed_transitions returns the exact expected set for each status."""
    result = WorkflowEngine.get_allowed_transitions(status)
    assert result == expected, (
        f"get_allowed_transitions({status.value}) "
        f"returned {result!r}, expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# 7. WorkflowEngine.can_transition (async, does not need DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_transition_valid() -> None:
    """can_transition returns True for a valid transition."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(BladeStatus.CREATED, BladeStatus.OH_INSPECTION)
    assert result is True


@pytest.mark.asyncio
async def test_can_transition_invalid() -> None:
    """can_transition returns False for an invalid transition."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(BladeStatus.CREATED, BladeStatus.COMPLETED)
    assert result is False


@pytest.mark.asyncio
async def test_can_transition_terminal_state() -> None:
    """can_transition returns False for any transition FROM COMPLETED."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    for tgt in ALL_STATUSES:
        result = await engine.can_transition(BladeStatus.COMPLETED, tgt)
        assert result is False, f"COMPLETED → {tgt.value} should be False"


# ---------------------------------------------------------------------------
# 7b. HPTR-only shortcut edges (blade never leaves OH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hptr_can_skip_straight_to_slot_assigned() -> None:
    """HPTR blades may go MEASUREMENTS_RECORDED → SLOT_ASSIGNED directly."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(
        BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.SLOT_ASSIGNED, BladeType.HPTR
    )
    assert result is True


@pytest.mark.asyncio
async def test_lptr_cannot_skip_straight_to_slot_assigned() -> None:
    """LPTR blades must NOT gain the HPTR-only shortcut edge."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(
        BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.SLOT_ASSIGNED, BladeType.LPTR
    )
    assert result is False


@pytest.mark.asyncio
async def test_no_blade_type_preserves_base_map_only() -> None:
    """Omitting blade_type must not unlock any HPTR-only edge (backward-compat default)."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(
        BladeStatus.MEASUREMENTS_RECORDED, BladeStatus.SLOT_ASSIGNED
    )
    assert result is False


@pytest.mark.asyncio
async def test_hptr_can_skip_balancing_completed_to_final_verification() -> None:
    """HPTR blades may go BALANCING_COMPLETED → FINAL_VERIFICATION directly (never RETURNED_TO_OH)."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(
        BladeStatus.BALANCING_COMPLETED, BladeStatus.FINAL_VERIFICATION, BladeType.HPTR
    )
    assert result is True


@pytest.mark.asyncio
async def test_lptr_cannot_skip_balancing_completed_to_final_verification() -> None:
    """LPTR blades must still go through RETURNED_TO_OH before FINAL_VERIFICATION."""
    engine = WorkflowEngine(db=None)  # type: ignore[arg-type]
    result = await engine.can_transition(
        BladeStatus.BALANCING_COMPLETED, BladeStatus.FINAL_VERIFICATION, BladeType.LPTR
    )
    assert result is False


def test_extra_transitions_only_defined_for_hptr() -> None:
    """EXTRA_TRANSITIONS_BY_TYPE must not define shortcut edges for LPTR."""
    assert BladeType.LPTR not in EXTRA_TRANSITIONS_BY_TYPE
    assert BladeType.HPTR in EXTRA_TRANSITIONS_BY_TYPE


# ---------------------------------------------------------------------------
# 8. All statuses appear in ALLOWED_TRANSITIONS (map is exhaustive)
# ---------------------------------------------------------------------------


def test_all_statuses_have_entry_in_allowed_transitions() -> None:
    """Every BladeStatus must have an explicit entry in ALLOWED_TRANSITIONS."""
    missing = [s for s in BladeStatus if s not in ALLOWED_TRANSITIONS]
    assert missing == [], (
        f"These statuses have no entry in ALLOWED_TRANSITIONS: "
        f"{[s.value for s in missing]}"
    )


# ---------------------------------------------------------------------------
# 9. Transition map is internally consistent (no self-loops)
# ---------------------------------------------------------------------------


def test_no_self_loops_in_transition_map() -> None:
    """No status should list itself as a valid next state."""
    self_loops = [
        s for s, targets in ALLOWED_TRANSITIONS.items() if s in targets
    ]
    assert self_loops == [], (
        f"Self-loop transitions found: {[s.value for s in self_loops]}"
    )
