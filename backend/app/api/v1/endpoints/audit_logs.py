"""
Audit log endpoints.

GET /audit-logs/  — paginated audit log list (SUPER_ADMIN only)
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.schemas.base import PaginatedResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get(
    "/",
    status_code=200,
    summary="List audit log entries (SUPER_ADMIN only)",
)
async def list_audit_logs(
    current_user: Annotated[Any, Depends(require_roles("SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    method: str | None = Query(default=None, description="Filter by HTTP method"),
    user_id: uuid.UUID | None = Query(default=None, description="Filter by acting user"),
    status_code: int | None = Query(default=None, description="Filter by HTTP status code"),
) -> Any:
    """
    Return a reverse-chronological list of all audit log entries.

    Supports filtering by HTTP method, acting user, or response status code.
    Only accessible to SUPER_ADMIN users.
    """
    from app.models.audit_log import AuditLog

    conditions = []
    if method:
        conditions.append(AuditLog.method == method.upper())
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if status_code:
        conditions.append(AuditLog.status_code == status_code)

    total: int = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(*conditions)
        )
    ).scalar_one()

    items = list(
        (
            await db.execute(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.timestamp.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    page = skip // limit + 1 if limit > 0 else 1
    return {
        "items": [
            {
                "id": str(item.id),
                "user_id": str(item.user_id) if item.user_id else None,
                "method": item.method,
                "path": item.path,
                "status_code": item.status_code,
                "ip_address": item.ip_address,
                "user_agent": item.user_agent,
                "request_body_hash": item.request_body_hash,
                "duration_ms": item.duration_ms,
                "timestamp": item.timestamp.isoformat() if item.timestamp else None,
                "action": item.action,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "changes": item.changes,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": limit,
        "pages": max(1, -(-total // limit)),
    }
