"""
WorkOrderService — orchestrates the Work Order grid-entry lifecycle:
create (scaffold 90 rows), resume/detail, per-row autosave, and the final
validate-and-complete step.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    BLADES_PER_WORK_ORDER,
    STATIC_MOMENT_FACTOR,
    WEIGHT_TO_GRAMS_FACTOR,
)
from app.models.enums import BladeStatus
from app.repositories.blade_repository import BladeRepository
from app.repositories.measurement_repository import MeasurementRepository
from app.repositories.work_order_repository import WorkOrderRepository
from app.schemas.work_order import (
    WorkOrderCompleteResponse,
    WorkOrderCreate,
    WorkOrderDetailResponse,
    WorkOrderRowResponse,
    WorkOrderRowUpdate,
)
from app.workflows.state_machine import WorkflowEngine

if TYPE_CHECKING:
    from app.models.blade import Blade
    from app.models.measurement import Measurement
    from app.models.user import User

log = structlog.get_logger(__name__)


def _row_response(
    blade: "Blade", measurement: "Measurement | None"
) -> WorkOrderRowResponse:
    weight_grams = (
        float(measurement.weight_grams)
        if measurement is not None and measurement.weight_grams is not None
        else None
    )
    static_moment = (
        float(measurement.static_moment_gcm)
        if measurement is not None and measurement.static_moment_gcm is not None
        else None
    )
    raw_weight = (
        round(weight_grams / WEIGHT_TO_GRAMS_FACTOR, 2)
        if weight_grams is not None
        else None
    )
    is_complete = bool(blade.melt_number and blade.melt_number.strip()) and weight_grams is not None
    return WorkOrderRowResponse(
        s_no=int(blade.serial_number),
        blade_id=blade.id,
        melt_number=blade.melt_number,
        ocr_melt_number=blade.ocr_melt_number,
        ocr_mismatch_flag=blade.ocr_mismatch_flag,
        raw_weight=raw_weight,
        weight_grams=weight_grams,
        static_moment_gcm=static_moment,
        is_complete=is_complete,
    )


class WorkOrderService:
    """Orchestrates Work Order create/resume/autosave/complete."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._wo_repo = WorkOrderRepository(db)
        self._blade_repo = BladeRepository(db)
        self._measurement_repo = MeasurementRepository(db)
        self._workflow_engine = WorkflowEngine(db)

    # ------------------------------------------------------------------
    # Create (Phase A "Start Blade Entry")
    # ------------------------------------------------------------------

    async def create(self, data: WorkOrderCreate, user: "User") -> WorkOrderDetailResponse:
        existing = await self._wo_repo.get_by_number(data.work_order_number)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Work Order '{data.work_order_number}' already exists.",
            )

        work_order = await self._wo_repo.create_header(data, created_by_id=user.id)
        await self._blade_repo.bulk_create_scaffold_rows(
            work_order=work_order,
            created_by_id=user.id,
            station_id=user.station_id,
            count=BLADES_PER_WORK_ORDER,
        )
        await self.db.commit()

        log.info(
            "work_order_service.created",
            work_order_number=work_order.work_order_number,
            blade_type=work_order.blade_type.value,
        )
        return await self.get_detail(data.work_order_number)

    # ------------------------------------------------------------------
    # Resume / detail
    # ------------------------------------------------------------------

    async def get_detail(self, work_order_number: str) -> WorkOrderDetailResponse:
        work_order = await self._get_work_order_or_404(work_order_number)
        blades = await self._blade_repo.get_by_work_order(work_order.id)

        rows: list[WorkOrderRowResponse] = []
        first_incomplete: int | None = None
        for blade in blades:
            measurement = await self._measurement_repo.get_latest_by_blade(blade.id)
            row = _row_response(blade, measurement)
            if not row.is_complete and first_incomplete is None:
                first_incomplete = row.s_no
            rows.append(row)

        return WorkOrderDetailResponse(
            work_order_number=work_order.work_order_number,
            shop_order_number=work_order.shop_order_number,
            part_number=work_order.part_number,
            blade_type=work_order.blade_type,
            engine_number=work_order.engine_number,
            engine_hours=work_order.engine_hours,
            component_hours=work_order.component_hours,
            is_entry_complete=work_order.is_entry_complete,
            entry_completed_at=work_order.entry_completed_at,
            rows=rows,
            first_incomplete_s_no=first_incomplete,
        )

    # ------------------------------------------------------------------
    # Autosave (per-row)
    # ------------------------------------------------------------------

    async def save_row(
        self,
        work_order_number: str,
        s_no: int,
        data: WorkOrderRowUpdate,
        user: "User",
    ) -> WorkOrderRowResponse:
        if not 1 <= s_no <= BLADES_PER_WORK_ORDER:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"s_no must be between 1 and {BLADES_PER_WORK_ORDER}.",
            )

        work_order = await self._get_work_order_or_404(work_order_number)
        if work_order.is_entry_complete:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Work Order '{work_order_number}' entry is already complete. "
                    "Use the Assembly modify flow for corrections."
                ),
            )

        blade = await self._blade_repo.get_row(work_order.id, s_no)
        if blade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Row {s_no} not found for Work Order '{work_order_number}'.",
            )

        if data.melt_number is not None:
            blade.melt_number = data.melt_number
        if data.ocr_melt_number is not None:
            blade.ocr_melt_number = data.ocr_melt_number
        if data.ocr_mismatch_flag is not None:
            blade.ocr_mismatch_flag = data.ocr_mismatch_flag
        if data.ocr_mismatch_notes is not None:
            blade.ocr_mismatch_notes = data.ocr_mismatch_notes
        self.db.add(blade)
        await self.db.flush()

        if data.raw_weight is not None:
            weight_grams = round(data.raw_weight * WEIGHT_TO_GRAMS_FACTOR, 4)
            static_moment_gcm = round(weight_grams * STATIC_MOMENT_FACTOR, 4)
            measurement = await self._measurement_repo.upsert_initial(
                blade_id=blade.id,
                weight_grams=weight_grams,
                static_moment_gcm=static_moment_gcm,
                measured_by_id=user.id,
                station_id=user.station_id,
            )
        else:
            measurement = await self._measurement_repo.get_latest_by_blade(blade.id)

        await self.db.commit()
        await self.db.refresh(blade)

        log.info(
            "work_order_service.row_saved",
            work_order_number=work_order_number,
            s_no=s_no,
        )
        return _row_response(blade, measurement)

    # ------------------------------------------------------------------
    # Complete (validate + bulk workflow transition)
    # ------------------------------------------------------------------

    async def complete(self, work_order_number: str, user: "User") -> WorkOrderCompleteResponse:
        work_order = await self._get_work_order_or_404(work_order_number)
        blades = await self._blade_repo.get_by_work_order(work_order.id)

        if len(blades) != BLADES_PER_WORK_ORDER:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Work Order '{work_order_number}' has {len(blades)} rows, "
                    f"expected {BLADES_PER_WORK_ORDER}."
                ),
            )

        if work_order.is_entry_complete:
            return WorkOrderCompleteResponse(
                work_order_number=work_order.work_order_number,
                status=BladeStatus.MEASUREMENTS_RECORDED.value,
                blade_ids=[b.id for b in blades],
                completed_at=work_order.entry_completed_at or datetime.now(timezone.utc),
            )

        incomplete_rows: list[int] = []
        melt_groups: dict[str, list[int]] = {}

        for blade in blades:
            s_no = int(blade.serial_number)
            measurement = await self._measurement_repo.get_latest_by_blade(blade.id)
            has_melt = bool(blade.melt_number and blade.melt_number.strip())
            has_weight = measurement is not None and measurement.weight_grams is not None
            if not (has_melt and has_weight):
                incomplete_rows.append(s_no)
                continue
            key = blade.melt_number.strip().upper()
            melt_groups.setdefault(key, []).append(s_no)

        if incomplete_rows:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Not all rows are complete.",
                    "incomplete_rows": sorted(incomplete_rows),
                },
            )

        duplicate_groups = [
            {"melt_number": melt, "s_nos": sorted(s_nos)}
            for melt, s_nos in melt_groups.items()
            if len(s_nos) > 1
        ]
        if duplicate_groups:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Duplicate melt numbers found.",
                    "duplicate_groups": duplicate_groups,
                },
            )

        station_id = user.station_id
        for blade in blades:
            blade, _ = await self._workflow_engine.transition(
                blade=blade,
                to_status=BladeStatus.OH_INSPECTION,
                user=user,
                station_id=station_id,
                remarks="Blade entry: grid row completed.",
            )
            blade, _ = await self._workflow_engine.transition(
                blade=blade,
                to_status=BladeStatus.MEASUREMENTS_RECORDED,
                user=user,
                station_id=station_id,
                remarks="Blade entry: Work Order completed.",
            )

        await self._wo_repo.mark_complete(work_order, completed_by_id=user.id)
        await self.db.commit()
        await self.db.refresh(work_order)

        log.info(
            "work_order_service.completed",
            work_order_number=work_order_number,
            blade_count=len(blades),
        )
        return WorkOrderCompleteResponse(
            work_order_number=work_order.work_order_number,
            status=BladeStatus.MEASUREMENTS_RECORDED.value,
            blade_ids=[b.id for b in blades],
            completed_at=work_order.entry_completed_at,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_work_order_or_404(self, work_order_number: str) -> Any:
        work_order = await self._wo_repo.get_by_number(work_order_number)
        if work_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{work_order_number}' not found.",
            )
        return work_order
