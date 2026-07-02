from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


# ---------------------------------------------------------------------------
# Key function
# ---------------------------------------------------------------------------


def _resolve_key(request: Request) -> str:
    """Return a rate-limit key that distinguishes authenticated from anonymous.

    Authenticated callers are keyed by their JWT subject (user UUID) so that
    multiple devices of the same user share a single counter.  Unauthenticated
    callers are keyed by remote IP.
    """
    auth: str | None = request.headers.get("Authorization", "")
    if auth and auth.startswith("Bearer "):
        import jwt  # noqa: PLC0415
        from jwt.exceptions import PyJWTError  # noqa: PLC0415
        from app.core.config import settings  # noqa: PLC0415

        token = auth.removeprefix("Bearer ").strip()
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False},
            )
            sub: str | None = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except PyJWTError:
            pass

    return get_remote_address(request)


# ---------------------------------------------------------------------------
# Limiter instance (import this in routers via `from app.middleware.rate_limit import limiter`)
# ---------------------------------------------------------------------------

limiter = Limiter(
    key_func=_resolve_key,
    default_limits=["100/minute"],
    headers_enabled=True,           # Adds X-RateLimit-* headers to responses.
    swallow_errors=False,
)


# ---------------------------------------------------------------------------
# Per-tier limit strings
# ---------------------------------------------------------------------------

AUTHENTICATED_LIMIT: str = "100/minute"
ANONYMOUS_LIMIT: str = "20/minute"
AUTH_ENDPOINT_LIMIT: str = "5/minute"


# ---------------------------------------------------------------------------
# Application wiring helper
# ---------------------------------------------------------------------------


def configure_rate_limiting(app: FastAPI) -> None:
    """Attach the limiter and its error handler to *app*.

    Call this once during application startup::

        from app.middleware.rate_limit import configure_rate_limiting
        configure_rate_limiting(app)
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)


# ---------------------------------------------------------------------------
# Convenience decorators / dependencies for per-route overrides
# ---------------------------------------------------------------------------


def rate_limit_authenticated(limit: str = AUTHENTICATED_LIMIT) -> Callable:
    """Decorator for routes that should use the authenticated user limit."""
    return limiter.limit(limit, key_func=_resolve_key)


def rate_limit_anonymous(limit: str = ANONYMOUS_LIMIT) -> Callable:
    """Decorator for routes accessible without authentication."""
    return limiter.limit(limit, key_func=get_remote_address)


def rate_limit_auth_endpoint(limit: str = AUTH_ENDPOINT_LIMIT) -> Callable:
    """Strict rate limit for login / token-refresh endpoints."""
    return limiter.limit(limit, key_func=get_remote_address)
