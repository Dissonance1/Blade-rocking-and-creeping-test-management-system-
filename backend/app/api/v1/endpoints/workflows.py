"""
Workflow history and dashboard statistics endpoints.

GET /workflows/history/{blade_id}    — full workflow log for a blade
GET /workflows/dashboard/stats       — counts by status + station-wise breakdown
GET /workflows/timeline/{blade_id}   — blade timeline for visual display
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.enums import BladeStatus
from app.schemas.workflow import WorkflowHistoryResponse, WorkflowLogResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /history/{blade_id}
# ---------------------------------------------------------------------------


@router.get(
    "/history/{blade_id}",
    response_model=WorkflowHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full workflow history for a blade",
)
async def get_workflow_history(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """
    Return the complete chronological list of status transitions for
    the specified blade, together with the actor, station, remarks,
    and timestamp for each step.

    Raises:
        HTTP 404 — blade not found.
    """
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    blade_result = await db.execute(
        select(Blade).where(Blade.id == blade_id, Blade.deleted_at.is_(None))
    )
    blade = blade_result.scalar_one_or_none()
    if blade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blade {blade_id} not found",
        )

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
# GET /dashboard/stats
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard/stats",
    status_code=status.HTTP_200_OK,
    summary="Dashboard statistics: blade counts by status and station breakdown",
)
async def dashboard_stats(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Return aggregated statistics suitable for a management dashboard:

    - **by_status**: total blade count per ``BladeStatus`` value.
    - **by_station**: per-station breakdown of blade counts (active blades only).
    - **total_active**: total non-terminal blades.
    - **total_completed**: blades in COMPLETED status.
    - **total_rejected**: blades in REJECTED status.

    Terminal blades (COMPLETED, REJECTED) are included in ``by_status``
    but excluded from ``total_active`` and ``by_station``.
    """
    from app.models.blade import Blade
    from app.models.slot_allocation import SlotAllocation
    from app.models.workflow import Station

    terminal = {BladeStatus.COMPLETED, BladeStatus.REJECTED}

    # Status counts
    status_counts_result = await db.execute(
        select(Blade.status, func.count(Blade.id).label("cnt"))
        .where(Blade.deleted_at.is_(None))
        .group_by(Blade.status)
    )
    by_status: dict[str, int] = {
        row.status: row.cnt for row in status_counts_result
    }

    # Fill in zeros for any status not represented
    for s in BladeStatus:
        by_status.setdefault(s.value, 0)

    # Station-wise breakdown (active blades only)
    station_counts_result = await db.execute(
        select(
            Station.id,
            Station.name,
            Station.code,
            func.count(Blade.id).label("cnt"),
        )
        .join(Blade, Blade.current_station_id == Station.id)
        .where(
            Blade.deleted_at.is_(None),
            Blade.status.notin_(list(terminal)),
        )
        .group_by(Station.id, Station.name, Station.code)
    )
    by_station = [
        {
            "station_id": str(row.id),
            "station_name": row.name,
            "station_code": row.code,
            "blade_count": row.cnt,
        }
        for row in station_counts_result
    ]

    total_active = sum(
        cnt for status_val, cnt in by_status.items()
        if status_val not in {s.value for s in terminal}
    )

    unbalanced_result = await db.execute(
        select(SlotAllocation.slot_number, SlotAllocation.blade_id)
        .where(
            SlotAllocation.is_active.is_(True),
            SlotAllocation.is_balanced.is_(False),
        )
        .order_by(SlotAllocation.slot_number)
    )
    unbalanced_slots = [
        {"slot_number": row.slot_number, "blade_id": str(row.blade_id)}
        for row in unbalanced_result
    ]

    return {
        "by_status": by_status,
        "by_station": by_station,
        "total_active": total_active,
        "total_completed": by_status.get(BladeStatus.COMPLETED.value, 0),
        "total_rejected": by_status.get(BladeStatus.REJECTED.value, 0),
        "unbalanced_slots": unbalanced_slots,
        "total_unbalanced": len(unbalanced_slots),
    }


