"""
User, Role, Permission, and UserRole models.

Tables: users, roles, permissions, role_permissions (M2M), user_roles
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Table,
    Column,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, SoftDeleteMixin
from app.models.enums import RoleName


# ---------------------------------------------------------------------------
# M2M association table: roles <-> permissions
# ---------------------------------------------------------------------------

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------

class Permission(UUIDPrimaryKeyMixin, Base):
    """Granular permission record (resource + action pair)."""

    __tablename__ = "permissions"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Back-populates
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    def __repr__(self) -> str:
        return f"<Permission {self.resource}:{self.action}>"


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class Role(UUIDPrimaryKeyMixin, Base):
    """Application role with an enumerated name."""

    __tablename__ = "roles"

    name: Mapped[RoleName] = mapped_column(
        SAEnum(RoleName, name="rolename", create_type=True),
        unique=True,
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    permissions: Mapped[list[Permission]] = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="role",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<Role {self.name.value}>"


# ---------------------------------------------------------------------------
# UserRole (association object — carries assigned_at / assigned_by metadata)
# ---------------------------------------------------------------------------

class UserRole(Base):
    """Associates a user with a role, tracking who assigned it and when."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="user_roles",
        lazy="noload",
    )
    role: Mapped[Role] = relationship(
        "Role",
        back_populates="user_roles",
        lazy="selectin",
    )
    assigner: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[assigned_by],
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<UserRole user={self.user_id} role={self.role_id}>"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Application user account."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # FK to stations (optional — user may be assigned to a specific station)
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole",
        foreign_keys=[UserRole.user_id],
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    station: Mapped["Station | None"] = relationship(  # type: ignore[name-defined]
        "Station",
        foreign_keys=[station_id],
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
        Index("ix_users_deleted_at", "deleted_at"),
    )

    @property
    def roles(self) -> list[Role]:
        return [ur.role for ur in self.user_roles]

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.email})>"


# Avoid circular import — Station is defined in workflow.py
from app.models.workflow import Station  # noqa: E402, F401
