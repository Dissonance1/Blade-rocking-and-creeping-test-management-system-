"""
API tests for the /api/v1/work-orders endpoints — HPTR/LPTR split behavior.

Coverage:
    POST /work-orders/{work_order_number}/send-to-assembly — only applies to
                                                               LPTR work orders (422 on HPTR)
    POST /work-orders/{work_order_number}/assign-slot      — LPTR (algorithmic) vs
                                                               HPTR (explicit assignments),
                                                               blade_type derived from the
                                                               Work Order header

A Work Order is always exactly one blade_type and (once entry is complete)
exactly 90 blades — the old batch_number model where one batch could mix
LPTR and HPTR blades no longer exists, so every fixture here is single-type.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.blade import Blade
from app.models.enums import BatchEventType, BladeStatus, BladeType
from app.models.measurement import Measurement
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.work_order_event import WorkOrderEvent

BASE = "/api/v1/work-orders"


async def _make_work_order(
    db_session,
    oh_user: User,
    blade_type: BladeType,
    work_order_number: str | None = None,
) -> WorkOrder:
    work_order = WorkOrder(
        id=uuid.uuid4(),
        work_order_number=work_order_number or f"WO-{uuid.uuid4().hex[:8].upper()}",
        shop_order_number="SO-TEST",
        part_number="PT-4470",
        blade_type=blade_type,
        engine_hours="100:00:00",
        created_by_id=oh_user.id,
    )
    db_session.add(work_order)
    await db_session.flush()
    await db_session.refresh(work_order)
    return work_order


async def _make_blade(
    db_session,
    oh_user: User,
    work_order: WorkOrder,
    status: BladeStatus,
    weight_grams: float | None = None,
) -> Blade:
    blade = Blade(
        id=uuid.uuid4(),
        serial_number=f"BLD-WO-{uuid.uuid4().hex[:8].upper()}",
        melt_number="MELT-WO",
        work_order_id=work_order.id,
        work_order_number=work_order.work_order_number,
        part_number=work_order.part_number,
        nomenclature="Turbine Blade",
        blade_type=work_order.blade_type,
        status=status,
        created_by_id=oh_user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        ocr_mismatch_flag=False,
    )
    db_session.add(blade)
    await db_session.flush()

    if weight_grams is not None:
        m = Measurement(
            id=uuid.uuid4(),
            blade_id=blade.id,
            measurement_type="INITIAL",
            weight_grams=weight_grams,
            static_moment_gcm=weight_grams,  # reuse value; irrelevant which for these tests
            measured_by_id=oh_user.id,
        )
        db_session.add(m)
        await db_session.flush()

    await db_session.refresh(blade)
    return blade


# ---------------------------------------------------------------------------
# POST /{work_order_number}/send-to-assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_work_order_lptr_moves_eligible_blades(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """An LPTR work order: send-to-assembly transitions its eligible blades."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.LPTR)
    blade = await _make_blade(db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED)

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/send-to-assembly",
        json={"remarks": "test send"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["sent_count"] == 1
    assert data["skipped_count"] == 0

    await db_session.refresh(blade)
    assert blade.status == BladeStatus.SENT_TO_ASSEMBLY


@pytest.mark.asyncio
async def test_send_work_order_hptr_returns_422(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """HPTR work orders never go to Assembly — send-to-assembly is rejected outright."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.HPTR)
    await _make_blade(db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED)

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/send-to-assembly",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "LPTR" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /{work_order_number}/assign-slot — LPTR branch (algorithmic)
# ---------------------------------------------------------------------------


async def _make_lptr_stage1_blades(db_session, oh_user: User, work_order: WorkOrder) -> list[Blade]:
    """LPTR stage 1 requires exactly LPTR_STAGE1_BLADE_COUNT (46) eligible blades."""
    from app.core.constants import LPTR_STAGE1_BLADE_COUNT

    return [
        await _make_blade(
            db_session, oh_user, work_order, BladeStatus.SENT_TO_ASSEMBLY, weight_grams=100.0 + i
        )
        for i in range(LPTR_STAGE1_BLADE_COUNT)
    ]


@pytest.mark.asyncio
async def test_assign_slot_lptr_requires_assembly_operator(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """OH_OPERATOR is forbidden from an LPTR work order's assign-slot — 403."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.LPTR)
    blade = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.SENT_TO_ASSEMBLY, weight_grams=100.0
    )

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "stage": 1,
            "unbalance_slot": 1,
            "total_slots": 90,
            "assignments": [{"blade_id": str(blade.id), "slot_number": 1}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_slot_lptr_requires_accepted_work_order(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """LPTR slot assignment is blocked until the work order has an ACCEPTED/MODIFIED event."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.LPTR)
    blades = await _make_lptr_stage1_blades(db_session, oh_user, work_order)

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "stage": 1,
            "unbalance_slot": 1,
            "total_slots": 90,
            "assignments": [
                {"blade_id": str(b.id), "slot_number": i + 1} for i, b in enumerate(blades)
            ],
        },
        headers=assembly_headers,
    )
    assert resp.status_code == 422
    assert "accepted" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assign_slot_lptr_succeeds_after_accepted(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """LPTR stage-1 slot assignment succeeds once the work order is ACCEPTED."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.LPTR)
    lptr_blades = await _make_lptr_stage1_blades(db_session, oh_user, work_order)

    db_session.add(
        WorkOrderEvent(
            id=uuid.uuid4(),
            work_order_number=work_order.work_order_number,
            event_type=BatchEventType.ACCEPTED,
            action_by_id=oh_user.id,
            remarks="test accept",
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "stage": 1,
            "unbalance_slot": 1,
            "total_slots": 90,
            "assignments": [
                {"blade_id": str(b.id), "slot_number": i + 1} for i, b in enumerate(lptr_blades)
            ],
        },
        headers=assembly_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["blades_assigned"] == len(lptr_blades)
    assert data["blade_type"] == "LPTR"
    assert data["stage"] == 1

    for blade in lptr_blades:
        await db_session.refresh(blade)
        assert blade.status == BladeStatus.SLOT_ASSIGNED


# ---------------------------------------------------------------------------
# POST /{work_order_number}/assign-slot — HPTR branch (explicit assignments)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_slot_hptr_requires_oh_operator(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """ASSEMBLY_OPERATOR is forbidden from an HPTR work order's assign-slot — 403."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.HPTR)
    blade = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=100.0
    )

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "start_slot": 60,
            "assignments": [{"blade_id": str(blade.id), "slot_number": 60}],
        },
        headers=assembly_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_slot_hptr_no_prior_work_order_event_required(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """HPTR slot assignment works without any prior WorkOrderEvent (no Assembly-acceptance gate)."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.HPTR)
    b1 = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=120.0
    )
    b2 = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=80.0
    )

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "start_slot": 60,
            "total_slots": 90,
            "assignments": [
                {"blade_id": str(b1.id), "slot_number": 60},
                {"blade_id": str(b2.id), "slot_number": 15},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["blade_type"] == "HPTR"
    assert data["blades_assigned"] == 2
    assert data["start_slot"] == 60
    assert data["w1_total"] == pytest.approx(80.0)  # slot 15 is in W1 (1-45)
    assert data["w2_total"] == pytest.approx(120.0)  # slot 60 is in W2 (46-90)

    await db_session.refresh(b1)
    await db_session.refresh(b2)
    assert b1.status == BladeStatus.SLOT_ASSIGNED
    assert b2.status == BladeStatus.SLOT_ASSIGNED


@pytest.mark.asyncio
async def test_assign_slot_hptr_assignments_must_cover_all_eligible_blades(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """Submitting assignments for only some of the eligible HPTR blades is rejected."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.HPTR)
    b1 = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=100.0
    )
    await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=90.0
    )

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "start_slot": 60,
            "assignments": [{"blade_id": str(b1.id), "slot_number": 60}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "eligible" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assign_slot_hptr_rejects_duplicate_slot_numbers(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """Duplicate slot_number values in the assignments list are rejected."""
    work_order = await _make_work_order(db_session, oh_user, BladeType.HPTR)
    b1 = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=100.0
    )
    b2 = await _make_blade(
        db_session, oh_user, work_order, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=90.0
    )

    resp = await client.post(
        f"{BASE}/{work_order.work_order_number}/assign-slot",
        json={
            "start_slot": 60,
            "assignments": [
                {"blade_id": str(b1.id), "slot_number": 60},
                {"blade_id": str(b2.id), "slot_number": 60},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "duplicate" in resp.json()["detail"].lower()
