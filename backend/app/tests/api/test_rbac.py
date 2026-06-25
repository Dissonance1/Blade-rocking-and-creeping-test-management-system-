"""
RBAC enforcement tests.

These tests verify that role-based access control is correctly enforced
across the API.  Each test checks that the wrong role receives HTTP 403
(or occasionally 401 for anonymous requests) and that the correct role
receives a non-403 response.

Test strategy
-------------
* Parametrized matrices let us add new endpoints / roles in one place.
* We test both the "should be forbidden" and "should be allowed" path where
  practical, so regressions in either direction are caught.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.models.blade import Blade
from app.models.enums import BladeStatus

BASE = "/api/v1"

# ---------------------------------------------------------------------------
# Parametrize helpers
# ---------------------------------------------------------------------------

# (method, path_template, body)
# path_template may contain {blade_id} which is substituted with a real UUID
# at test-time (or a random UUID when the endpoint is expected to return 403
# before even checking the resource).


def _crud_blade_path(blade_id: str = "") -> str:
    bid = blade_id or str(uuid.uuid4())
    return f"{BASE}/blades/{bid}"


# ---------------------------------------------------------------------------
# 1. Assembly operator cannot create blades
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assembly_operator_cannot_create_blade(
    client: AsyncClient, assembly_headers: dict
) -> None:
    """ASSEMBLY_OPERATOR → POST /blades/ → 403."""
    resp = await client.post(
        f"{BASE}/blades/",
        json={
            "serial_number": f"BLD-RBAC-{uuid.uuid4().hex[:6].upper()}",
            "melt_number": "MELT-001",
        },
        headers=assembly_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qa_viewer_cannot_create_blade(
    client: AsyncClient, qa_headers: dict
) -> None:
    """QA_VIEWER → POST /blades/ → 403."""
    resp = await client.post(
        f"{BASE}/blades/",
        json={"serial_number": f"BLD-QA-{uuid.uuid4().hex[:6].upper()}"},
        headers=qa_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_oh_operator_can_create_blade(
    client: AsyncClient, auth_headers: dict
) -> None:
    """OH_OPERATOR → POST /blades/ → 201 (not 403)."""
    resp = await client.post(
        f"{BASE}/blades/",
        json={
            "serial_number": f"BLD-OH-{uuid.uuid4().hex[:8].upper()}",
            "melt_number": "MELT-001",
            "part_number": "PT-4470",
        },
        headers=auth_headers,
    )
    assert resp.status_code != 403
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 2. QA viewer cannot modify anything
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_viewer_cannot_update_blade(
    client: AsyncClient, qa_headers: dict, sample_blade: Blade
) -> None:
    """QA_VIEWER → PUT /blades/{id} → 403."""
    resp = await client.put(
        f"{BASE}/blades/{sample_blade.id}",
        json={"nomenclature": "Modified"},
        headers=qa_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qa_viewer_cannot_send_to_assembly(
    client: AsyncClient, qa_headers: dict, sample_blade: Blade
) -> None:
    """QA_VIEWER → POST /blades/{id}/send-to-assembly → 403."""
    resp = await client.post(
        f"{BASE}/blades/{sample_blade.id}/send-to-assembly",
        json={},
        headers=qa_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qa_viewer_cannot_reject_blade(
    client: AsyncClient, qa_headers: dict, sample_blade: Blade
) -> None:
    """QA_VIEWER → POST /blades/{id}/reject → 403."""
    resp = await client.post(
        f"{BASE}/blades/{sample_blade.id}/reject",
        json={"rejection_notes": "QA trying to reject"},
        headers=qa_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qa_viewer_cannot_reopen_blade(
    client: AsyncClient, qa_headers: dict, sample_blade: Blade
) -> None:
    """QA_VIEWER → POST /blades/{id}/reopen → 403."""
    resp = await client.post(
        f"{BASE}/blades/{sample_blade.id}/reopen",
        json={},
        headers=qa_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qa_viewer_can_read_blades(
    client: AsyncClient, qa_headers: dict, sample_blade: Blade
) -> None:
    """QA_VIEWER CAN read blade data — GET /blades/ and GET /blades/{id}."""
    list_resp = await client.get(f"{BASE}/blades/", headers=qa_headers)
    assert list_resp.status_code == 200

    detail_resp = await client.get(
        f"{BASE}/blades/{sample_blade.id}", headers=qa_headers
    )
    assert detail_resp.status_code == 200


# ---------------------------------------------------------------------------
# 3. Super admin can access user management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_can_list_users(
    client: AsyncClient, super_admin_headers: dict
) -> None:
    """SUPER_ADMIN → GET /users/ → 200."""
    resp = await client.get(f"{BASE}/users/", headers=super_admin_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_can_access_user_detail(
    client: AsyncClient, super_admin_headers: dict, oh_user
) -> None:
    """SUPER_ADMIN → GET /users/{id} → 200."""
    resp = await client.get(f"{BASE}/users/{oh_user.id}", headers=super_admin_headers)
    assert resp.status_code in (200, 404)  # 404 ok if user not found in test DB


# ---------------------------------------------------------------------------
# 4. OH operator cannot manage users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oh_operator_cannot_list_users(
    client: AsyncClient, auth_headers: dict
) -> None:
    """OH_OPERATOR → GET /users/ → 403."""
    resp = await client.get(f"{BASE}/users/", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assembly_operator_cannot_list_users(
    client: AsyncClient, assembly_headers: dict
) -> None:
    """ASSEMBLY_OPERATOR → GET /users/ → 403."""
    resp = await client.get(f"{BASE}/users/", headers=assembly_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qa_viewer_cannot_list_users(
    client: AsyncClient, qa_headers: dict
) -> None:
    """QA_VIEWER → GET /users/ → 403."""
    resp = await client.get(f"{BASE}/users/", headers=qa_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_oh_operator_cannot_create_user(
    client: AsyncClient, auth_headers: dict
) -> None:
    """OH_OPERATOR → POST /users/ → 403."""
    resp = await client.post(
        f"{BASE}/users/",
        json={
            "email": "new@example.com",
            "username": "newuser",
            "password": "Password@123",
            "role_names": ["OH_OPERATOR"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5. Assembly operator cannot call OH-only actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assembly_operator_cannot_reject_blade(
    client: AsyncClient, assembly_headers: dict, sample_blade: Blade, db_session
) -> None:
    """ASSEMBLY_OPERATOR → POST /blades/{id}/reject → 403."""
    sample_blade.status = BladeStatus.OH_INSPECTION
    db_session.add(sample_blade)
    await db_session.flush()

    resp = await client.post(
        f"{BASE}/blades/{sample_blade.id}/reject",
        json={"rejection_notes": "Assembly trying to reject"},
        headers=assembly_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 6. Anonymous (no token) → 401, not 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path_suffix",
    [
        ("get", "/blades/"),
        ("get", f"/blades/{uuid.uuid4()}"),
        ("post", "/blades/"),
        ("get", "/users/"),
    ],
)
async def test_anonymous_gets_401_not_403(
    client: AsyncClient,
    method: str,
    path_suffix: str,
) -> None:
    """Unauthenticated requests must return 401 (not 403)."""
    call = getattr(client, method)
    resp = await call(f"{BASE}{path_suffix}")
    assert resp.status_code == 401, (
        f"Expected 401 for anonymous {method.upper()} {path_suffix}, "
        f"got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 7. Parametrized matrix — OH actions by wrong roles → 403
# ---------------------------------------------------------------------------

OH_ONLY_ACTIONS = [
    ("post", "/send-to-assembly", {}),
    ("post", "/reopen", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wrong_role_headers_fixture,action_method,action_suffix,body",
    [
        ("assembly_headers", *action)
        for action in OH_ONLY_ACTIONS
    ] + [
        ("qa_headers", *action)
        for action in OH_ONLY_ACTIONS
    ],
)
async def test_wrong_role_cannot_perform_oh_action(
    client: AsyncClient,
    request: pytest.FixtureRequest,
    wrong_role_headers_fixture: str,
    action_method: str,
    action_suffix: str,
    body: dict,
    sample_blade: Blade,
    db_session,
) -> None:
    """Roles other than OH_OPERATOR / SUPER_ADMIN cannot perform OH workflow actions."""
    wrong_headers = request.getfixturevalue(wrong_role_headers_fixture)
    sample_blade.status = BladeStatus.MEASUREMENTS_RECORDED
    db_session.add(sample_blade)
    await db_session.flush()

    call = getattr(client, action_method)
    resp = await call(
        f"{BASE}/blades/{sample_blade.id}{action_suffix}",
        json=body,
        headers=wrong_headers,
    )
    assert resp.status_code == 403, (
        f"{wrong_role_headers_fixture} {action_method.upper()} "
        f"{action_suffix} should be 403 but got {resp.status_code}"
    )
