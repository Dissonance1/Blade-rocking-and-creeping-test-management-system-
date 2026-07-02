"""
User, Role, Permission, and Auth schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import (
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.models.enums import RoleName
from app.schemas.base import BaseSchema


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------

class PermissionResponse(BaseSchema):
    """Read-only permission record."""

    id: uuid.UUID
    name: str = Field(..., examples=["blade:read"])
    resource: str = Field(..., examples=["blade"])
    action: str = Field(..., examples=["read"])
    description: str | None = None


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class RoleResponse(BaseSchema):
    """Role with its associated permissions."""

    id: uuid.UUID
    name: RoleName
    description: str | None = None
    permissions: list[PermissionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# User CRUD schemas
# ---------------------------------------------------------------------------

class UserCreate(BaseSchema):
    """Payload for creating a new user account."""

    email: EmailStr = Field(..., description="Unique email address")
    username: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_.-]+$",
        description="Unique alphanumeric username (letters, digits, ., -, _)",
        examples=["john.doe"],
    )
    password: SecretStr = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (will be hashed before storage)",
    )
    full_name: str | None = Field(
        default=None, max_length=255, examples=["John Doe"]
    )
    station_id: uuid.UUID | None = Field(
        default=None,
        description="Optional station the user is primarily assigned to",
    )
    role_names: list[RoleName] = Field(
        default_factory=list,
        description="Roles to assign at creation time",
    )

    @field_validator("username")
    @classmethod
    def username_lowercase(cls, v: str) -> str:
        return v.lower()

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.lower()


class UserUpdate(BaseSchema):
    """Partial update payload — all fields optional."""

    email: EmailStr | None = None
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    station_id: uuid.UUID | None = None

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str | None) -> str | None:
        return v.lower() if v else v

    @field_validator("username")
    @classmethod
    def username_lowercase(cls, v: str | None) -> str | None:
        return v.lower() if v else v


class UserResponse(BaseSchema):
    """Full user representation returned to clients."""

    id: uuid.UUID
    email: str
    username: str
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    station_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None = None
    roles: list[RoleResponse] = Field(default_factory=list)


class UserListItem(BaseSchema):
    """Lightweight user summary used in paginated list responses."""

    id: uuid.UUID
    email: str
    username: str
    full_name: str | None = None
    is_active: bool
    station_id: uuid.UUID | None = None
    role_names: list[str] = Field(default_factory=list)
    created_at: datetime
    last_login: datetime | None = None


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseSchema):
    """Credentials for the /auth/login endpoint."""

    email: EmailStr = Field(..., description="Registered email address")
    password: SecretStr = Field(..., description="Account password")

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.lower()


class Token(BaseSchema):
    """JWT token pair returned after successful authentication."""

    access_token: str = Field(..., description="Short-lived JWT access token")
    refresh_token: str = Field(..., description="Long-lived JWT refresh token")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(
        ..., description="Access token TTL in seconds", examples=[3600]
    )


class TokenData(BaseSchema):
    """Decoded payload of a verified JWT access token."""

    sub: str = Field(..., description="Subject — user UUID as string")
    email: str
    roles: list[str] = Field(default_factory=list)
    is_superuser: bool = False
    jti: str | None = Field(
        default=None, description="JWT ID used for token revocation"
    )


class RefreshTokenRequest(BaseSchema):
    """Payload for the /auth/refresh endpoint."""

    refresh_token: str = Field(..., description="A valid, non-expired refresh token")


class ChangePasswordRequest(BaseSchema):
    """Payload for an authenticated user changing their own password."""

    current_password: SecretStr = Field(
        ..., description="The user's current (existing) password"
    )
    new_password: SecretStr = Field(
        ...,
        min_length=8,
        max_length=128,
        description="The desired new password",
    )
    confirm_new_password: SecretStr = Field(
        ..., description="Must match new_password exactly"
    )

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password.get_secret_value() != self.confirm_new_password.get_secret_value():
            raise ValueError(
                "new_password and confirm_new_password do not match"
            )
        return self
