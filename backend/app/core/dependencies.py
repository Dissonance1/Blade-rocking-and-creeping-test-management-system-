from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _get_user_model():  # noqa: ANN202
    from app.models.user import User  # noqa: PLC0415
    return User


def _get_user_role_model():  # noqa: ANN202
    from app.models.user import UserRole, Role  # noqa: PLC0415
    return UserRole, Role


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Resolve the JWT bearer token to a User ORM instance with roles loaded."""
    from app.core.jwt_blacklist import is_blacklisted

    payload = decode_token(token)

    # Reject tokens explicitly blacklisted on logout (uses app.state.redis)
    jti: str | None = payload.get("jti")
    if jti:
        try:
            redis_client = getattr(request.app.state, "redis", None)
            if redis_client and await is_blacklisted(redis_client, jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception:
            pass  # Redis unavailable — fail open

    user_id_raw: str | None = payload.get("sub")
    if user_id_raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(user_id_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        )

    User = _get_user_model()
    UserRole, Role = _get_user_role_model()
    result = await db.execute(
        select(User)
        .where(User.id == user_id, User.is_active.is_(True))
        .options(
            selectinload(User.user_roles).selectinload(UserRole.role)
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_active_superuser(
    current_user: Any = Depends(get_current_user),
) -> Any:
    if not getattr(current_user, "is_superuser", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return current_user


def _user_role_names(user: Any) -> list[str]:
    """Extract role name strings from a User ORM instance."""
    try:
        return [ur.role.name for ur in (user.user_roles or []) if ur.role]
    except Exception:
        return []


def require_roles(*roles: str) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Return a dependency that enforces role membership.

    Usage::

        @router.post("/admin/something")
        async def admin_action(
            _: User = Depends(require_roles("SUPER_ADMIN")),
        ):
            ...
    """

    async def _check_roles(
        current_user: Any = Depends(get_current_user),
    ) -> Any:
        user_roles = _user_role_names(current_user)
        if not any(r in roles for r in user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied. Required role(s): {', '.join(roles)}. "
                    f"Your roles: {user_roles}."
                ),
            )
        return current_user

    return _check_roles  # type: ignore[return-value]
