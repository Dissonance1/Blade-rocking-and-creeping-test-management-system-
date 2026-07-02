"""
Top-level v1 API router.

All sub-routers are included here with their respective URL prefixes and
OpenAPI tags.  The router itself is included in ``app.main`` under the
``/api/v1`` prefix defined by ``settings.API_V1_STR``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    assembly,
    audit_logs,
    auth,
    batches,
    blades,
    dti,
    measurements,
    notifications,
    ocr,
    reports,
    slots,
    stations,
    sync,
    users,
    weighing,
    workflows,
)

api_router = APIRouter()

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["auth"],
)

# ---------------------------------------------------------------------------
# Blade CRUD + workflow actions
# ---------------------------------------------------------------------------
api_router.include_router(
    blades.router,
    prefix="/blades",
    tags=["blades"],
)

# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------
api_router.include_router(
    measurements.router,
    prefix="",       # Provides both /blades/{blade_id}/measurements and /measurements/{id}
    tags=["measurements"],
)

# ---------------------------------------------------------------------------
# Slot allocation
# ---------------------------------------------------------------------------
api_router.include_router(
    slots.router,
    prefix="/slots",
    tags=["slots"],
)

# ---------------------------------------------------------------------------
# Workflow history + dashboard stats
# ---------------------------------------------------------------------------
api_router.include_router(
    workflows.router,
    prefix="/workflows",
    tags=["workflows"],
)

# ---------------------------------------------------------------------------
# Notifications + WebSocket push
# ---------------------------------------------------------------------------
api_router.include_router(
    notifications.router,
    prefix="/notifications",
    tags=["notifications"],
)

# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
api_router.include_router(
    reports.router,
    prefix="/reports",
    tags=["reports"],
)

# ---------------------------------------------------------------------------
# User management (SUPER_ADMIN only)
# ---------------------------------------------------------------------------
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["users"],
)

# ---------------------------------------------------------------------------
# OCR scanning
# ---------------------------------------------------------------------------
api_router.include_router(
    ocr.router,
    prefix="/ocr",
    tags=["ocr"],
)

# ---------------------------------------------------------------------------
# Station management
# ---------------------------------------------------------------------------
api_router.include_router(
    stations.router,
    prefix="/stations",
    tags=["stations"],
)

# ---------------------------------------------------------------------------
# Batch workflow
# ---------------------------------------------------------------------------
api_router.include_router(
    batches.router,
    prefix="/batches",
    tags=["batches"],
)

# ---------------------------------------------------------------------------
# Audit logs (SUPER_ADMIN only)
# ---------------------------------------------------------------------------
api_router.include_router(
    audit_logs.router,
    prefix="/audit-logs",
    tags=["audit-logs"],
)

# ---------------------------------------------------------------------------
# Weighing machine WebSocket
# ---------------------------------------------------------------------------
api_router.include_router(
    weighing.router,
    prefix="/weighing",
    tags=["weighing"],
)

# ---------------------------------------------------------------------------
# DTI gauge WebSocket
# ---------------------------------------------------------------------------
api_router.include_router(
    dti.router,
    prefix="/dti",
    tags=["dti"],
)

# ---------------------------------------------------------------------------
# Assembly station workflow (720 Hanger)
# ---------------------------------------------------------------------------
api_router.include_router(
    assembly.router,
    prefix="/assembly",
    tags=["assembly"],
)

# ---------------------------------------------------------------------------
# LAN sync — OH PC exposes blade data for Assembly to pull over LAN
# ---------------------------------------------------------------------------
api_router.include_router(
    sync.router,
    prefix="/sync",
    tags=["sync"],
)
