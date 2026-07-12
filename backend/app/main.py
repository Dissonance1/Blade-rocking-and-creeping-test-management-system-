"""
Blade Rocking & Creep Test Management System — FastAPI application entry-point.

Startup sequence
----------------
1. ``lifespan`` runs:   init DB tables (non-prod), connect Redis, configure Celery.
2. Middleware stack:   rate-limit → audit → CORS.
3. Routers:           /api/v1/* sub-routers.
4. Exception handlers: HTTPException, RequestValidationError, WorkflowTransitionError.
5. Utility endpoints:  /health, optionally /metrics.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: F401 – kept for type ref

from app.core.config import settings
from app.db.session import init_db

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class WorkflowTransitionError(Exception):
    """Raised when an invalid blade status transition is attempted."""

    def __init__(self, detail: str, current_status: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.current_status = current_status


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: RUF029
    """Application lifespan: runs startup tasks before yield, teardown after."""

    logger.info(
        "application_startup",
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )

    # ------------------------------------------------------------------ DB
    if settings.ENVIRONMENT != "prod":
        try:
            await init_db()
            logger.info("database_tables_initialised")
        except Exception as exc:  # noqa: BLE001
            logger.error("database_init_failed", error=str(exc))

    # ---------------------------------------------------------------- Redis
    try:
        import redis.asyncio as aioredis  # type: ignore[import]

        redis_client = aioredis.from_url(
            settings.redis_url_str,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.ping()
        app.state.redis = redis_client
        logger.info("redis_connected", url=settings.redis_url_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_connection_failed", error=str(exc))
        app.state.redis = None

    # --------------------------------------------------------------- Celery
    try:
        from celery import Celery  # type: ignore[import]

        celery_app = Celery(
            settings.APP_NAME,
            broker=settings.redis_url_str,
            backend=settings.redis_url_str,
        )
        celery_app.config_from_object(
            {
                "task_serializer": "json",
                "accept_content": ["json"],
                "result_serializer": "json",
                "timezone": "UTC",
                "enable_utc": True,
            }
        )
        app.state.celery = celery_app
        logger.info("celery_configured")
    except ImportError:
        logger.warning("celery_not_installed_skipping_setup")
        app.state.celery = None

    logger.info("application_ready")

    yield  # ← application is now live

    # -------------------------------------------------------------- Teardown
    if getattr(app.state, "redis", None) is not None:
        await app.state.redis.aclose()
        logger.info("redis_disconnected")

    logger.info("application_shutdown")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_application() -> FastAPI:
    """Build, wire, and return the FastAPI application instance."""

    app = FastAPI(
        title="Blade Rocking & Creep Test Management System API",
        version=settings.APP_VERSION,
        description=(
            "REST API for the Blade Rocking & Creep Test Management System.\n\n"
            "This system manages the complete lifecycle of turbine blades through\n"
            "overhaul (OH) inspection, assembly slot allocation, balancing, and\n"
            "final quality verification.  Access is controlled by role-based\n"
            "permissions (SUPER_ADMIN, OH_OPERATOR, ASSEMBLY_OPERATOR, QA_VIEWER)."
        ),
        contact={
            "name": "Meridian Data Labs",
            "email": "amit@meridiandatalabs.com",
        },
        openapi_tags=[
            {"name": "auth", "description": "Authentication and session management"},
            {"name": "blades", "description": "Blade CRUD and workflow actions"},
            {"name": "measurements", "description": "Rocking/creep measurement records"},
            {"name": "slots", "description": "Assembly slot allocation and balancing"},
            {"name": "workflows", "description": "Workflow history and dashboard statistics"},
            {"name": "notifications", "description": "In-app notifications and WebSocket push"},
            {"name": "reports", "description": "Async report generation and download"},
            {"name": "users", "description": "User management (SUPER_ADMIN only)"},
            {"name": "ocr", "description": "OCR scanning for serial/melt numbers and QR codes"},
            {"name": "stations", "description": "Station management"},
        ],
        servers=[
            {"url": "/", "description": "Current environment"},
            {"url": "https://api.blade-rocking.example.com", "description": "Production"},
        ],
        lifespan=lifespan,
        docs_url="/docs" if settings.ENVIRONMENT != "prod" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT != "prod" else None,
    )

    # ----------------------------------------------------------------- CORS
    cors_origins: list[str] = [str(o) for o in settings.CORS_ORIGINS]
    if not cors_origins and settings.ENVIRONMENT == "dev":
        # Allow all origins in development when none are explicitly configured.
        cors_origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    # -------------------------------------------------------- Custom middleware
    from app.middleware.audit import AuditMiddleware
    from app.middleware.rate_limit import configure_rate_limiting

    app.add_middleware(AuditMiddleware)
    configure_rate_limiting(app)

    # ------------------------------------------------------------- Routers
    from app.api.v1.router import api_router

    app.include_router(api_router, prefix=settings.API_V1_STR)

    # ------------------------------------------------------- Exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": exc.detail,
                "errors": [],
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors = []
        for error in exc.errors():
            loc = error.get("loc", [])
            field = ".".join(str(p) for p in loc[1:]) if len(loc) > 1 else str(loc[0]) if loc else None
            field_errors.append(
                {
                    "field": field,
                    "message": error.get("msg", "Validation error"),
                    "code": error.get("type"),
                }
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "message": "Request validation failed",
                "errors": field_errors,
            },
        )

    @app.exception_handler(WorkflowTransitionError)
    async def workflow_transition_error_handler(
        request: Request, exc: WorkflowTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success": False,
                "message": exc.detail,
                "errors": [
                    {
                        "field": "status",
                        "message": exc.detail,
                        "code": "invalid_workflow_transition",
                    }
                ],
                "current_status": exc.current_status,
            },
        )

    # WorkflowEngine.transition() (app.workflows.state_machine) raises its own,
    # differently-shaped WorkflowTransitionError — without this handler it was
    # an unhandled exception (raw 500) instead of a clean 409.
    from app.workflows.state_machine import WorkflowTransitionError as EngineWorkflowTransitionError

    @app.exception_handler(EngineWorkflowTransitionError)
    async def engine_workflow_transition_error_handler(
        request: Request, exc: EngineWorkflowTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success": False,
                "message": str(exc),
                "errors": [
                    {
                        "field": "status",
                        "message": str(exc),
                        "code": "invalid_workflow_transition",
                    }
                ],
                "current_status": exc.current.value,
            },
        )

    # --------------------------------------------------------- Utility routes
    @app.get(
        "/health",
        tags=["health"],
        summary="Health check",
        response_model=dict[str, Any],
    )
    async def health_check() -> dict[str, Any]:
        """Return application liveness / readiness information."""
        return {
            "status": "ok",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    # Optional Prometheus metrics endpoint
    if os.getenv("ENABLE_METRICS", "").lower() in {"1", "true", "yes"}:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore[import]

            Instrumentator(
                should_group_status_codes=False,
                excluded_handlers=["/health", "/metrics"],
            ).instrument(app).expose(app, endpoint="/metrics")
            logger.info("prometheus_metrics_enabled")
        except ImportError:
            logger.warning("prometheus_fastapi_instrumentator_not_installed")

    return app


app: FastAPI = create_application()
