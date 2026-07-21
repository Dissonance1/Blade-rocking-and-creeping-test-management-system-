"""
API tests for the /api/v1/blades endpoints.

Coverage:
    GET    /blades/
    GET    /blades/{id}
    POST   /blades/{id}/send-to-assembly
    POST   /blades/{id}/reopen

Blade creation is exclusively via POST /work-orders/ (grid scaffold) —
see test_work_orders.py — there is no standalone blade-creation endpoint.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.models.blade import Blade
from app.models.enums import BladeStatus
from app.models.user import User

BASE = "/api/v1/blades"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET / — list blades
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_blades_paginated(
    client: AsyncClient, auth_headers: dict, sample_blade: Blade
) -> None:
    """List endpoint returns a paginated response with the expected structure."""
    resp = await client.get(BASE + "/", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_blades_default_page_size(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Default page_size of 20 is applied when not specified."""
    resp = await client.get(BASE + "/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["page_size"] == 20


@pytest.mark.asyncio
async def test_get_blades_filter_by_status(
    client: AsyncClient, auth_headers: dict, sample_blade: Blade
) -> None:
    """Filter by status=OH_INSPECTION returns only blades in that status."""
    resp = await client.get(
        BASE + "/",
        params={"status": BladeStatus.OH_INSPECTION.value},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["status"] == BladeStatus.OH_INSPECTION.value


@pytest.mark.asyncio
async def test_get_blades_unauthenticated(client: AsyncClient) -> None:
    """Listing blades without auth returns 401."""
    resp = await client.get(BASE + "/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /{blade_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_blade_by_id(
    client: AsyncClient, auth_headers: dict, sample_blade: Blade
) -> None:
    """GET /blades/{id} returns the full blade record."""
    resp = await client.get(f"{BASE}/{sample_blade.id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == str(sample_blade.id)
    assert data["serial_number"] == sample_blade.serial_number


@pytest.mark.asyncio
async def test_get_blade_not_found(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Non-existent blade ID returns 404."""
    resp = await client.get(f"{BASE}/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_blade_unauthenticated(
    client: AsyncClient, sample_blade: Blade
) -> None:
    """GET /blades/{id} without auth returns 401."""
    resp = await client.get(f"{BASE}/{sample_blade.id}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /{blade_id}/send-to-assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_to_assembly_with_measurements(
    client: AsyncClient,
    auth_headers: dict,
    sample_blade_with_measurements: Blade,
) -> None:
    """
    A blade in MEASUREMENTS_RECORDED transitions to SENT_TO_ASSEMBLY.

    The response must reflect the updated status.
    """
    resp = await client.post(
        f"{BASE}/{sample_blade_with_measurements.id}/send-to-assembly",
        json={"remarks": "Ready for balancing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == BladeStatus.SENT_TO_ASSEMBLY.value


@pytest.mark.asyncio
async def test_send_to_assembly_from_oh_inspection(
    client: AsyncClient,
    auth_headers: dict,
    sample_blade: Blade,
    db_session,
) -> None:
    """A blade in OH_INSPECTION can also be sent to assembly."""
    # Promote sample_blade to OH_INSPECTION (it is in CREATED; create_blade sets OH_INSPECTION)
    sample_blade.status = BladeStatus.OH_INSPECTION
    db_session.add(sample_blade)
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/{sample_blade.id}/send-to-assembly",
        json={"remarks": "Direct from OH inspection"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == BladeStatus.SENT_TO_ASSEMBLY.value


@pytest.mark.asyncio
async def test_send_to_assembly_wrong_status(
    client: AsyncClient,
    auth_headers: dict,
    sample_blade: Blade,
) -> None:
    """A blade in CREATED status cannot be sent to assembly — returns 409."""
    resp = await client.post(
        f"{BASE}/{sample_blade.id}/send-to-assembly",
        json={},
        headers=auth_headers,
    )
    # Blade is CREATED; valid sources are OH_INSPECTION / MEASUREMENTS_RECORDED / REOPENED
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_send_to_assembly_not_found(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Non-existent blade returns 404."""
    resp = await client.post(
        f"{BASE}/{uuid.uuid4()}/send-to-assembly",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_to_assembly_as_assembly_operator_forbidden(
    client: AsyncClient,
    assembly_headers: dict,
    sample_blade_with_measurements: Blade,
) -> None:
    """ASSEMBLY_OPERATOR cannot call send-to-assembly — returns 403."""
    resp = await client.post(
        f"{BASE}/{sample_blade_with_measurements.id}/send-to-assembly",
        json={},
        headers=assembly_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_send_to_assembly_rejects_hptr_blade(
    client: AsyncClient,
    auth_headers: dict,
    sample_blade_with_measurements: Blade,
    db_session,
) -> None:
    """HPTR blades stay in OH — send-to-assembly returns 422 regardless of status."""
    from app.models.enums import BladeType

    sample_blade_with_measurements.blade_type = BladeType.HPTR
    db_session.add(sample_blade_with_measurements)
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/{sample_blade_with_measurements.id}/send-to-assembly",
        json={"remarks": "Should be rejected"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "HPTR" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /{blade_id}/reopen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reopen_rejected_blade(
    client: AsyncClient,
    auth_headers: dict,
    sample_blade: Blade,
    db_session,
) -> None:
    """
    REJECTED → REOPENED is the first step of the reopen workflow.

    After reopen the blade status should be REOPENED (or OH_INSPECTION if
    the endpoint transitions directly to OH_INSPECTION).
    """
    sample_blade.status = BladeStatus.REJECTED
    db_session.add(sample_blade)
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/{sample_blade.id}/reopen",
        json={"remarks": "Rejected in error — reopen for re-inspection"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in (
        BladeStatus.REOPENED.value,
        BladeStatus.OH_INSPECTION.value,
    )


@pytest.mark.asyncio
async def test_reopen_non_rejected_blade_forbidden(
    client: AsyncClient,
    auth_headers: dict,
    sample_blade: Blade,
    db_session,
) -> None:
    """Cannot reopen a blade that is not in REJECTED status — returns 409."""
    sample_blade.status = BladeStatus.COMPLETED
    db_session.add(sample_blade)
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/{sample_blade.id}/reopen",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reopen_not_found(client: AsyncClient, auth_headers: dict) -> None:
    """Reopen on a non-existent blade returns 404."""
    resp = await client.post(f"{BASE}/{uuid.uuid4()}/reopen", json={}, headers=auth_headers)
    assert resp.status_code == 404
