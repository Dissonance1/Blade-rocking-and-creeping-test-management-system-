"""
Blade CRUD and workflow action endpoints.

Blade creation is exclusively via POST /work-orders/ (grid scaffold) —
there is no longer a standalone blade-creation endpoint here.

GET    /blades/                          — list blades (search/filter)
GET    /blades/{blade_id}                — get blade detail
PUT    /blades/{blade_id}                — update blade basic info
POST   /blades/{blade_id}/send-to-assembly
POST   /blades/{blade_id}/return-to-oh
POST   /blades/{blade_id}/complete
POST   /blades/{blade_id}/reject
POST   /blades/{blade_id}/reopen
POST   /blades/{blade_id}/hold
GET    /blades/{blade_id}/history
POST   /blades/{blade_id}/attachments
GET    /blades/{blade_id}/attachments
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any

import aiofiles
import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import AttachmentType, BladeStatus, BladeType
from app.schemas.base import PaginatedResponse, StatusResponse
from app.schemas.blade import (
    BladeListItem,
    BladeResponse,
    BladeSearchParams,
    BladeUpdate,
    RejectBladeRequest,
    SendToAssemblyRequest,
)
from app.schemas.workflow import WorkflowHistoryResponse, WorkflowLogResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_blade_or_404(blade_id: uuid.UUID, db: AsyncSession) -> Any:
    """Fetch a non-deleted Blade by primary key or raise HTTP 404."""
    from app.models.blade import Blade

    result = await db.execute(
        select(Blade).where(Blade.id == blade_id, Blade.deleted_at.is_(None))
    )
    blade = result.scalar_one_or_none()
    if blade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blade {blade_id} not found",
        )
    return blade


def _build_blade_filters(q: BladeSearchParams) -> list:
    """Build a list of SQLAlchemy WHERE conditions from *q*."""
    from app.models.blade import Blade

    conditions = [Blade.deleted_at.is_(None)]

    if q.serial_number:
        conditions.append(Blade.serial_number.ilike(f"%{q.serial_number}%"))
    if q.melt_number:
        conditions.append(Blade.melt_number.ilike(f"%{q.melt_number}%"))
    if q.work_order_number:
        conditions.append(Blade.work_order_number.ilike(f"%{q.work_order_number}%"))
    if q.part_number:
        conditions.append(Blade.part_number.ilike(f"%{q.part_number}%"))
    if q.status:
        conditions.append(Blade.status == q.status)
    if q.station_id:
        conditions.append(Blade.current_station_id == q.station_id)
    if q.assigned_to_id:
        conditions.append(Blade.assigned_to_id == q.assigned_to_id)
    if q.created_by_id:
        conditions.append(Blade.created_by_id == q.created_by_id)
    if q.ocr_mismatch_only:
        conditions.append(Blade.ocr_mismatch_flag.is_(True))
    if q.date_from:
        from sqlalchemy import cast, Date

        conditions.append(cast(Blade.created_at, Date) >= q.date_from)
    if q.date_to:
        from sqlalchemy import cast, Date

        conditions.append(cast(Blade.created_at, Date) <= q.date_to)

    return conditions


async def _log_workflow_transition(
    db: AsyncSession,
    blade: Any,
    from_status: BladeStatus | None,
    to_status: BladeStatus,
    actor_id: uuid.UUID,
    remarks: str | None = None,
    station_id: uuid.UUID | None = None,
) -> None:
    """Persist a WorkflowLog row for a status transition."""
    from app.models.workflow import WorkflowLog

    log = WorkflowLog(
        blade_id=blade.id,
        from_status=from_status,
        to_status=to_status,
        action_by_id=actor_id,
        station_id=station_id or blade.current_station_id,
        remarks=remarks,
    )
    db.add(log)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=PaginatedResponse[BladeListItem],
    status_code=status.HTTP_200_OK,
    summary="List blades with optional filters",
)
async def list_blades(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    # Search params as individual query parameters
    serial_number: str | None = Query(default=None),
    melt_number: str | None = Query(default=None),
    work_order_number: str | None = Query(default=None),
    part_number: str | None = Query(default=None),
    blade_type: "BladeType | None" = Query(default=None),
    blade_status: BladeStatus | None = Query(default=None, alias="status"),
    blade_statuses: str | None = Query(default=None, alias="statuses"),
    station_id: uuid.UUID | None = Query(default=None),
    assigned_to_id: uuid.UUID | None = Query(default=None),
    created_by_id: uuid.UUID | None = Query(default=None),
    ocr_mismatch_only: bool = Query(default=False),
    date_from: str | None = Query(default=None, description="ISO date YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="ISO date YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=1000, alias="limit"),
    sort_by: str = Query(default="created_at"),
    sort_desc: bool = Query(default=True),
) -> Any:
    """
    Return a paginated list of blades matching the supplied filter criteria.

    All filters are combined with AND logic.  Supports full-text ILIKE
    matching on ``serial_number``, ``melt_number``, ``work_order_number``,
    and ``part_number``.
    """
    from app.models.blade import Blade
    import datetime as dt

    conditions = [Blade.deleted_at.is_(None)]

    if serial_number:
        conditions.append(Blade.serial_number.ilike(f"%{serial_number}%"))
    if melt_number:
        conditions.append(Blade.melt_number.ilike(f"%{melt_number}%"))
    if work_order_number:
        conditions.append(Blade.work_order_number.ilike(f"%{work_order_number}%"))
    if part_number:
        conditions.append(Blade.part_number.ilike(f"%{part_number}%"))
    if blade_type:
        conditions.append(Blade.blade_type == blade_type)
    if blade_status:
        conditions.append(Blade.status == blade_status)
    if blade_statuses:
        status_list = [s.strip() for s in blade_statuses.split(",") if s.strip() in BladeStatus.__members__]
        if status_list:
            conditions.append(Blade.status.in_(status_list))
    if station_id:
        conditions.append(Blade.current_station_id == station_id)
    if assigned_to_id:
        conditions.append(Blade.assigned_to_id == assigned_to_id)
    if created_by_id:
        conditions.append(Blade.created_by_id == created_by_id)
    if ocr_mismatch_only:
        conditions.append(Blade.ocr_mismatch_flag.is_(True))
    if date_from:
        from sqlalchemy import cast, Date

        conditions.append(cast(Blade.created_at, Date) >= dt.date.fromisoformat(date_from))
    if date_to:
        from sqlalchemy import cast, Date

        conditions.append(cast(Blade.created_at, Date) <= dt.date.fromisoformat(date_to))

    # Count
    count_q = select(func.count()).select_from(Blade).where(*conditions)
    total: int = (await db.execute(count_q)).scalar_one()

    # Sortable columns
    _sortable = {
        "created_at": Blade.created_at,
        "updated_at": Blade.updated_at,
        "serial_number": Blade.serial_number,
        "status": Blade.status,
    }
    order_col = _sortable.get(sort_by, Blade.created_at)
    order_expr = order_col.desc() if sort_desc else order_col.asc()

    offset = (page - 1) * page_size
    items_q = (
        select(Blade)
        .where(*conditions)
        .order_by(order_expr)
        .offset(offset)
        .limit(page_size)
    )
    blades = list((await db.execute(items_q)).scalars().all())

    # Enrich blades with latest INITIAL measurement weight/SM
    # Use a subquery that picks the single most recent INITIAL measurement per blade
    from app.models.measurement import Measurement
    from sqlalchemy import text

    blade_ids = [b.id for b in blades]
    meas_by_blade: dict = {}
    if blade_ids:
        # Use a plain GROUP BY + MAX(measured_at) approach then join back
        subq = (
            select(
                Measurement.blade_id,
                func.max(Measurement.measured_at).label("latest_at"),
            )
            .where(
                Measurement.blade_id.in_(blade_ids),
                Measurement.measurement_type == "INITIAL",
            )
            .group_by(Measurement.blade_id)
            .subquery()
        )
        meas_q = (
            select(
                Measurement.blade_id,
                Measurement.weight_grams,
                Measurement.static_moment_gcm,
            )
            .join(
                subq,
                (Measurement.blade_id == subq.c.blade_id)
                & (Measurement.measured_at == subq.c.latest_at),
            )
        )
        for row in (await db.execute(meas_q)).all():
            meas_by_blade[str(row.blade_id)] = {
                "weight_grams": float(row.weight_grams) if row.weight_grams else None,
                "static_moment_gcm": float(row.static_moment_gcm) if row.static_moment_gcm else None,
            }

    # Build list items enriched with measurement data
    items = []
    for b in blades:
        m = meas_by_blade.get(str(b.id), {})
        item = {
            "id": b.id,
            "serial_number": b.serial_number,
            "melt_number": b.melt_number,
            "work_order_number": b.work_order_number,
            "shop_order_number": b.shop_order_number,
            "part_number": b.part_number,
            "nomenclature": b.nomenclature,
            "engine_number": b.engine_number,
            "blade_type": b.blade_type,
            "status": b.status,
            "ocr_mismatch_flag": b.ocr_mismatch_flag,
            "current_station": None,
            "assigned_to": None,
            "created_at": b.created_at,
            "updated_at": b.updated_at,
            "weight_grams": m.get("weight_grams"),
            "static_moment_gcm": m.get("static_moment_gcm"),
        }
        items.append(item)

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# GET /rejection-reasons/
# ---------------------------------------------------------------------------


@router.get(
    "/rejection-reasons/",
    status_code=status.HTTP_200_OK,
    summary="List all active rejection reasons",
)
async def list_rejection_reasons(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    from app.models.workflow import RejectionReason
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(RejectionReason).where(RejectionReason.is_active.is_(True)).order_by(RejectionReason.code)
    )
    reasons = result.scalars().all()
    return [
        {"id": str(r.id), "code": r.code, "description": r.description, "is_active": r.is_active}
        for r in reasons
    ]


# ---------------------------------------------------------------------------
# GET /{blade_id}/qr
# ---------------------------------------------------------------------------


@router.get("/{blade_id}/qr", status_code=200, summary="Generate QR code data for a blade")
async def get_blade_qr(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    blade = await _get_blade_or_404(blade_id, db)
    qr_data = {
        "blade_id": str(blade.id),
        "serial_number": blade.serial_number,
        "melt_number": blade.melt_number,
        "part_number": blade.part_number,
        "status": str(blade.status),
        "url": f"/blades/{blade.id}",
    }
    return {"qr_data": json.dumps(qr_data), "blade_id": str(blade.id), "serial_number": blade.serial_number}


# ---------------------------------------------------------------------------
# GET /{blade_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{blade_id}",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full blade detail",
)
async def get_blade(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Return the complete record for a single blade, including measurements and OCR data."""
    from app.repositories.blade_repository import BladeRepository
    repo = BladeRepository(db)
    blade = await repo.get_with_measurements(blade_id)
    if blade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Blade {blade_id} not found")
    return blade


