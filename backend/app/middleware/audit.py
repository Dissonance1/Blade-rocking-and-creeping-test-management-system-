from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable
from typing import Any

import structlog
import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

# Endpoints that are never recorded in the audit log.
_SKIP_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/healthz",
        "/ready",
        "/metrics",
        "/favicon.ico",
    }
)


def _extract_user_id(request: Request) -> str | None:
    """Parse the Bearer token from the Authorization header without raising."""
    auth: str | None = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},  # We only want the subject here.
        )
        return payload.get("sub")
    except PyJWTError:
        return None


def _hash_body(body: bytes) -> str:
    """Return a hex SHA-256 digest of *body* for tamper-evidence logging."""
    return hashlib.sha256(body).hexdigest()


async def _persist_audit_log(entry: dict[str, Any]) -> None:
    """Insert one audit log row inside its own short-lived session."""
    sql = text(
        """
        INSERT INTO audit_logs (
            id,
            user_id,
            method,
            path,
            status_code,
            ip_address,
            user_agent,
            request_body_hash,
            duration_ms,
            timestamp
        ) VALUES (
            :id,
            :user_id,
            :method,
            :path,
            :status_code,
            :ip_address,
            :user_agent,
            :request_body_hash,
            :duration_ms,
            NOW()
        )
        """
    )
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sql, entry)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        # Audit logging must never crash the application.
        logger.error(
            "audit_log_persist_failed",
            error=str(exc),
            path=entry.get("path"),
        )


class AuditMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that writes an audit record for every API call.

    Body bytes are read once, cached on the request scope, and forwarded to the
    ASGI app unmodified.  The database write is fire-and-forget — it runs as a
    background task so it does not add latency to the response path.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int = 65_536) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Buffer the request body so we can hash it and still forward it.
        raw_body: bytes = await request.body()
        body_hash = _hash_body(raw_body[: self._max_body_bytes])

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000)

        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        )

        entry: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "user_id": _extract_user_id(request),
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "ip_address": client_ip,
            "user_agent": request.headers.get("User-Agent"),
            "request_body_hash": body_hash,
            "duration_ms": duration_ms,
        }

        # Schedule the DB write as a background coroutine to avoid
        # blocking the response from being sent to the client.
        asyncio.ensure_future(_persist_audit_log(entry))

        return response
