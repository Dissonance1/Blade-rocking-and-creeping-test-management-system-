"""
Domain-wide constants shared across services/repositories/endpoints.
"""

BLADES_PER_WORK_ORDER: int = 90
"""Exactly this many Blade rows are scaffolded for every Work Order —
one blade type per work order, serial-numbered 1..BLADES_PER_WORK_ORDER."""

WEIGHT_TO_GRAMS_FACTOR: float = 1.57
"""Weight (g) = raw scale reading (kg) * this factor."""

STATIC_MOMENT_FACTOR: float = 20.0
"""Static Moment = Weight (g) * this factor."""
