"""
API tests for the /api/v1/batches endpoints — HPTR/LPTR split behavior.

Coverage:
    POST /batches/{batch_number}/send-to-assembly — only LPTR blades move,
                                                     HPTR blades are skipped
    POST /batches/{batch_number}/assign-slot      — LPTR (algorithmic) vs
                                                     HPTR (explicit assignments)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.batch_event import BatchEvent
from app.models.blade import Blade
from app.models.enums import BatchEventType, BladeStatus, BladeType
from app.models.measurement import Measurement
from app.models.user import User

BASE = "/api/v1/batches"


async def _make_blade(
    db_session,
    oh_user: User,
    batch_number: str,
    blade_type: BladeType,
    status: BladeStatus,
    weight_grams: float | None = None,
) -> Blade:
    blade = Blade(
        id=uuid.uuid4(),
        serial_number=f"BLD-BATCH-{uuid.uuid4().hex[:8].upper()}",
        melt_number="MELT-BATCH",
        work_order_number="WO-2024-BATCH",
        part_number="PT-4470",
        nomenclature="Turbine Blade",
        batch_number=batch_number,
        blade_type=blade_type,
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
# POST /{batch_number}/send-to-assembly — mixed batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_batch_only_moves_lptr_blades(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """A mixed LPTR+HPTR batch: send-to-assembly only transitions LPTR blades."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    lptr = await _make_blade(db_session, oh_user, batch_number, BladeType.LPTR, BladeStatus.MEASUREMENTS_RECORDED)
    hptr = await _make_blade(db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)

    resp = await client.post(
        f"{BASE}/{batch_number}/send-to-assembly",
        json={"remarks": "test send"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["sent_count"] == 1
    assert data["hptr_skipped_count"] == 1

    await db_session.refresh(lptr)
    await db_session.refresh(hptr)
    assert lptr.status == BladeStatus.SENT_TO_ASSEMBLY
    assert hptr.status == BladeStatus.MEASUREMENTS_RECORDED  # untouched


@pytest.mark.asyncio
async def test_send_batch_all_hptr_returns_422(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """A batch with only HPTR blades has nothing eligible to send — 422."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    await _make_blade(db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)

    resp = await client.post(
        f"{BASE}/{batch_number}/send-to-assembly",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "HPTR" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /{batch_number}/assign-slot — LPTR branch (algorithmic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_slot_lptr_requires_assembly_operator(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """OH_OPERATOR is forbidden from the LPTR (default) assign-slot branch — 403."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    await _make_blade(
        db_session, oh_user, batch_number, BladeType.LPTR, BladeStatus.SENT_TO_ASSEMBLY, weight_grams=100.0
    )

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={"imbalance_slot": 1, "total_slots": 80},
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_slot_lptr_requires_accepted_batch(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """LPTR slot assignment is blocked until the batch has an ACCEPTED/MODIFIED event."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    await _make_blade(
        db_session, oh_user, batch_number, BladeType.LPTR, BladeStatus.SENT_TO_ASSEMBLY, weight_grams=100.0
    )

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={"imbalance_slot": 1, "total_slots": 80},
        headers=assembly_headers,
    )
    assert resp.status_code == 422
    assert "accepted" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assign_slot_lptr_succeeds_after_accepted(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """LPTR slot assignment succeeds once the batch is ACCEPTED, and skips HPTR blades in the same batch."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    lptr_blades = [
        await _make_blade(
            db_session, oh_user, batch_number, BladeType.LPTR, BladeStatus.SENT_TO_ASSEMBLY, weight_grams=100.0 + i
        )
        for i in range(4)
    ]
    hptr_blade = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=50.0
    )

    db_session.add(
        BatchEvent(
            id=uuid.uuid4(),
            batch_number=batch_number,
            event_type=BatchEventType.ACCEPTED,
            action_by_id=oh_user.id,
            remarks="test accept",
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={"blade_type": "LPTR", "imbalance_slot": 1, "total_slots": 80},
        headers=assembly_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["blades_assigned"] == 4
    assert data["blade_type"] == "LPTR"

    for blade in lptr_blades:
        await db_session.refresh(blade)
        assert blade.status == BladeStatus.SLOT_ASSIGNED

    await db_session.refresh(hptr_blade)
    assert hptr_blade.status == BladeStatus.MEASUREMENTS_RECORDED  # untouched


# ---------------------------------------------------------------------------
# POST /{batch_number}/assign-slot — HPTR branch (explicit assignments)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_slot_hptr_requires_oh_operator(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """ASSEMBLY_OPERATOR is forbidden from the HPTR assign-slot branch — 403."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    blade = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=100.0
    )

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={
            "blade_type": "HPTR",
            "start_slot": 60,
            "assignments": [{"blade_id": str(blade.id), "slot_number": 60}],
        },
        headers=assembly_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_slot_hptr_no_prior_batch_event_required(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """HPTR slot assignment works without any prior BatchEvent (no Assembly-acceptance gate)."""
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    b1 = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=120.0
    )
    b2 = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=80.0
    )

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={
            "blade_type": "HPTR",
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
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    b1 = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=100.0
    )
    await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=90.0
    )

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={
            "blade_type": "HPTR",
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
    batch_number = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
    b1 = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=100.0
    )
    b2 = await _make_blade(
        db_session, oh_user, batch_number, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED, weight_grams=90.0
    )

    resp = await client.post(
        f"{BASE}/{batch_number}/assign-slot",
        json={
            "blade_type": "HPTR",
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
