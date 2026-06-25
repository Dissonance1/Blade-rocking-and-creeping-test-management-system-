"""
User management endpoints (SUPER_ADMIN only).

POST   /users/                         — create user
GET    /users/                         — list users (paginated)
GET    /users/{user_id}                — get user detail
PUT    /users/{user_id}                — update user
DELETE /users/{user_id}                — soft delete user
POST   /users/{user_id}/roles          — assign role(s)
DELETE /users/{user_id}/roles/{role_name} — remove a role
POST   /users/{user_id}/lock           — lock user account
POST   /users/{user_id}/unlock         — unlock user account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.enums import RoleName
from app.schemas.base import PaginatedResponse, StatusResponse
from app.schemas.user import UserCreate, UserListItem, UserResponse, UserUpdate

logger = structlog.get_logger(__name__)
router = APIRouter()

# All endpoints require SUPER_ADMIN
_admin_dep = Depends(require_roles("SUPER_ADMIN"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_or_404(user_id: uuid.UUID, db: AsyncSession) -> Any:
    from app.models.user import User, UserRole as UserRoleModel
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .options(selectinload(User.user_roles).selectinload(UserRoleModel.role))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    return user


async def _get_role_by_name(role_name: str, db: AsyncSession) -> Any:
    from app.models.user import Role

    result = await db.execute(
        select(Role).where(Role.name == role_name)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role '{role_name}' not found",
        )
    return role


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
)
async def create_user(
    body: UserCreate,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Create a new application user account.

    Email and username must be unique across active users.  The supplied
    ``password`` is bcrypt-hashed before storage.

    Raises:
        HTTP 409 — email or username already in use.
    """
    from app.models.user import User, UserRole, Role

    # Uniqueness check
    existing_email = (
        await db.execute(
            select(User).where(User.email == body.email, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{body.email}' already exists",
        )

    existing_username = (
        await db.execute(
            select(User).where(User.username == body.username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken",
        )

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password.get_secret_value()),
        full_name=body.full_name,
        station_id=body.station_id,
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.flush()

    # Assign roles
    for role_name in body.role_names:
        role = await _get_role_by_name(role_name.value, db)
        user_role = UserRole(
            user_id=user.id,
            role_id=role.id,
            assigned_at=datetime.now(timezone.utc),
            assigned_by=current_user.id,
        )
        db.add(user_role)

    await db.commit()

    logger.info(
        "user_created",
        created_user_id=str(user.id),
        by=str(current_user.id),
        email=user.email,
    )
    # Re-fetch with relationships so Pydantic can serialize UserResponse
    return await _get_user_or_404(user.id, db)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=PaginatedResponse[UserListItem],
    status_code=status.HTTP_200_OK,
    summary="List all users (paginated)",
)
async def list_users(
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Search email or username"),
) -> Any:
    """
    Return a paginated list of all user accounts.

    Optionally filter by ``is_active`` status and search by email/username
    (case-insensitive partial match).
    """
    from app.models.user import User, UserRole as UserRoleModel
    from sqlalchemy.orm import selectinload

    conditions = [User.deleted_at.is_(None)]
    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))
    if search:
        like = f"%{search}%"
        from sqlalchemy import or_
        conditions.append(or_(User.email.ilike(like), User.username.ilike(like)))

    total: int = (
        await db.execute(select(func.count()).select_from(User).where(*conditions))
    ).scalar_one()

    rows = list(
        (
            await db.execute(
                select(User)
                .where(*conditions)
                .options(selectinload(User.user_roles).selectinload(UserRoleModel.role))
                .order_by(User.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    # Build list items with populated role_names and last_login
    items = []
    for u in rows:
        role_names = [ur.role.name for ur in (u.user_roles or []) if ur.role]
        items.append(
            UserListItem(
                id=u.id,
                email=u.email,
                username=u.username,
                full_name=u.full_name,
                is_active=u.is_active,
                station_id=u.station_id,
                role_names=role_names,
                created_at=u.created_at,
                last_login=u.last_login,
            )
        )

    page = skip // limit + 1 if limit > 0 else 1
    return PaginatedResponse(items=items, total=total, page=page, page_size=limit)


# ---------------------------------------------------------------------------
# GET /{user_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full user detail",
)
async def get_user(
    user_id: uuid.UUID,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Return the full record for a single user, including roles."""
    return await _get_user_or_404(user_id, db)


# ---------------------------------------------------------------------------
# PUT /{user_id}
# ---------------------------------------------------------------------------


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a user account",
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Update mutable fields of an existing user account.

    Raises:
        HTTP 404 — user not found.
        HTTP 409 — new email/username already in use.
    """
    from app.models.user import User

    user = await _get_user_or_404(user_id, db)
    update_data = body.model_dump(exclude_unset=True)

    # Uniqueness checks for email/username changes
    if "email" in update_data and update_data["email"] != user.email:
        conflict = (
            await db.execute(
                select(User).where(
                    User.email == update_data["email"],
                    User.id != user_id,
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{update_data['email']}' is already in use",
            )

    if "username" in update_data and update_data["username"] != user.username:
        conflict = (
            await db.execute(
                select(User).where(
                    User.username == update_data["username"],
                    User.id != user_id,
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{update_data['username']}' is already taken",
            )

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    logger.info("user_updated", user_id=str(user_id), by=str(current_user.id))
    return user


# ---------------------------------------------------------------------------
# DELETE /{user_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{user_id}",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a user account",
)
async def delete_user(
    user_id: uuid.UUID,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Soft-delete a user account by setting ``deleted_at`` to the current
    timestamp.

    The account is deactivated immediately; all historical records
    (workflow logs, measurements) referencing this user are preserved.

    Raises:
        HTTP 400 — attempting to delete the current super-admin account.
        HTTP 404 — user not found.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    user = await _get_user_or_404(user_id, db)
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False

    await db.commit()

    logger.info("user_deleted", user_id=str(user_id), by=str(current_user.id))
    return StatusResponse(message=f"User {user_id} deleted successfully")


# ---------------------------------------------------------------------------
# POST /{user_id}/roles
# ---------------------------------------------------------------------------


@router.post(
    "/{user_id}/roles",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign one or more roles to a user",
)
async def assign_roles(
    user_id: uuid.UUID,
    role_names: list[RoleName],
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Assign one or more roles to an existing user.

    Roles already assigned are silently skipped (idempotent).

    Raises:
        HTTP 404 — user or role not found.
    """
    from app.models.user import User, UserRole

    user = await _get_user_or_404(user_id, db)
    existing_role_names = {ur.role.name for ur in user.user_roles}

    for rn in role_names:
        if rn.value in existing_role_names:
            continue
        role = await _get_role_by_name(rn.value, db)
        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            assigned_at=datetime.now(timezone.utc),
            assigned_by=current_user.id,
        )
        db.add(user_role)

    await db.commit()

    logger.info(
        "roles_assigned",
        user_id=str(user_id),
        roles=[rn.value for rn in role_names],
        by=str(current_user.id),
    )
    # Re-fetch with relationships loaded so Pydantic can serialize UserResponse
    return await _get_user_or_404(user_id, db)


# ---------------------------------------------------------------------------
# DELETE /{user_id}/roles/{role_name}
# ---------------------------------------------------------------------------


@router.delete(
    "/{user_id}/roles/{role_name}",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a specific role from a user",
)
async def remove_role(
    user_id: uuid.UUID,
    role_name: RoleName,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Remove a role assignment from a user.

    Raises:
        HTTP 404 — user not found or user does not have the specified role.
    """
    from app.models.user import UserRole, Role

    user = await _get_user_or_404(user_id, db)
    role = await _get_role_by_name(role_name.value, db)

    result = await db.execute(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
        )
    )
    user_role = result.scalar_one_or_none()
    if user_role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User does not have role '{role_name.value}'",
        )

    await db.delete(user_role)
    await db.commit()

    logger.info(
        "role_removed",
        user_id=str(user_id),
        role=role_name.value,
        by=str(current_user.id),
    )
    return StatusResponse(message=f"Role '{role_name.value}' removed from user")


# ---------------------------------------------------------------------------
# POST /{user_id}/lock
# ---------------------------------------------------------------------------


@router.post(
    "/{user_id}/lock",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Lock a user account (prevent login)",
)
async def lock_user(
    user_id: uuid.UUID,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Deactivate a user account without deleting it.

    The user will receive HTTP 401 on subsequent login attempts.

    Raises:
        HTTP 400 — attempting to lock the current user's account.
        HTTP 404 — user not found.
        HTTP 409 — account is already locked.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot lock your own account",
        )

    user = await _get_user_or_404(user_id, db)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User account is already locked/inactive",
        )

    user.is_active = False
    await db.commit()

    logger.info("user_locked", user_id=str(user_id), by=str(current_user.id))
    return StatusResponse(message=f"User {user_id} account locked")


# ---------------------------------------------------------------------------
# POST /{user_id}/unlock
# ---------------------------------------------------------------------------


@router.post(
    "/{user_id}/unlock",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Unlock a locked user account",
)
async def unlock_user(
    user_id: uuid.UUID,
    current_user: Annotated[Any, _admin_dep],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """
    Re-activate a previously locked user account.

    Raises:
        HTTP 404 — user not found.
        HTTP 409 — account is already active.
    """
    from app.models.user import User

    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User account is already active",
        )

    user.is_active = True
    await db.commit()

    logger.info("user_unlocked", user_id=str(user_id), by=str(current_user.id))
    return StatusResponse(message=f"User {user_id} account unlocked")
