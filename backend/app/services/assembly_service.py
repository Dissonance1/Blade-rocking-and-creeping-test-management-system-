"""
AssemblyService — business logic for the Assembly station (720 Hanger).

Responsibilities:
- Mark a work order as received (transitions all SENT_TO_ASSEMBLY blades to ASSEMBLY_RECEIVED)
- Record per-blade scan / measurement data and validate against OH snapshot
- Accept (ACCEPTED or MODIFIED) or reject individual blades
- Compute work order progress
- Trigger set-making once all blades in the work order (BLADES_PER_WORK_ORDER) are accepted

Tolerances used for automatic validation:
  Weight:  ±0.5 g   (iScale resolution 0.1 g)
  DTI:     ±0.010 mm (Sylvac BT resolution 0.001 mm)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BLADES_PER_WORK_ORDER
from app.models.assembly_blade_record import AssemblyBladeRecord
from app.models.assembly_receipt import AssemblyBatchReceipt
from app.models.blade import Blade
from app.models.enums import AssemblyVerificationStatus, BladeStatus, BladeType
from app.models.measurement import Measurement
from app.models.user import User
from app.repositories.assembly_repository import AssemblyRepository
from app.repositories.blade_repository import BladeRepository
from app.schemas.assembly import (
    AssemblyBladeRecordResponse,
    BatchProgressResponse,
    BatchReceiptResponse,
    BladeAcceptRequest,
    BladeRejectRequest,
    BladeVerifyRequest,
    BladeVerifyResponse,
    FieldValidation,
)
from app.notifications.service import NotificationService
from app.workflows.state_machine import WorkflowEngine

log = structlog.get_logger(__name__)

# Validation tolerances
_WEIGHT_TOLERANCE = 0.5    # grams
_DTI_TOLERANCE    = 0.010  # mm


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(a - b, 6)


def _validate_field(
    field: str, oh_val: float | None, asm_val: float | None, tol: float
) -> FieldValidation:
    delta = _delta(asm_val, oh_val)
    within = abs(delta) <= tol if delta is not None else True
    return FieldValidation(
        field=field,
        oh_value=oh_val,
        assembly_value=asm_val,
        delta=delta,
        within_tolerance=within,
        tolerance_used=tol,
    )


def _record_to_response(r: AssemblyBladeRecord) -> AssemblyBladeRecordResponse:
    return AssemblyBladeRecordResponse(
        id=r.id,
        blade_id=r.blade_id,
        batch_receipt_id=r.batch_receipt_id,
        qr_scan_result=r.qr_scan_result,
        ocr_blade_number=r.ocr_blade_number,
        assembly_weight=_to_float(r.assembly_weight),
        assembly_dti_h1=_to_float(r.assembly_dti_h1),
        assembly_dti_h2=_to_float(r.assembly_dti_h2),
        assembly_dti_h3=_to_float(r.assembly_dti_h3),
        assembly_dti_h4=_to_float(r.assembly_dti_h4),
        oh_weight=_to_float(r.oh_weight),
        oh_dti_h1=_to_float(r.oh_dti_h1),
        oh_dti_h2=_to_float(r.oh_dti_h2),
        oh_dti_h3=_to_float(r.oh_dti_h3),
        oh_dti_h4=_to_float(r.oh_dti_h4),
        weight_delta=_to_float(r.weight_delta),
        status=r.status,
        verification_notes=r.verification_notes,
        verified_by_id=r.verified_by_id,
        verified_at=r.verified_at,
        created_at=r.created_at,
    )


class AssemblyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = AssemblyRepository(db)
        self._blade_repo = BladeRepository(db)
        self._engine = WorkflowEngine(db)
        self._notifier = NotificationService(db)

    # ── 1. Batch receipt ──────────────────────────────────────────────────────

    async def receive_batch(
        self,
        work_order_number: str,
        operator: User,
        station_id: uuid.UUID | None,
        notes: str | None,
    ) -> BatchReceiptResponse:
        existing = await self._repo.get_receipt_by_batch(work_order_number)
        if existing:
            raise ValueError(
                f"Work order '{work_order_number}' was already received at Assembly "
                f"on {existing.received_at.date()}."
            )

        blades = await self._repo.get_batch_blades(
            work_order_number, status=BladeStatus.SENT_TO_ASSEMBLY
        )
        if not blades:
            raise ValueError(
                f"No blades with status SENT_TO_ASSEMBLY found in work order "
                f"'{work_order_number}'. Ensure OH has sent the work order before "
                "marking it received."
            )

        receipt = await self._repo.create_receipt(
            work_order_number=work_order_number,
            received_by_id=operator.id,
            station_id=station_id,
            total_expected=len(blades),
            notes=notes,
        )

        # Transition every blade SENT_TO_ASSEMBLY → ASSEMBLY_RECEIVED
        for blade in blades:
            await self._engine.transition(
                blade=blade,
                to_status=BladeStatus.ASSEMBLY_RECEIVED,
                user=operator,
                station_id=station_id,
                remarks=f"Work order received at Assembly by {operator.username}",
            )

        log.info(
            "assembly.batch_received",
            work_order_number=work_order_number,
            blade_count=len(blades),
            operator_id=str(operator.id),
        )

        # One work-order-level notification to OH — not one per blade
        await self._notifier.notify_batch_received(
            work_order_number=work_order_number,
            blade_count=len(blades),
            operator_display=operator.full_name or operator.username,
        )

        return BatchReceiptResponse(
            id=receipt.id,
            work_order_number=receipt.work_order_number,
            received_at=receipt.received_at,
            received_by_id=receipt.received_by_id,
            station_id=receipt.station_id,
            total_expected=receipt.total_expected,
            notes=receipt.notes,
            created_at=receipt.created_at,
        )

    # ── 2. Per-blade scan & verify ────────────────────────────────────────────

    async def _get_oh_measurements(self, blade: Blade) -> dict[str, float | None]:
        """Pull the most recent FINAL measurement from OH for this blade."""
        from sqlalchemy import select as _select
        from app.models.enums import MeasurementType
        res = await self.db.execute(
            _select(Measurement)
            .where(
                Measurement.blade_id == blade.id,
                Measurement.measurement_type == MeasurementType.FINAL,
            )
            .order_by(Measurement.measured_at.desc())
            .limit(1)
        )
        m = res.scalar_one_or_none()
        if m is None:
            return {k: None for k in ("weight", "dti_h1", "dti_h2", "dti_h3", "dti_h4")}
        hd = m.height_data or {}
        return {
            "weight": _to_float(m.weight_grams),
            "dti_h1": _to_float(hd.get("H1")),
            "dti_h2": _to_float(hd.get("H2")),
            "dti_h3": _to_float(hd.get("H3")),
            "dti_h4": _to_float(hd.get("H4")),
        }

    async def verify_blade(
        self,
        blade: Blade,
        work_order_number: str,
        payload: BladeVerifyRequest,
    ) -> BladeVerifyResponse:
        if blade.status != BladeStatus.ASSEMBLY_RECEIVED:
            raise ValueError(
                f"Blade must be in ASSEMBLY_RECEIVED status to be verified. "
                f"Current status: {blade.status.value}"
            )
        if blade.work_order_number != work_order_number:
            raise ValueError(
                f"Blade '{blade.serial_number}' does not belong to work order "
                f"'{work_order_number}'."
            )

        receipt = await self._repo.get_receipt_by_batch(work_order_number)
        if receipt is None:
            raise ValueError(f"Work order '{work_order_number}' has not been received yet.")

        # Fetch or create the blade record
        record = await self._repo.get_blade_record(blade.id, receipt.id)
        oh = await self._get_oh_measurements(blade)

        if record is None:
            record = await self._repo.create_blade_record(
                blade_id=blade.id,
                batch_receipt_id=receipt.id,
                oh_weight=oh["weight"],
                oh_dti_h1=oh["dti_h1"],
                oh_dti_h2=oh["dti_h2"],
                oh_dti_h3=oh["dti_h3"],
                oh_dti_h4=oh["dti_h4"],
            )

        # Update with submitted readings
        w_delta = _delta(payload.assembly_weight, oh["weight"])
        await self._repo.update_blade_record(
            record,
            qr_scan_result=payload.qr_scan_result,
            ocr_blade_number=payload.ocr_blade_number,
            assembly_weight=payload.assembly_weight,
            assembly_dti_h1=payload.assembly_dti_h1,
            assembly_dti_h2=payload.assembly_dti_h2,
            assembly_dti_h3=payload.assembly_dti_h3,
            assembly_dti_h4=payload.assembly_dti_h4,
            weight_delta=w_delta,
        )

        # Identity checks
        serial_match = True
        if payload.qr_scan_result:
            serial_match = blade.serial_number in payload.qr_scan_result
        ocr_match = True
        if payload.ocr_blade_number:
            ocr_match = blade.serial_number in payload.ocr_blade_number

        # Field validations
        validations = [
            _validate_field("weight", oh["weight"], payload.assembly_weight, _WEIGHT_TOLERANCE),
            _validate_field("dti_h1", oh["dti_h1"], payload.assembly_dti_h1, _DTI_TOLERANCE),
            _validate_field("dti_h2", oh["dti_h2"], payload.assembly_dti_h2, _DTI_TOLERANCE),
            _validate_field("dti_h3", oh["dti_h3"], payload.assembly_dti_h3, _DTI_TOLERANCE),
            _validate_field("dti_h4", oh["dti_h4"], payload.assembly_dti_h4, _DTI_TOLERANCE),
        ]
        all_ok = all(v.within_tolerance for v in validations)
        if not serial_match or not ocr_match:
            suggested = "REJECT"
        elif all_ok:
            suggested = "ACCEPT"
        else:
            suggested = "REVIEW"

        return BladeVerifyResponse(
            record=_record_to_response(record),
            serial_number_match=serial_match,
            ocr_match=ocr_match,
            validations=validations,
            all_within_tolerance=all_ok,
            suggested_action=suggested,
        )

    # ── 3. Accept blade ───────────────────────────────────────────────────────

    async def accept_blade(
        self,
        blade: Blade,
        work_order_number: str,
        payload: BladeAcceptRequest,
        operator: User,
        station_id: uuid.UUID | None,
    ) -> AssemblyBladeRecordResponse:
        if blade.status != BladeStatus.ASSEMBLY_RECEIVED:
            raise ValueError(
                f"Blade must be in ASSEMBLY_RECEIVED to be accepted. "
                f"Current status: {blade.status.value}"
            )

        receipt = await self._repo.get_receipt_by_batch(work_order_number)
        if receipt is None:
            raise ValueError(f"Work order '{work_order_number}' has not been received yet.")

        record = await self._repo.get_blade_record(blade.id, receipt.id)
        if record is None:
            raise ValueError(
                "Blade has not been scanned yet. Call /verify before accepting."
            )

        # Determine if any readings were overridden
        overrides = {
            k: v for k, v in {
                "assembly_weight": payload.assembly_weight,
                "assembly_dti_h1": payload.assembly_dti_h1,
                "assembly_dti_h2": payload.assembly_dti_h2,
                "assembly_dti_h3": payload.assembly_dti_h3,
                "assembly_dti_h4": payload.assembly_dti_h4,
            }.items() if v is not None
        }
        is_modified = bool(overrides)
        new_status = (
            AssemblyVerificationStatus.MODIFIED
            if is_modified
            else AssemblyVerificationStatus.ACCEPTED
        )

        updates: dict = {
            "status": new_status,
            "verification_notes": payload.notes,
            "verified_by_id": operator.id,
            "verified_at": datetime.now(timezone.utc),
        }
        updates.update(overrides)
        if payload.assembly_weight is not None and record.oh_weight is not None:
            updates["weight_delta"] = _delta(payload.assembly_weight, _to_float(record.oh_weight))

        await self._repo.update_blade_record(record, **updates)

        await self._engine.transition(
            blade=blade,
            to_status=BladeStatus.ASSEMBLY_VERIFIED,
            user=operator,
            station_id=station_id,
            remarks=f"Assembly {'MODIFIED' if is_modified else 'ACCEPTED'} by {operator.username}",
        )

        return _record_to_response(record)

    # ── 4. Reject blade ───────────────────────────────────────────────────────

    async def reject_blade(
        self,
        blade: Blade,
        work_order_number: str,
        payload: BladeRejectRequest,
        operator: User,
        station_id: uuid.UUID | None,
    ) -> AssemblyBladeRecordResponse:
        if blade.status != BladeStatus.ASSEMBLY_RECEIVED:
            raise ValueError(
                f"Blade must be in ASSEMBLY_RECEIVED to be rejected. "
                f"Current status: {blade.status.value}"
            )

        receipt = await self._repo.get_receipt_by_batch(work_order_number)
        if receipt is None:
            raise ValueError(f"Work order '{work_order_number}' has not been received yet.")

        record = await self._repo.get_blade_record(blade.id, receipt.id)
        if record is None:
            raise ValueError(
                "Blade has not been scanned yet. Call /verify before rejecting."
            )

        await self._repo.update_blade_record(
            record,
            status=AssemblyVerificationStatus.REJECTED,
            verification_notes=payload.notes,
            verified_by_id=operator.id,
            verified_at=datetime.now(timezone.utc),
        )

        await self._engine.transition(
            blade=blade,
            to_status=BladeStatus.REJECTED,
            user=operator,
            station_id=station_id,
            remarks=f"Rejected at Assembly: {payload.notes}",
        )

        return _record_to_response(record)

    # ── 5. Batch progress ─────────────────────────────────────────────────────

    async def get_batch_progress(self, work_order_number: str) -> BatchProgressResponse:
        # A Work Order is now always exactly one blade_type (never a mix of
        # LPTR + HPTR), so we look up the header once and branch on it,
        # rather than always computing both an Assembly-side tally and an
        # OH-side HPTR tally against the same work_order_number.
        from sqlalchemy import func, select

        from app.models.work_order import WorkOrder

        wo_res = await self.db.execute(
            select(WorkOrder).where(WorkOrder.work_order_number == work_order_number)
        )
        work_order = wo_res.scalar_one_or_none()
        blade_type = work_order.blade_type if work_order is not None else None

        if blade_type == BladeType.HPTR:
            # HPTR never leaves OH — its "set making ready" gate is simply
            # "every HPTR blade in the work order has reached
            # MEASUREMENTS_RECORDED (or beyond, since blades already
            # slotted/balanced still count as measured)". Computed directly
            # from Blade rows — Assembly never creates a receipt for an
            # HPTR work order.
            hptr_total = (
                await self.db.execute(
                    select(func.count(Blade.id)).where(
                        Blade.work_order_number == work_order_number,
                        Blade.blade_type == BladeType.HPTR,
                        Blade.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            hptr_measurements_recorded = (
                await self.db.execute(
                    select(func.count(Blade.id)).where(
                        Blade.work_order_number == work_order_number,
                        Blade.blade_type == BladeType.HPTR,
                        Blade.deleted_at.is_(None),
                        Blade.status.in_(
                            [
                                BladeStatus.MEASUREMENTS_RECORDED,
                                BladeStatus.SLOT_ASSIGNED,
                                BladeStatus.BALANCING_IN_PROGRESS,
                                BladeStatus.BALANCING_COMPLETED,
                                BladeStatus.FINAL_VERIFICATION,
                                BladeStatus.COMPLETED,
                            ]
                        ),
                    )
                )
            ).scalar_one()

            return BatchProgressResponse(
                work_order_number=work_order_number,
                total_expected=hptr_total or BLADES_PER_WORK_ORDER,
                assembly_received=0,
                assembly_verified=0,
                assembly_rejected=0,
                pending=0,
                set_making_ready=False,
                hptr_total=hptr_total,
                hptr_measurements_recorded=hptr_measurements_recorded,
                hptr_set_making_ready=(hptr_total > 0 and hptr_measurements_recorded >= hptr_total),
            )

        # LPTR (default) — existing Assembly-side verification flow.
        receipt = await self._repo.get_receipt_by_batch(work_order_number)
        total_expected = receipt.total_expected if receipt else BLADES_PER_WORK_ORDER

        status_counts = await self._repo.count_blades_by_status(work_order_number)
        assembly_received = status_counts.get(BladeStatus.ASSEMBLY_RECEIVED, 0)
        assembly_verified = status_counts.get(BladeStatus.ASSEMBLY_VERIFIED, 0)
        assembly_rejected = status_counts.get(BladeStatus.REJECTED, 0)
        pending = assembly_received  # still awaiting scan

        return BatchProgressResponse(
            work_order_number=work_order_number,
            total_expected=total_expected,
            assembly_received=assembly_received + assembly_verified + assembly_rejected,
            assembly_verified=assembly_verified,
            assembly_rejected=assembly_rejected,
            pending=pending,
            set_making_ready=(assembly_verified >= total_expected),
            hptr_total=0,
            hptr_measurements_recorded=0,
            hptr_set_making_ready=False,
        )
