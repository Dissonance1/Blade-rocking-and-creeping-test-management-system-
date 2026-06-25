"""
Base Pydantic v2 schema primitives shared across the entire application.
"""

from __future__ import annotations

import math
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """
    Project-wide Pydantic base model.

    ``from_attributes=True`` enables ORM-mode so models can be
    constructed directly from SQLAlchemy instances.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
    )


class PaginatedResponse(BaseSchema, Generic[T]):
    """
    Generic paginated list wrapper returned by list endpoints.

    Example response::

        {
          "items": [...],
          "total": 253,
          "page": 2,
          "page_size": 20,
          "pages": 13
        }
    """

    items: list[T] = Field(..., description="Items on the current page")
    total: int = Field(..., ge=0, description="Total number of matching records")
    page: int = Field(..., ge=1, description="Current page number (1-based)")
    page_size: int = Field(..., ge=1, le=500, description="Number of items per page")

    @computed_field  # type: ignore[misc]
    @property
    def pages(self) -> int:
        """Total number of pages."""
        if self.total == 0:
            return 1
        return math.ceil(self.total / self.page_size)


class StatusResponse(BaseSchema):
    """
    Minimal response returned by mutating endpoints that do not
    need to return a full resource representation.

    Example::

        {"success": true, "message": "Blade status updated successfully."}
    """

    success: bool = Field(default=True)
    message: str = Field(..., description="Human-readable result description")


class ErrorDetail(BaseSchema):
    """Single validation or application error item."""

    field: str | None = Field(
        default=None, description="Dot-path of the offending field, if applicable"
    )
    message: str = Field(..., description="Error message")
    code: str | None = Field(
        default=None, description="Machine-readable error code, if applicable"
    )


class ErrorResponse(BaseSchema):
    """Standard error envelope used by exception handlers."""

    success: bool = Field(default=False)
    message: str = Field(..., description="Top-level error summary")
    errors: list[ErrorDetail] = Field(default_factory=list)
