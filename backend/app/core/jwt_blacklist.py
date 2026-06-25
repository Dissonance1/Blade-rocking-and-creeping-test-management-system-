"""
Redis-backed JWT token blacklist.

When a user logs out, their token's JTI (JWT ID) is stored in Redis
with a TTL equal to the remaining token validity. Subsequent requests
with a blacklisted JTI are rejected with 401.
"""
from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_BLACKLIST_PREFIX = "jwt_blacklist:"


def _jti_key(jti: str) -> str:
    return f"{_BLACKLIST_PREFIX}{jti}"


async def blacklist_token(redis_client: Any, payload: dict) -> None:
    """Add a token's JTI to the Redis blacklist with appropriate TTL."""
    jti: str | None = payload.get("jti")
    exp: int | None = payload.get("exp")

    if not jti:
        # Tokens without JTI cannot be individually revoked; log and continue.
        logger.warning("logout_token_missing_jti")
        return

    ttl = max(1, int(exp - time.time())) if exp else 3600
    try:
        await redis_client.setex(_jti_key(jti), ttl, "1")
        logger.info("token_blacklisted", jti=jti, ttl_seconds=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.error("token_blacklist_failed", jti=jti, error=str(exc))


async def is_blacklisted(redis_client: Any, jti: str) -> bool:
    """Return True if the given JTI is in the blacklist."""
    try:
        return bool(await redis_client.exists(_jti_key(jti)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("blacklist_check_failed", jti=jti, error=str(exc))
        return False  # Fail open — better UX than locking out all users on Redis outage
