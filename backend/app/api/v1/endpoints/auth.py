"""
Authentication endpoints.

POST /auth/login          — email + password → Token pair (+ httponly refresh cookie)
POST /auth/refresh        — refresh token → new access token
POST /auth/logout         — invalidate refresh token
GET  /auth/me             — current user profile
PATCH /auth/me/profile    — update own profile (full_name)
POST /auth/me/change-password — update own password
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
# Rate limiting for /login and /refresh is enforced at the NGINX layer
# (auth_limit zone: 5 requests/minute per IP — see nginx/nginx.conf)
from app.schemas.base import StatusResponse
from app.schemas.user import (
    ChangePasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    Token,
    UserResponse,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_MAX_AGE = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400  # seconds


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach a secure HttpOnly refresh-token cookie to *response*."""
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=token,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.ENVIRONMENT != "dev",
        samesite="lax",
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Delete the refresh-token cookie."""
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
    )


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT tokens",
)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """
    Exchange email + password for a JWT access token and a long-lived
    refresh token.

    The refresh token is returned both in the JSON body **and** as an
    HttpOnly cookie (path ``/api/v1/auth``) for browser clients that can
    leverage automatic cookie handling.

    Raises:
        HTTP 401 — invalid credentials or inactive account.
    """
    from app.models.user import User  # late import to avoid circular deps

    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active.is_(True))
    )
    user: User | None = result.scalar_one_or_none()

    if user is None or not verify_password(
        body.password.get_secret_value(), user.hashed_password
    ):
        logger.warning("login_failed", email=body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong credentials given, please check your email and password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Persist last-login timestamp (best-effort, non-blocking).
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(last_login=datetime.now(timezone.utc))
    )

    role_names: list[str] = [ur.role.name for ur in user.user_roles]
    token_data: dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "roles": role_names,
        "is_superuser": user.is_superuser,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    _set_refresh_cookie(response, refresh_token)

    logger.info("login_success", user_id=str(user.id), email=user.email)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Obtain a new access token using a refresh token",
)
async def refresh_token(
    request: Request,
    response: Response,
    body: RefreshTokenRequest | None = None,
    refresh_token_cookie: Annotated[str | None, Cookie(alias=_REFRESH_COOKIE_NAME)] = None,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Exchange a valid refresh token for a new JWT access + refresh token pair.

    The refresh token may be supplied either in the JSON body
    (``refresh_token`` field) or via the HttpOnly cookie set by ``/login``.
    The cookie takes precedence when both are present.

    Raises:
        HTTP 401 — token missing, invalid, or expired.
        HTTP 401 — user not found or inactive.
    """
    from app.models.user import User

    raw_token: str | None = refresh_token_cookie or (body.refresh_token if body else None)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(raw_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — expected refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from uuid import UUID

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user: User | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role_names: list[str] = [ur.role.name for ur in user.user_roles]
    token_data: dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "roles": role_names,
        "is_superuser": user.is_superuser,
    }

    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    _set_refresh_cookie(response, new_refresh_token)

    logger.info("token_refreshed", user_id=str(user.id))

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Invalidate the current session",
)
async def logout(
    request: Request,
    response: Response,
    current_user: Annotated[Any, Depends(get_current_user)],
) -> StatusResponse:
    """
    Log out the authenticated user.

    Clears the HttpOnly refresh-token cookie AND blacklists the JWT's JTI
    in Redis so the token cannot be reused even before its natural expiry.
    """
    _clear_refresh_cookie(response)

    # Blacklist the current access token so it cannot be reused post-logout
    try:
        from app.core.jwt_blacklist import blacklist_token
        from app.core.security import decode_token

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]
            payload = decode_token(raw_token)
            redis_client = getattr(request.app.state, "redis", None)
            if redis_client:
                await blacklist_token(redis_client, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("logout_blacklist_error", error=str(exc))

    logger.info("logout", user_id=str(current_user.id))
    return StatusResponse(message="Logged out successfully")


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the current authenticated user's profile",
)
async def get_me(
    current_user: Annotated[Any, Depends(get_current_user)],
) -> Any:
    """
    Return the full profile of the currently authenticated user,
    including their roles and permissions.
    """
    return current_user


# ---------------------------------------------------------------------------
# PATCH /me/profile
# ---------------------------------------------------------------------------


@router.patch(
    "/me/profile",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update the authenticated user's own profile",
)
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Update self-service profile fields (currently just ``full_name``) for
    the currently authenticated user.

    Mutates the already role-loaded ``current_user`` in place rather than
    re-fetching, since a plain (non-eager-loaded) lookup would drop the
    ``roles`` relationship needed to serialize the response.
    """
    current_user.full_name = body.full_name
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user, attribute_names=["full_name", "updated_at"])

    logger.info("profile_updated", user_id=str(current_user.id))
    return current_user


# ---------------------------------------------------------------------------
# POST /me/change-password
# ---------------------------------------------------------------------------


@router.post(
    "/me/change-password",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Change the authenticated user's own password",
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Update the password for the currently authenticated user.

    The caller must supply the correct current password, the desired new
    password, and a confirmation of the new password.

    Raises:
        HTTP 400 — current password is incorrect.
    """
    from app.models.user import User

    if not verify_password(
        body.current_password.get_secret_value(),
        current_user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    new_hashed = hash_password(body.new_password.get_secret_value())
    await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(hashed_password=new_hashed)
    )

    logger.info("password_changed", user_id=str(current_user.id))
    return StatusResponse(message="Password updated successfully")
