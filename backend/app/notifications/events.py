"""
Notification event constants and payload builders.

All event-type strings used throughout the application are defined here
so that callers never have to hard-code raw strings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.blade import Blade
    from app.models.user import User

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

BLADE_RECEIVED: str = "blade_received"
"""A new blade has been received at the facility."""

SLOT_PENDING: str = "slot_pending"
"""A blade is awaiting slot allocation in the OH (Overhead) station."""

BALANCING_DONE: str = "balancing_done"
"""Dynamic balancing measurement has been completed for a blade."""

BLADE_REJECTED: str = "blade_rejected"
"""A blade has failed QC and been rejected."""

VERIFICATION_PENDING: str = "verification_pending"
"""A blade is awaiting supervisor verification before proceeding."""

WORKFLOW_UPDATED: str = "workflow_updated"
"""A blade's workflow stage has been updated."""

# Convenience tuple for validation / enumeration.
ALL_EVENTS: tuple[str, ...] = (
    BLADE_RECEIVED,
    SLOT_PENDING,
    BALANCING_DONE,
    BLADE_REJECTED,
    VERIFICATION_PENDING,
    WORKFLOW_UPDATED,
)

# ---------------------------------------------------------------------------
# Human-readable messages per event type
# ---------------------------------------------------------------------------

_EVENT_MESSAGES: dict[str, str] = {
    BLADE_RECEIVED: "New blade received — assembly queued",
    SLOT_PENDING: "Blade awaiting slot allocation",
    BALANCING_DONE: "Balancing complete — ready for next stage",
    BLADE_REJECTED: "Blade rejected — review required",
    VERIFICATION_PENDING: "Blade pending supervisor verification",
    WORKFLOW_UPDATED: "Blade workflow status updated",
}

_EVENT_DESCRIPTIONS: dict[str, str] = {
    BLADE_RECEIVED: (
        "Blade {serial} has been received and is queued for assembly processing."
    ),
    SLOT_PENDING: (
        "Blade {serial} requires a slot allocation in the overhead station."
    ),
    BALANCING_DONE: (
        "Dynamic balancing for blade {serial} is complete and awaits the next stage."
    ),
    BLADE_REJECTED: (
        "Blade {serial} has been rejected by {actor}. Please review the rejection notes."
    ),
    VERIFICATION_PENDING: (
        "Blade {serial} is awaiting verification approval from a supervisor."
    ),
    WORKFLOW_UPDATED: (
        "Blade {serial} workflow status was updated by {actor}."
    ),
}


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def build_blade_notification_payload(
    event: str,
    blade: Blade,
    actor: User,
) -> dict:
    """
    Build a structured notification payload dict for a blade lifecycle event.

    Parameters
    ----------
    event:
        One of the ``ALL_EVENTS`` string constants defined in this module.
    blade:
        The :class:`~app.models.blade.Blade` ORM instance the event concerns.
    actor:
        The :class:`~app.models.user.User` who triggered the event.

    Returns
    -------
    dict
        A serialisation-ready dictionary with the following keys:

        - ``event_type`` — the event constant string
        - ``blade_id`` — stringified UUID
        - ``serial_number`` — blade serial number (or ``"N/A"``)
        - ``message`` — short human-readable title
        - ``description`` — longer message with serial / actor interpolated
        - ``timestamp`` — ISO-8601 UTC timestamp string
        - ``actor_name`` — display name of the acting user
        - ``actor_id`` — stringified UUID of the acting user
    """
    serial: str = getattr(blade, "serial_number", None) or "N/A"
    actor_name: str = _get_actor_display_name(actor)

    message: str = _EVENT_MESSAGES.get(event, f"Blade event: {event}")
    description_template: str = _EVENT_DESCRIPTIONS.get(
        event, "Blade {serial} event: {event} triggered by {actor}."
    )
    description: str = description_template.format(
        serial=serial,
        actor=actor_name,
        event=event,
    )

    return {
        "event_type": event,
        "blade_id": str(blade.id),
        "serial_number": serial,
        "message": message,
        "description": description,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "actor_name": actor_name,
        "actor_id": str(actor.id),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_actor_display_name(actor: User) -> str:
    """Return the most appropriate display name for *actor*."""
    full_name: str = " ".join(
        filter(
            None,
            [
                getattr(actor, "first_name", None),
                getattr(actor, "last_name", None),
            ],
        )
    ).strip()
    if full_name:
        return full_name
    return getattr(actor, "email", None) or getattr(actor, "username", None) or "System"