# ---------------------------------------------------------------------------
# PUT /{blade_id}
# ---------------------------------------------------------------------------


@router.put(
    "/{blade_id}",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Update blade basic information",
)
async def update_blade(
    blade_id: uuid.UUID,
    body: BladeUpdate,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Update the mutable fields of an existing blade record.

    Status transitions must be performed through the dedicated action
    endpoints rather than this update endpoint.

    Raises:
        HTTP 404 — blade not found.
    """
    blade = await _get_blade_or_404(blade_id, db)

    # If melt number is changing, create a workflow log entry
    if body.melt_number and body.melt_number != blade.melt_number:
        await _log_workflow_transition(
            db=db, blade=blade,
            from_status=blade.status, to_status=blade.status,
            actor_id=current_user.id,
            remarks=f"Melt number changed: {blade.melt_number} → {body.melt_number}",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(blade, field, value)

    await db.commit()
    await db.refresh(blade)

    logger.info("blade_updated", blade_id=str(blade_id), fields=list(update_data.keys()))
    return blade


# ---------------------------------------------------------------------------
# POST /{blade_id}/send-to-assembly
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/send-to-assembly",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a blade from OH to assembly",
)
async def send_to_assembly(
    blade_id: uuid.UUID,
    body: SendToAssemblyRequest,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Transition a blade to ``SENT_TO_ASSEMBLY`` status.

    Valid from: ``OH_INSPECTION``, ``MEASUREMENTS_RECORDED``, ``REOPENED``.

    This action:
    - Updates blade status to SENT_TO_ASSEMBLY.
    - Optionally routes to a specific assembly station.
    - Persists a workflow log entry.
    - Dispatches a notification to Assembly team (background task).

    Raises:
        HTTP 404 — blade not found.
        HTTP 409 — invalid transition from current status.
    """
    from app.main import WorkflowTransitionError

    blade = await _get_blade_or_404(blade_id, db)

    if blade.blade_type == BladeType.HPTR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="HPTR blades stay in OH and are never sent to Assembly. Use the OH Slot Allocation tools instead.",
        )

    # Every blade belongs to a Work Order and must be sent as a full set
    # (90 blades), not individually. Use
    # POST /work-orders/{work_order_number}/send-to-assembly instead.
    if blade.work_order_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Blade '{blade.serial_number}' belongs to Work Order '{blade.work_order_number}'. "
                "Work Order blades must be sent to Assembly together when the set is complete (90 blades). "
                "Use the 'Send Work Order to Assembly' action on the OH Queue page."
            ),
        )

    valid_from = {
        BladeStatus.OH_INSPECTION,
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.REOPENED,
    }
    if blade.status not in valid_from:
        raise WorkflowTransitionError(
            detail=f"Cannot send to assembly from status '{blade.status}'",
            current_status=str(blade.status),
        )

    from_status = blade.status
    blade.status = BladeStatus.SENT_TO_ASSEMBLY
    if body.target_station_id:
        blade.current_station_id = body.target_station_id

    await _log_workflow_transition(
        db=db,
        blade=blade,
        from_status=from_status,
        to_status=BladeStatus.SENT_TO_ASSEMBLY,
        actor_id=current_user.id,
        remarks=body.remarks,
        station_id=body.target_station_id,
    )

    await db.commit()
    await db.refresh(blade)

    # Batch-level notification is sent by POST /batches/{batch}/send-to-assembly.
    # No per-blade notification here — that would spam 90 messages per batch.

    logger.info("blade_sent_to_assembly", blade_id=str(blade_id))
    return blade


