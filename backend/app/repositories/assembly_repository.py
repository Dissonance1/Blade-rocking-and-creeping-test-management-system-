"""
AssemblyRepository — all DB queries for the Assembly station workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assembly_blade_record import AssemblyBladeRecord
from app.models.assembly_receipt import AssemblyBatchReceipt
from app.models.blade import Blade
from app.models.enums import AssemblyVerificationStatus, BladeStatus


class AssemblyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Batch receipts ────────────────────────────────────────────────────────

    async def get_receipt_by_batch(self, batch_number: str) -> AssemblyBatchReceipt | None:
        res = await self.db.execute(
            select(AssemblyBatchReceipt).where(
                AssemblyBatchReceipt.batch_number == batch_number
            )
        )
        return res.scalar_one_or_none()

    async def create_receipt(
        self,
        batch_number: str,
        received_by_id: uuid.UUID,
        station_id: uuid.UUID | None,
        total_expected: int,
        notes: str | None,
    ) -> AssemblyBatchReceipt:
        receipt = AssemblyBatchReceipt(
            batch_number=batch_number,
            received_by_id=received_by_id,
            station_id=station_id,
            total_expected=total_expected,
            notes=notes,
            received_at=datetime.now(timezone.utc),
        )
        self.db.add(receipt)
        await self.db.flush()
        await self.db.refresh(receipt)
        return receipt

    # ── Blade records ─────────────────────────────────────────────────────────

    async def get_blade_record(
        self, blade_id: uuid.UUID, batch_receipt_id: uuid.UUID
    ) -> AssemblyBladeRecord | None:
        res = await self.db.execute(
            select(AssemblyBladeRecord).where(
                AssemblyBladeRecord.blade_id == blade_id,
                AssemblyBladeRecord.batch_receipt_id == batch_receipt_id,
            )
        )
        return res.scalar_one_or_none()

    async def get_blade_record_by_id(self, record_id: uuid.UUID) -> AssemblyBladeRecord | None:
        res = await self.db.execute(
            select(AssemblyBladeRecord).where(AssemblyBladeRecord.id == record_id)
        )
        return res.scalar_one_or_none()

    async def list_blade_records(
        self, batch_receipt_id: uuid.UUID
    ) -> list[AssemblyBladeRecord]:
        res = await self.db.execute(
            select(AssemblyBladeRecord)
            .where(AssemblyBladeRecord.batch_receipt_id == batch_receipt_id)
            .order_by(AssemblyBladeRecord.created_at)
        )
        return list(res.scalars().all())

    async def create_blade_record(
        self,
        blade_id: uuid.UUID,
        batch_receipt_id: uuid.UUID,
        oh_weight: float | None,
        oh_dti_h1: float | None,
        oh_dti_h2: float | None,
        oh_dti_h3: float | None,
        oh_dti_h4: float | None,
    ) -> AssemblyBladeRecord:
        record = AssemblyBladeRecord(
            blade_id=blade_id,
            batch_receipt_id=batch_receipt_id,
            oh_weight=oh_weight,
            oh_dti_h1=oh_dti_h1,
            oh_dti_h2=oh_dti_h2,
            oh_dti_h3=oh_dti_h3,
            oh_dti_h4=oh_dti_h4,
            status=AssemblyVerificationStatus.PENDING,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def update_blade_record(
        self,
        record: AssemblyBladeRecord,
        **kwargs,
    ) -> AssemblyBladeRecord:
        for k, v in kwargs.items():
            setattr(record, k, v)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    # ── Batch-level aggregate counts ──────────────────────────────────────────

    async def count_blades_by_status(
        self, batch_number: str
    ) -> dict[BladeStatus, int]:
        res = await self.db.execute(
            select(Blade.status, func.count(Blade.id))
            .where(
                Blade.batch_number == batch_number,
                Blade.deleted_at.is_(None),
            )
            .group_by(Blade.status)
        )
        return {row[0]: row[1] for row in res.all()}

    async def count_verification_statuses(
        self, batch_receipt_id: uuid.UUID
    ) -> dict[AssemblyVerificationStatus, int]:
        res = await self.db.execute(
            select(AssemblyBladeRecord.status, func.count(AssemblyBladeRecord.id))
            .where(AssemblyBladeRecord.batch_receipt_id == batch_receipt_id)
            .group_by(AssemblyBladeRecord.status)
        )
        return {row[0]: row[1] for row in res.all()}

    # ── Blades in a batch ─────────────────────────────────────────────────────

    async def get_batch_blades(
        self,
        batch_number: str,
        status: BladeStatus | None = None,
    ) -> list[Blade]:
        conditions = [
            Blade.batch_number == batch_number,
            Blade.deleted_at.is_(None),
        ]
        if status:
            conditions.append(Blade.status == status)
        res = await self.db.execute(
            select(Blade).where(*conditions).order_by(Blade.serial_number)
        )
        return list(res.scalars().all())