# ---------------------------------------------------------------------------
# GET /dashboard/work-orders — distinct work orders with engine/blade summary
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard/work-orders",
    status_code=status.HTTP_200_OK,
    summary="Distinct active work orders with engine summary for dashboard header",
)
async def dashboard_work_orders(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    """
    Return one record per distinct work_order_number from active blades.

    Each record includes: work_order_number, shop_order_number, engine_number,
    running_hours, part_number, nomenclature, and the count of active blades
    for that work order.
    """
    from app.models.blade import Blade

    rows = (
        await db.execute(
            select(
                Blade.work_order_number,
                Blade.shop_order_number,
                Blade.engine_number,
                Blade.running_hours,
                Blade.part_number,
                Blade.nomenclature,
                func.count(Blade.id).label("blade_count"),
            )
            .where(
                Blade.deleted_at.is_(None),
                Blade.status.notin_(list({BladeStatus.COMPLETED, BladeStatus.REJECTED})),
            )
            .group_by(
                Blade.work_order_number,
                Blade.shop_order_number,
                Blade.engine_number,
                Blade.running_hours,
                Blade.part_number,
                Blade.nomenclature,
            )
            .order_by(func.count(Blade.id).desc())
        )
    ).all()

    return [
        {
            "work_order_number": row.work_order_number,
            "shop_order_number": row.shop_order_number,
            "engine_number": row.engine_number,
            "running_hours": row.running_hours,
            "part_number": row.part_number,
            "nomenclature": row.nomenclature,
            "blade_count": row.blade_count,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /dashboard/throughput  — last N days daily stats
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard/throughput",
    status_code=status.HTTP_200_OK,
    summary="Daily blade throughput for the last N days",
)
async def daily_throughput(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
) -> list:
    """
    Return a list of daily objects covering the last *days* calendar days
    (today included).  Each object has:

    - ``date``: ISO date string (YYYY-MM-DD)
    - ``created``: blades created on that day
    - ``completed``: blades that reached COMPLETED on that day
    - ``rejected``: blades that reached REJECTED on that day
    """
    from datetime import datetime, timedelta, timezone
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)

    # ── Created per day ────────────────────────────────────────────────────
    created_result = await db.execute(
        select(
            func.date(Blade.created_at).label("day"),
            func.count(Blade.id).label("cnt"),
        )
        .where(
            Blade.deleted_at.is_(None),
            Blade.created_at >= since,
        )
        .group_by(func.date(Blade.created_at))
    )
    created_by_day: dict[str, int] = {
        str(row.day): row.cnt for row in created_result
    }

    # ── Completed / rejected per day via workflow logs ─────────────────────
    for target_status in (BladeStatus.COMPLETED, BladeStatus.REJECTED):
        result = await db.execute(
            select(
                func.date(WorkflowLog.timestamp).label("day"),
                func.count(WorkflowLog.id).label("cnt"),
            )
            .where(
                WorkflowLog.to_status == target_status,
                WorkflowLog.timestamp >= since,
            )
            .group_by(func.date(WorkflowLog.timestamp))
        )
        if target_status == BladeStatus.COMPLETED:
            completed_by_day: dict[str, int] = {str(row.day): row.cnt for row in result}
        else:
            rejected_by_day: dict[str, int] = {str(row.day): row.cnt for row in result}

    # ── Build full date range ──────────────────────────────────────────────
    output = []
    for i in range(days):
        d = since + timedelta(days=i)
        day_str = str(d)
        output.append(
            {
                "date": day_str,
                "created": created_by_day.get(day_str, 0),
                "completed": completed_by_day.get(day_str, 0),
                "rejected": rejected_by_day.get(day_str, 0),
            }
        )

    return output


# ---------------------------------------------------------------------------
# GET /timeline/{blade_id}
# ---------------------------------------------------------------------------


@router.get(
    "/timeline/{blade_id}",
    status_code=status.HTTP_200_OK,
    summary="Get a blade's workflow timeline for visual display",
)
async def get_blade_timeline(
    blade_id: uuid.UUID,
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Return a timeline representation of a blade's workflow progress,
    enriched with display metadata for front-end rendering.

    The response contains:
    - ``blade``: minimal blade identification.
    - ``timeline``: ordered list of timeline steps, each with:
        - ``step_number``: 1-based position.
        - ``status``: the target ``BladeStatus`` value.
        - ``label``: human-readable status label.
        - ``completed``: whether this step has been reached.
        - ``current``: whether this is the blade's current status.
        - ``timestamp``: ISO timestamp when this step was reached (or null).
        - ``actor``: username of the person who triggered this step (or null).
        - ``remarks``: operator remarks for this transition (or null).

    Raises:
        HTTP 404 — blade not found.
    """
    from app.models.blade import Blade
    from app.models.workflow import WorkflowLog

    blade_result = await db.execute(
        select(Blade).where(Blade.id == blade_id, Blade.deleted_at.is_(None))
    )
    blade = blade_result.scalar_one_or_none()
    if blade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blade {blade_id} not found",
        )

    # Ordered canonical workflow path
    WORKFLOW_ORDER: list[BladeStatus] = [
        BladeStatus.CREATED,
        BladeStatus.OH_INSPECTION,
        BladeStatus.MEASUREMENTS_RECORDED,
        BladeStatus.SENT_TO_ASSEMBLY,
        BladeStatus.SLOT_ASSIGNED,
        BladeStatus.BALANCING_IN_PROGRESS,
        BladeStatus.BALANCING_COMPLETED,
        BladeStatus.RETURNED_TO_OH,
        BladeStatus.FINAL_VERIFICATION,
        BladeStatus.COMPLETED,
    ]

    STATUS_LABELS: dict[BladeStatus, str] = {
        BladeStatus.CREATED: "Created",
        BladeStatus.OH_INSPECTION: "OH Inspection",
        BladeStatus.MEASUREMENTS_RECORDED: "Measurements Recorded",
        BladeStatus.SENT_TO_ASSEMBLY: "Sent to Assembly",
        BladeStatus.SLOT_ASSIGNED: "Slot Assigned",
        BladeStatus.BALANCING_IN_PROGRESS: "Balancing In Progress",
        BladeStatus.BALANCING_COMPLETED: "Balancing Completed",
        BladeStatus.RETURNED_TO_OH: "Returned to OH",
        BladeStatus.FINAL_VERIFICATION: "Final Verification",
        BladeStatus.COMPLETED: "Completed",
        BladeStatus.REJECTED: "Rejected",
        BladeStatus.ON_HOLD: "On Hold",
        BladeStatus.REOPENED: "Reopened",
    }

    # Fetch all log entries for this blade
    logs_result = await db.execute(
        select(WorkflowLog)
        .where(WorkflowLog.blade_id == blade_id)
        .order_by(WorkflowLog.timestamp.asc())
    )
    logs = list(logs_result.scalars().all())

    # Build a map: to_status -> first log entry that reached it
    status_to_log: dict[BladeStatus, Any] = {}
    for log in logs:
        if log.to_status not in status_to_log:
            status_to_log[log.to_status] = log

    current_status = blade.status
    current_index = WORKFLOW_ORDER.index(current_status) if current_status in WORKFLOW_ORDER else -1

    timeline_steps = []
    for step_num, step_status in enumerate(WORKFLOW_ORDER, start=1):
        step_index = WORKFLOW_ORDER.index(step_status)
        log_entry = status_to_log.get(step_status)

        is_completed = step_index < current_index or current_status == step_status
        is_current = current_status == step_status

        timeline_steps.append(
            {
                "step_number": step_num,
                "status": step_status.value,
                "label": STATUS_LABELS.get(step_status, step_status.value),
                "completed": is_completed,
                "current": is_current,
                "timestamp": log_entry.timestamp.isoformat() if log_entry else None,
                "actor": (
                    log_entry.action_by.username
                    if log_entry and log_entry.action_by
                    else None
                ),
                "remarks": log_entry.remarks if log_entry else None,
            }
        )

    # Append special statuses if applicable
    special_status = None
    if current_status in {BladeStatus.REJECTED, BladeStatus.ON_HOLD, BladeStatus.REOPENED}:
        special_log = status_to_log.get(current_status)
        special_status = {
            "status": current_status.value,
            "label": STATUS_LABELS.get(current_status, current_status.value),
            "timestamp": special_log.timestamp.isoformat() if special_log else None,
            "actor": (
                special_log.action_by.username
                if special_log and special_log.action_by
                else None
            ),
            "remarks": special_log.remarks if special_log else None,
        }

    return {
        "blade": {
            "id": str(blade.id),
            "serial_number": blade.serial_number,
            "melt_number": blade.melt_number,
            "status": blade.status.value,
            "part_number": blade.part_number,
        },
        "timeline": timeline_steps,
        "special_status": special_status,
        "total_transitions": len(logs),
    }
