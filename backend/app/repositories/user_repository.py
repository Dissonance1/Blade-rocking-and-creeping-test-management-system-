"""
UserRepository — all database operations for User, Role, and UserRole entities.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Role, User, UserRole
from app.repositories.base import BaseRepository
from app.schemas.user import UserCreate, UserUpdate

log = structlog.get_logger(__name__)


class UserRepository(BaseRepository[User, UserCreate, UserUpdate]):
    """Async repository for the ``users`` table."""

    model = User

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    async def get_by_email(self, email: str) -> User | None:
        """Return the active user with *email*, or ``None``."""
        stmt = select(User).where(
            User.email == email.lower(),
            User.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """Return the active user with *username*, or ``None``."""
        stmt = select(User).where(
            User.username == username.lower(),
            User.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_roles(self, user_id: uuid.UUID) -> User | None:
        """
        Return the user with *user_id* with ``user_roles`` and their nested
        ``Role``/``Permission`` relationships eagerly loaded.
        """
        stmt = (
            select(User)
            .options(
                selectinload(User.user_roles).selectinload(UserRole.role),
            )
            .where(
                User.id == user_id,
                User.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Role management
    # ------------------------------------------------------------------

    async def assign_role(
        self,
        user_id: uuid.UUID,
        role_name: str,
        assigned_by: uuid.UUID,
    ) -> UserRole:
        """
        Assign *role_name* to the user identified by *user_id*.

        Returns the new :class:`~app.models.user.UserRole` association object.
        Raises :class:`ValueError` if the user or role does not exist, or if
        the user already holds that role.
        """
        user = await self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        role_stmt = select(Role).where(Role.name == role_name)
        role = (await self.db.execute(role_stmt)).scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' does not exist")

        # Idempotency guard
        existing_stmt = select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
        )
        existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            log.info(
                "user_repository.assign_role.already_exists",
                user_id=str(user_id),
                role=role_name,
            )
            return existing

        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            assigned_at=datetime.now(timezone.utc),
            assigned_by=assigned_by,
        )
        self.db.add(user_role)
        await self.db.flush()
        await self.db.refresh(user_role)

        log.info(
            "user_repository.assign_role",
            user_id=str(user_id),
            role=role_name,
            assigned_by=str(assigned_by),
        )
        return user_role

    async def remove_role(self, user_id: uuid.UUID, role_name: str) -> bool:
        """
        Remove *role_name* from the user.

        Returns ``True`` if a row was deleted, ``False`` if the user did not
        hold that role.
        """
        role_stmt = select(Role).where(Role.name == role_name)
        role = (await self.db.execute(role_stmt)).scalar_one_or_none()
        if role is None:
            return False

        user_role_stmt = select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
        )
        user_role = (await self.db.execute(user_role_stmt)).scalar_one_or_none()
        if user_role is None:
            return False

        await self.db.delete(user_role)
        await self.db.flush()

        log.info(
            "user_repository.remove_role",
            user_id=str(user_id),
            role=role_name,
        )
        return True

    # ------------------------------------------------------------------
    # Activity tracking
    # ------------------------------------------------------------------

    async def update_last_login(self, user_id: uuid.UUID) -> None:
        """Stamp ``last_login`` to *now* for the given user."""
        user = await self.get(user_id)
        if user is None:
            log.warning("user_repository.update_last_login.not_found", user_id=str(user_id))
            return

        user.last_login = datetime.now(timezone.utc)
        self.db.add(user)
        await self.db.flush()
        log.debug("user_repository.last_login_updated", user_id=str(user_id))