# ---------------------------------------------------------------------------
# POST /{blade_id}/return-to-oh
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/return-to-oh",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Return a blade from assembly back to OH",
)
async def return_to_oh(
    blade_id: uuid.UUID,
    remarks: str | None = None,
    current_user: Any = Depends(require_roles("ASSEMBLY_OPERATOR", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Transition a blade to ``RETURNED_TO_OH`` status.

    Valid from: ``SENT_TO_ASSEMBLY``, ``SLOT_ASSIGNED``,
    ``BALANCING_IN_PROGRESS``, ``BALANCING_COMPLETED``.

    Raises:
        HTTP 404 — blade not found.
        HTTP 409 — invalid transition from current status.
    """
    from app.main import WorkflowTransitionError

    blade = await _get_blade_or_404(blade_id, db)

    valid_from = {
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.SLOT_ASSIGNED,
        BladeStatus.BALANCING_IN_PROGRESS,
        BladeStatus.BALANCING_COMPLETED,
    }
    if blade.status not in valid_from:
        raise WorkflowTransitionError(
            detail=f"Cannot return to OH from status '{blade.status}'",
            current_status=str(blade.status),
        )

    from_status = blade.status
    blade.status = BladeStatus.RETURNED_TO_OH

    await _log_workflow_transition(
        db=db,
        blade=blade,
        from_status=from_status,
        to_status=BladeStatus.RETURNED_TO_OH,
        actor_id=current_user.id,
        remarks=remarks,
    )

    await db.commit()
    await db.refresh(blade)

    # When every blade in the work order is back at OH, send one notification.
    work_order_number = blade.work_order_number
    if work_order_number:
        async def _notify_work_order_returned(_wo: str) -> None:
            from app.notifications.service import NotificationService
            from app.models.notification import NotificationType
            from app.db.session import AsyncSessionLocal
            try:
                async with AsyncSessionLocal() as _db:
                    remaining = (await _db.execute(
                        select(func.count(Blade.id)).where(
                            Blade.work_order_number == _wo,
                            Blade.deleted_at.is_(None),
                            Blade.status.notin_([
                                BladeStatus.RETURNED_TO_OH,
                                BladeStatus.FINAL_VERIFICATION,
                                BladeStatus.COMPLETED,
                                BladeStatus.REJECTED,
                            ]),
                        )
                    )).scalar_one()
                    if remaining == 0:
                        svc = NotificationService(_db)
                        await svc.notify_roles(
                            roles=["OH_OPERATOR", "SUPER_ADMIN"],
                            title=f"Work Order {_wo} returned to OH",
                            body=f"All blades in Work Order {_wo} have been returned from Assembly. Final verification can begin.",
                            notification_type=NotificationType.WORKFLOW_UPDATED,
                            metadata={"work_order_number": _wo},
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify_work_order_returned_failed", error=str(exc))

        background_tasks.add_task(_notify_work_order_returned, work_order_number)

    logger.info("blade_returned_to_oh", blade_id=str(blade_id))
    return blade


# ---------------------------------------------------------------------------
# POST /{blade_id}/complete
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/complete",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a blade as finally completed",
)
async def complete_blade(
    blade_id: uuid.UUID,
    remarks: str | None = None,
    current_user: Any = Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Transition a blade to ``COMPLETED`` status.

    Valid from: ``FINAL_VERIFICATION``, ``RETURNED_TO_OH``,
    ``BALANCING_COMPLETED``.

    Raises:
        HTTP 404 — blade not found.
        HTTP 409 — invalid transition from current status.
    """
    from app.main import WorkflowTransitionError

    blade = await _get_blade_or_404(blade_id, db)

    valid_from = {
        BladeStatus.FINAL_VERIFICATION,
        BladeStatus.RETURNED_TO_OH,
        BladeStatus.BALANCING_COMPLETED,
    }
    if blade.status not in valid_from:
        raise WorkflowTransitionError(
            detail=f"Cannot complete blade from status '{blade.status}'",
            current_status=str(blade.status),
        )

    from_status = blade.status
    blade.status = BladeStatus.COMPLETED

    await _log_workflow_transition(
        db=db,
        blade=blade,
        from_status=from_status,
        to_status=BladeStatus.COMPLETED,
        actor_id=current_user.id,
        remarks=remarks or "Blade overhaul completed",
    )

    await db.commit()
    await db.refresh(blade)

    # When every blade in the work order is COMPLETED, notify Assembly + Super Admin.
    work_order_number = blade.work_order_number
    if work_order_number:
        async def _notify_work_order_completed(_wo: str) -> None:
            from app.notifications.service import NotificationService
            from app.models.notification import NotificationType
            from app.db.session import AsyncSessionLocal
            try:
                async with AsyncSessionLocal() as _db:
                    remaining = (await _db.execute(
                        select(func.count(Blade.id)).where(
                            Blade.work_order_number == _wo,
                            Blade.deleted_at.is_(None),
                            Blade.status != BladeStatus.COMPLETED,
                            Blade.status != BladeStatus.REJECTED,
                        )
                    )).scalar_one()
                    if remaining == 0:
                        svc = NotificationService(_db)
                        await svc.notify_roles(
                            roles=["ASSEMBLY_OPERATOR", "SUPER_ADMIN"],
                            title=f"Work Order {_wo} — Final verification complete",
                            body=f"All blades in Work Order {_wo} have passed final OH verification and are marked COMPLETED.",
                            notification_type=NotificationType.GENERAL,
                            metadata={"work_order_number": _wo},
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify_work_order_completed_failed", error=str(exc))

        background_tasks.add_task(_notify_work_order_completed, work_order_number)

    logger.info("blade_completed", blade_id=str(blade_id))
    return blade


# ---------------------------------------------------------------------------
# POST /{blade_id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/reject",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a blade",
)
async def reject_blade(
    blade_id: uuid.UUID,
    body: RejectBladeRequest,
    current_user: Any = Depends(
        require_roles("OH_OPERATOR", "ASSEMBLY_OPERATOR", "SUPER_ADMIN")
    ),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Transition a blade to ``REJECTED`` status.

    A pre-defined rejection reason is required.  The blade may be rejected
    from any active (non-terminal) status.

    Raises:
        HTTP 404 — blade or rejection reason not found.
        HTTP 409 — blade is already completed or rejected.
    """
    from app.main import WorkflowTransitionError

    blade = await _get_blade_or_404(blade_id, db)

    terminal_statuses = {BladeStatus.COMPLETED, BladeStatus.REJECTED}
    if blade.status in terminal_statuses:
        raise WorkflowTransitionError(
            detail=f"Cannot reject a blade with status '{blade.status}'",
            current_status=str(blade.status),
        )

    # Validate rejection reason exists
    from app.models.workflow import RejectionReason
    from sqlalchemy import select as sa_select

    rr = (
        await db.execute(
            sa_select(RejectionReason).where(
                RejectionReason.id == body.rejection_reason_id,
                RejectionReason.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if rr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rejection reason {body.rejection_reason_id} not found",
        )

    from_status = blade.status
    blade.status = BladeStatus.REJECTED
    blade.rejection_reason_id = body.rejection_reason_id
    blade.rejection_notes = body.rejection_notes

    await _log_workflow_transition(
        db=db,
        blade=blade,
        from_status=from_status,
        to_status=BladeStatus.REJECTED,
        actor_id=current_user.id,
        remarks=body.rejection_notes,
    )

    await db.commit()
    await db.refresh(blade)

    logger.info("blade_rejected", blade_id=str(blade_id), reason_id=str(body.rejection_reason_id))
    return blade


# ---------------------------------------------------------------------------
# POST /{blade_id}/reopen
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/reopen",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Reopen a rejected blade",
)
async def reopen_blade(
    blade_id: uuid.UUID,
    remarks: str | None = None,
    current_user: Any = Depends(require_roles("SUPER_ADMIN", "OH_OPERATOR")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Transition a ``REJECTED`` blade back to ``REOPENED`` status.

    Only SUPER_ADMINs and OH_OPERATORs may reopen a blade.

    Raises:
        HTTP 404 — blade not found.
        HTTP 409 — blade is not in REJECTED status.
    """
    from app.main import WorkflowTransitionError

    blade = await _get_blade_or_404(blade_id, db)

    if blade.status != BladeStatus.REJECTED:
        raise WorkflowTransitionError(
            detail=f"Only REJECTED blades can be reopened. Current status: '{blade.status}'",
            current_status=str(blade.status),
        )

    blade.status = BladeStatus.REOPENED
    blade.rejection_reason_id = None
    blade.rejection_notes = None

    await _log_workflow_transition(
        db=db,
        blade=blade,
        from_status=BladeStatus.REJECTED,
        to_status=BladeStatus.REOPENED,
        actor_id=current_user.id,
        remarks=remarks or "Blade reopened for re-inspection",
    )

    await db.commit()
    await db.refresh(blade)

    logger.info("blade_reopened", blade_id=str(blade_id))
    return blade


# ---------------------------------------------------------------------------
# POST /{blade_id}/hold
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/hold",
    response_model=BladeResponse,
    status_code=status.HTTP_200_OK,
    summary="Put a blade on hold",
)
async def hold_blade(
    blade_id: uuid.UUID,
    remarks: str | None = None,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Transition a blade to ``ON_HOLD`` status.

    Any authenticated user may place a blade on hold.
    Blades that are already COMPLETED, REJECTED, or ON_HOLD cannot be
    placed on hold again.

    Raises:
        HTTP 404 — blade not found.
        HTTP 409 — invalid transition.
    """
    from app.main import WorkflowTransitionError

    blade = await _get_blade_or_404(blade_id, db)

    blocked = {BladeStatus.COMPLETED, BladeStatus.REJECTED, BladeStatus.ON_HOLD}
    if blade.status in blocked:
        raise WorkflowTransitionError(
            detail=f"Cannot place blade on hold from status '{blade.status}'",
            current_status=str(blade.status),
        )

    from_status = blade.status
    blade.status = BladeStatus.ON_HOLD

    await _log_workflow_transition(
        db=db,
        blade=blade,
        from_status=from_status,
        to_status=BladeStatus.ON_HOLD,
        actor_id=current_user.id,
        remarks=remarks,
    )

    await db.commit()
    await db.refresh(blade)

    logger.info("blade_on_hold", blade_id=str(blade_id))
    return blade


# ---------------------------------------------------------------------------
# DELETE /{blade_id}  — soft delete (SUPER_ADMIN only)
# ---------------------------------------------------------------------------


@router.delete(
    "/{blade_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a blade and all its related records",
)
async def delete_blade(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Permanently delete a blade and all related records (measurements, workflow
    logs, slot allocations, attachments, notifications).

    OH_OPERATOR may only delete blades that are still at the OH stage
    (CREATED, OH_INSPECTION, MEASUREMENTS_RECORDED, REOPENED, ON_HOLD).
    SUPER_ADMIN may delete any blade regardless of status.
    """
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.slot_allocation import SlotAllocation
    from app.models.workflow import WorkflowLog
    from app.models.notification import Notification
    from app.models.attachment import Attachment
    from app.models.work_order import WorkOrder

    OH_DELETABLE = {
        BladeStatus.CREATED,
        BladeStatus.OH_INSPECTION,
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.REOPENED,
        BladeStatus.ON_HOLD,
    }

    blade = await _get_blade_or_404(blade_id, db)

    roles = [r.name if hasattr(r, "name") else r for r in (current_user.roles or [])]
    if "SUPER_ADMIN" not in roles and blade.status not in OH_DELETABLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot delete blade in status '{blade.status}'. "
                   "Only blades at OH stage can be deleted by OH operators.",
        )

    work_order_id = blade.work_order_id
    serial_number = blade.serial_number
    replacement_fields = dict(
        work_order_number=blade.work_order_number,
        shop_order_number=blade.shop_order_number,
        part_number=blade.part_number,
        nomenclature=blade.nomenclature,
        engine_number=blade.engine_number,
        engine_hours=blade.engine_hours,
        component_hours=blade.component_hours,
        blade_type=blade.blade_type,
        current_station_id=blade.current_station_id,
    )

    # Hard-delete all child records first, then the blade itself
    for Model in (WorkflowLog, Measurement, SlotAllocation, Notification, Attachment):
        await db.execute(delete(Model).where(Model.blade_id == blade_id))

    await db.delete(blade)
    await db.flush()

    # Work Orders are a fixed 90-slot scaffold (S.No "01".."90") — deleting a
    # blade must never leave a gap in that set. Immediately re-scaffold a
    # blank row at the same S.No so the grid always shows all 90 rows, ready
    # for re-entry. The replacement is blank, so a previously "complete"
    # Work Order is no longer complete.
    if work_order_id is not None:
        db.add(
            Blade(
                serial_number=serial_number,
                work_order_id=work_order_id,
                status=BladeStatus.CREATED,
                created_by_id=current_user.id,
                ocr_mismatch_flag=False,
                **replacement_fields,
            )
        )
        work_order = await db.get(WorkOrder, work_order_id)
        if work_order is not None and work_order.is_entry_complete:
            work_order.is_entry_complete = False
            work_order.entry_completed_at = None
            work_order.entry_completed_by_id = None

    await db.commit()

    logger.info(
        "blade_hard_deleted",
        blade_id=str(blade_id),
        serial_number=serial_number,
        work_order_id=str(work_order_id) if work_order_id else None,
        by=str(current_user.id),
    )
    return {"success": True, "message": f"Blade {serial_number} deleted and row reset for re-entry"}


# ---------------------------------------------------------------------------
# GET /{blade_id}/history
# ---------------------------------------------------------------------------


@router.get(
    "/{blade_id}/history",
    response_model=WorkflowHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full workflow history for a blade",
)
async def get_blade_history(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Return the full chronological workflow history for a blade, including
    every status transition with timestamps, actors, and remarks.
    """
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    blade = await _get_blade_or_404(blade_id, db)

    logs_result = await db.execute(
        select(WorkflowLog)
        .where(WorkflowLog.blade_id == blade_id)
        .order_by(WorkflowLog.timestamp.asc())
    )
    logs = list(logs_result.scalars().all())

    return WorkflowHistoryResponse(
        blade=blade,
        logs=logs,
        total_transitions=len(logs),
    )


# ---------------------------------------------------------------------------
# POST /{blade_id}/attach-ocr-scan — associate a pending OCR scan with a blade
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/attach-ocr-scan",
    status_code=status.HTTP_201_CREATED,
    summary="Associate a saved OCR scan image with a blade",
)
async def attach_ocr_scan(
    blade_id: uuid.UUID,
    body: dict,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Link a previously saved OCR scan image (from ``POST /ocr/scan/blade-serial``
    or ``POST /ocr/scan/melt-number``) to the specified blade as an Attachment.

    Request body:
    - ``scan_id``: UUID string returned by the OCR scan endpoint.
    - ``label``: "serial_number" or "melt_number" (used as the display filename).

    Raises:
        HTTP 404 — blade or scan file not found.
    """
    from app.models.attachment import Attachment

    blade = await _get_blade_or_404(blade_id, db)

    scan_id = body.get("scan_id", "")
    label = body.get("label", "ocr_scan")

    if not scan_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scan_id is required")

    scan_dir = Path(os.environ.get("UPLOAD_DIR", settings.UPLOAD_DIR)) / "ocr_scans"
    found_path: Path | None = None
    found_ext = "jpg"
    for ext in ("jpg", "png", "tiff", "bmp", "webp"):
        candidate = scan_dir / f"{scan_id}.{ext}"
        if candidate.exists():
            found_path = candidate
            found_ext = ext
            break

    if found_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCR scan '{scan_id}' not found on server",
        )

    mime_map = {"jpg": "image/jpeg", "png": "image/png", "tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp"}
    original_filename = f"{label}_scan.{found_ext}"
    relative_path = f"ocr_scans/{scan_id}.{found_ext}"

    attachment = Attachment(
        blade_id=blade_id,
        filename=f"{scan_id}.{found_ext}",
        original_filename=original_filename,
        file_path=relative_path,
        file_size_bytes=found_path.stat().st_size,
        mime_type=mime_map.get(found_ext, "image/jpeg"),
        uploaded_by_id=current_user.id,
        attachment_type=AttachmentType.OCR_SCAN,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    logger.info(
        "ocr_scan_attached",
        blade_id=str(blade_id),
        scan_id=scan_id,
        label=label,
        attachment_id=str(attachment.id),
    )

    return {
        "id": str(attachment.id),
        "blade_id": str(blade_id),
        "scan_id": scan_id,
        "label": label,
        "original_filename": original_filename,
        "file_path": relative_path,
        "file_size_bytes": attachment.file_size_bytes,
        "mime_type": attachment.mime_type,
        "attachment_type": attachment.attachment_type,
        "uploaded_at": attachment.uploaded_at.isoformat(),
        "view_url": f"/api/v1/ocr/scan/{scan_id}",
    }


# ---------------------------------------------------------------------------
# POST /{blade_id}/attachments
# ---------------------------------------------------------------------------


@router.post(
    "/{blade_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Upload an attachment for a blade",
)
async def upload_attachment(
    blade_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="File to attach to the blade")],
    attachment_type: AttachmentType = AttachmentType.DOCUMENT,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Upload a file and attach it to the specified blade record.

    Supported attachment types: IMAGE, DOCUMENT, OCR_SCAN.
    Maximum file size is controlled by ``settings.MAX_FILE_SIZE_MB``.

    Raises:
        HTTP 400 — file exceeds maximum allowed size.
        HTTP 404 — blade not found.
    """
    import hashlib
    from datetime import timezone

    blade = await _get_blade_or_404(blade_id, db)

    # Validate size
    content = await file.read()
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB",
        )

    from app.models.attachment import Attachment

    safe_name = f"{blade_id}_{hashlib.md5((file.filename or 'file').encode()).hexdigest()[:8]}_{file.filename or 'upload'}"
    relative_path = f"attachments/{blade_id}/{safe_name}"
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    full_path = upload_dir / relative_path

    # Create directory and write file to disk
    full_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)

    attachment = Attachment(
        blade_id=blade_id,
        filename=safe_name,
        original_filename=file.filename or "unknown",
        file_path=relative_path,
        file_size_bytes=len(content),
        mime_type=file.content_type or "application/octet-stream",
        uploaded_by_id=current_user.id,
        attachment_type=attachment_type,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    logger.info(
        "attachment_uploaded",
        blade_id=str(blade_id),
        attachment_id=str(attachment.id),
        filename=file.filename,
    )
    return {
        "id": str(attachment.id),
        "filename": attachment.original_filename,
        "file_path": attachment.file_path,
        "file_size_bytes": attachment.file_size_bytes,
        "mime_type": attachment.mime_type,
        "attachment_type": attachment.attachment_type,
        "uploaded_at": attachment.uploaded_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /{blade_id}/attachments
# ---------------------------------------------------------------------------


@router.get(
    "/{blade_id}/attachments",
    status_code=status.HTTP_200_OK,
    summary="List all attachments for a blade",
)
async def list_attachments(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """
    Return a paginated list of all file attachments associated with a blade.

    Raises:
        HTTP 404 — blade not found.
    """
    from app.models.attachment import Attachment

    await _get_blade_or_404(blade_id, db)

    total: int = (
        await db.execute(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.blade_id == blade_id)
        )
    ).scalar_one()

    items = list(
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.blade_id == blade_id)
                .order_by(Attachment.uploaded_at.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return {
        "items": [
            {
                "id": str(a.id),
                "filename": a.original_filename,
                # Expose a proper API view URL — served by the /view endpoint below
                "file_url": f"/api/v1/blades/{blade_id}/attachments/{a.id}/view",
                "file_path": a.file_path,
                "file_size_bytes": a.file_size_bytes,
                "mime_type": a.mime_type,
                "attachment_type": a.attachment_type,
                "uploaded_at": a.uploaded_at.isoformat(),
            }
            for a in items
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# GET /{blade_id}/attachments/{attachment_id}/view — serve the file
# ---------------------------------------------------------------------------


@router.get(
    "/{blade_id}/attachments/{attachment_id}/view",
    status_code=status.HTTP_200_OK,
    summary="Serve an attachment file (view or download)",
)
async def view_attachment(
    blade_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str | None = Query(default=None, description="JWT token for browser img requests"),
) -> StreamingResponse:
    """
    Stream an attachment file.

    Accepts the JWT either via the standard Authorization header OR via the
    ``?token=...`` query parameter (needed for browser ``<img src>`` tags which
    cannot send custom headers).
    """
    from app.core.security import decode_token

    # Resolve JWT: header takes priority, fallback to ?token= query param
    raw_token: str | None = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        decode_token(raw_token)   # validates signature + expiry, raises on failure
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    from app.models.attachment import Attachment

    result = await db.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.blade_id == blade_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    full_path = upload_dir / attachment.file_path

    if not full_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found on server: {attachment.file_path}",
        )

    mime = attachment.mime_type or "application/octet-stream"
    is_image = mime.startswith("image/")
    disposition = "inline" if is_image else f'attachment; filename="{attachment.original_filename}"'

    async def file_iter():
        async with aiofiles.open(full_path, "rb") as f:
            while chunk := await f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        content=file_iter(),
        media_type=mime,
        headers={"Content-Disposition": disposition},
    )


# ---------------------------------------------------------------------------
# DELETE /{blade_id}/attachments/{attachment_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{blade_id}/attachments/{attachment_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete an attachment (OH_OPERATOR or SUPER_ADMIN)",
)
async def delete_attachment(
    blade_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[Any, Depends(require_roles("OH_OPERATOR", "SUPER_ADMIN"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Delete an attachment record and remove the file from disk."""
    from app.models.attachment import Attachment

    result = await db.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.blade_id == blade_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    # Remove file from disk (non-fatal if missing)
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    full_path = upload_dir / attachment.file_path
    try:
        if full_path.exists():
            full_path.unlink()
    except OSError as exc:
        logger.warning("attachment_file_delete_failed", path=str(full_path), error=str(exc))

    await db.delete(attachment)
    await db.commit()

    logger.info(
        "attachment_deleted",
        attachment_id=str(attachment_id),
        blade_id=str(blade_id),
        by=str(current_user.id),
    )
    return {"success": True, "message": "Attachment deleted"}
