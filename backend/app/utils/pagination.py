"""
Pagination utilities for FastAPI route handlers.

Provides:
* :func:`paginate` — apply skip/limit to a SQLAlchemy ``Select`` statement
* :class:`PaginationParams` — reusable FastAPI dependency that parses and
  validates ``skip`` / ``limit`` query parameters
* :class:`PaginatedResponse` — typed generic wrapper for paginated API responses
"""

from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Low-level helper
# ---------------------------------------------------------------------------


def paginate(query: Select, skip: int, limit: int) -> Select:
    """
    Apply *skip* (OFFSET) and *limit* to a SQLAlchemy ``Select`` statement.

    Parameters
    ----------
    query:
        An existing :class:`sqlalchemy.Select` that has not yet been
        executed.
    skip:
        Number of rows to skip (0-based offset).
    limit:
        Maximum number of rows to return.  Negative values are treated
        as 0; the actual maximum is enforced by the caller or by the
        :class:`PaginationParams` dependency.

    Returns
    -------
    Select
        The modified select statement.

    Example
    -------
    ::

        stmt = select(Blade).order_by(Blade.created_at.desc())
        paginated_stmt = paginate(stmt, skip=20, limit=10)
        result = await db.execute(paginated_stmt)
    """
    if skip < 0:
        skip = 0
    if limit < 0:
        limit = 0
    return query.offset(skip).limit(limit)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


class PaginationParams:
    """
    Reusable FastAPI dependency for ``skip`` / ``limit`` query parameters.

    Usage
    -----
    ::

        from fastapi import Depends
        from app.utils.pagination import PaginationParams

        @router.get("/blades")
        async def list_blades(
            pagination: PaginationParams = Depends(),
            db: AsyncSession = Depends(get_db),
        ):
            stmt = select(Blade).order_by(Blade.created_at.desc())
            blades = await db.execute(paginate(stmt, pagination.skip, pagination.limit))
            ...

    Query parameters
    ----------------
    skip : int, optional
        Number of items to skip. Must be ``>= 0``.  Defaults to ``0``.
    limit : int, optional
        Maximum number of items to return. Must be between ``1`` and
        ``100`` (inclusive).  Defaults to ``20``.
    """

    def __init__(
        self,
        skip: int = Query(default=0, ge=0, description="Number of items to skip."),
        limit: int = Query(
            default=20,
            ge=1,
            le=100,
            description="Maximum number of items to return (1–100).",
        ),
    ) -> None:
        self.skip = skip
        self.limit = limit

    def __repr__(self) -> str:
        return f"PaginationParams(skip={self.skip}, limit={self.limit})"


# ---------------------------------------------------------------------------
# Async count helper
# ---------------------------------------------------------------------------


async def count_query(db: AsyncSession, base_select: Select) -> int:
    """
    Return the total count for *base_select* without applying pagination.

    Wraps the query in a ``SELECT count(*) FROM (<base_select>)`` subquery
    so that GROUP BY, DISTINCT, etc. are respected.

    Parameters
    ----------
    db:
        Open async SQLAlchemy session.
    base_select:
        The select statement *before* skip/limit are applied.

    Returns
    -------
    int
        Total number of matching rows.
    """
    count_stmt = select(func.count()).select_from(base_select.subquery())
    result = await db.execute(count_stmt)
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Generic paginated response schema
# ---------------------------------------------------------------------------


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic JSON envelope for paginated list endpoints.

    Example response body
    ---------------------
    ::

        {
            "items": [...],
            "total": 150,
            "skip": 20,
            "limit": 10,
            "has_more": true
        }
    """

    items: list[T]
    total: int
    skip: int
    limit: int
    has_more: bool

    @classmethod
    def build(
        cls,
        items: list[T],
        total: int,
        skip: int,
        limit: int,
    ) -> "PaginatedResponse[T]":
        """Convenience constructor that computes ``has_more`` automatically."""
        return cls(
            items=items,
            total=total,
            skip=skip,
            limit=limit,
            has_more=(skip + len(items)) < total,
        )

    model_config = {"arbitrary_types_allowed": True}
