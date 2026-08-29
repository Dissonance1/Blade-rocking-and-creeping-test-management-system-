"""
API tests for the /api/v1/slots endpoints.

Coverage:
    POST /slots/assign             — role branch by blade_type (HPTR → OH_OPERATOR, LPTR → ASSEMBLY_OPERATOR)
    PUT  /slots/{slot_id}/balancing — same role branch

HPTR blades never leave OH, so their valid_from status for slot assignment
is MEASUREMENTS_RECORDED (not SENT_TO_ASSEMBLY/RETURNED_TO_OH like LPTR).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.blade import Blade
from app.models.enums import BladeStatus, BladeType
from app.models.user import User

BASE = "/api/v1/slots"


async def _make_blade(db_session, oh_user: User, blade_type: BladeType, status: BladeStatus) -> Blade:
    blade = Blade(
        id=uuid.uuid4(),
        serial_number=f"BLD-SLOT-{uuid.uuid4().hex[:8].upper()}",
        melt_number="MELT-SLOT",
        work_order_number="WO-2024-SLOT",
        part_number="PT-4470",
        blade_type=blade_type,
        status=status,
        created_by_id=oh_user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        ocr_mismatch_flag=False,
    )
    db_session.add(blade)
    await db_session.flush()
    await db_session.refresh(blade)
    return blade


# ---------------------------------------------------------------------------
# POST /assign — role branch by blade_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oh_operator_can_assign_slot_to_hptr_blade(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """OH_OPERATOR assigning a slot to an HPTR blade at MEASUREMENTS_RECORDED succeeds."""
    blade = await _make_blade(db_session, oh_user, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)

    resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "60"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["slot_number"] == "60"


@pytest.mark.asyncio
async def test_oh_operator_cannot_assign_slot_to_lptr_blade(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """OH_OPERATOR is forbidden from assigning slots to LPTR blades — 403."""
    blade = await _make_blade(db_session, oh_user, BladeType.LPTR, BladeStatus.SENT_TO_ASSEMBLY)

    resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "1"},
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assembly_operator_cannot_assign_slot_to_hptr_blade(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """ASSEMBLY_OPERATOR is forbidden from assigning slots to HPTR blades — 403."""
    blade = await _make_blade(db_session, oh_user, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)

    resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "60"},
        headers=assembly_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assembly_operator_can_assign_slot_to_lptr_blade(
    client: AsyncClient, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """ASSEMBLY_OPERATOR assigning a slot to an LPTR blade at SENT_TO_ASSEMBLY succeeds."""
    blade = await _make_blade(db_session, oh_user, BladeType.LPTR, BladeStatus.SENT_TO_ASSEMBLY)

    resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "1"},
        headers=assembly_headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_super_admin_can_assign_slot_to_either_type(
    client: AsyncClient, super_admin_headers: dict, oh_user: User, db_session
) -> None:
    """SUPER_ADMIN can assign slots to both HPTR and LPTR blades."""
    hptr_blade = await _make_blade(db_session, oh_user, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)
    lptr_blade = await _make_blade(db_session, oh_user, BladeType.LPTR, BladeStatus.SENT_TO_ASSEMBLY)

    hptr_resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(hptr_blade.id), "slot_number": "60"},
        headers=super_admin_headers,
    )
    assert hptr_resp.status_code == 201, hptr_resp.text

    lptr_resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(lptr_blade.id), "slot_number": "1"},
        headers=super_admin_headers,
    )
    assert lptr_resp.status_code == 201, lptr_resp.text


@pytest.mark.asyncio
async def test_hptr_blade_wrong_status_returns_409(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """An HPTR blade not yet at MEASUREMENTS_RECORDED cannot be slot-assigned — 409."""
    blade = await _make_blade(db_session, oh_user, BladeType.HPTR, BladeStatus.OH_INSPECTION)

    resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "60"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PUT /{slot_id}/balancing — role branch by blade_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oh_operator_can_update_balancing_for_hptr_blade(
    client: AsyncClient, auth_headers: dict, oh_user: User, db_session
) -> None:
    """OH_OPERATOR can record balancing results for an HPTR blade's slot."""
    blade = await _make_blade(db_session, oh_user, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)

    assign_resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "60"},
        headers=auth_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text
    slot_id = assign_resp.json()["id"]

    balancing_resp = await client.put(
        f"{BASE}/{slot_id}/balancing",
        json={"is_balanced": True, "balancing_remarks": "Balanced within tolerance"},
        headers=auth_headers,
    )
    assert balancing_resp.status_code == 200, balancing_resp.text
    assert balancing_resp.json()["is_balanced"] is True


@pytest.mark.asyncio
async def test_assembly_operator_cannot_update_balancing_for_hptr_blade(
    client: AsyncClient, auth_headers: dict, assembly_headers: dict, oh_user: User, db_session
) -> None:
    """ASSEMBLY_OPERATOR is forbidden from updating balancing on an HPTR slot — 403."""
    blade = await _make_blade(db_session, oh_user, BladeType.HPTR, BladeStatus.MEASUREMENTS_RECORDED)

    assign_resp = await client.post(
        f"{BASE}/assign",
        json={"blade_id": str(blade.id), "slot_number": "60"},
        headers=auth_headers,
    )
    slot_id = assign_resp.json()["id"]

    resp = await client.put(
        f"{BASE}/{slot_id}/balancing",
        json={"is_balanced": True},
        headers=assembly_headers,
    )
    assert resp.status_code == 403
