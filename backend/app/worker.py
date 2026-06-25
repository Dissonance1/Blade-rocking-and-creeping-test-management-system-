"""
Celery application instance.

Import this module to get the configured Celery app:
    from app.worker import celery_app
"""
from __future__ import annotations

import os

from celery import Celery

# ---------------------------------------------------------------------------
# Read broker / backend from env (mirrors .env values, with safe defaults)
# ---------------------------------------------------------------------------
_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL",
    os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
)
_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND",
    os.environ.get("REDIS_URL", "redis://localhost:6379/2"),
)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------
celery_app = Celery(
    "blade_rocking",
    broker=_BROKER_URL,
    backend=_RESULT_BACKEND,
    include=["app.reports.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "reports.*": {"queue": "reports"},
    },
)

# Expose as `celery` so `celery -A app.worker worker` finds it automatically
celery = celery_app
