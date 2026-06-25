"""
API tests for authentication endpoints.

Coverage:
    POST /api/v1/auth/login
    POST /api/v1/auth/refresh
    POST /api/v1/auth/logout
    GET  /api/v1/auth/me
    POST /api/v1/auth/me/change-password
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.user import User

BASE = "/api/v1/auth"


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, oh_user: User) -> None:
    """Valid credentials return a JWT token pair and HTTP 200."""
    response = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "Test@123"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, oh_user: User) -> None:
    """Incorrect password returns HTTP 401."""
    response = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "access_token" not in response.json()


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient) -> None:
    """Email that does not exist returns HTTP 401 (no user enumeration)."""
    response = await client.post(
        f"{BASE}/login",
        json={"email": "ghost.user@nowhere.example.com", "password": "Test@123"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(
    client: AsyncClient, db_session, oh_user: User
) -> None:
    """Deactivated accounts cannot log in — returns 401."""
    oh_user.is_active = False
    db_session.add(oh_user)
    await db_session.flush()

    response = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "Test@123"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient) -> None:
    """Payload missing required fields returns HTTP 422."""
    response = await client.post(f"{BASE}/login", json={"email": "a@b.com"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_authenticated(
    client: AsyncClient, oh_user: User, auth_headers: dict
) -> None:
    """Authenticated user receives their own profile."""
    response = await client.get(f"{BASE}/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == oh_user.email
    assert data["username"] == oh_user.username
    assert "hashed_password" not in data  # must never be exposed


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient) -> None:
    """Request without an Authorization header returns HTTP 401."""
    response = await client.get(f"{BASE}/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient) -> None:
    """Malformed Bearer token returns HTTP 401."""
    response = await client.get(
        f"{BASE}/me",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient, oh_user: User) -> None:
    """Valid refresh token returns a new access + refresh token pair."""
    login_resp = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "Test@123"},
    )
    assert login_resp.status_code == 200
    refresh_tok = login_resp.json()["refresh_token"]

    refresh_resp = await client.post(
        f"{BASE}/refresh",
        json={"refresh_token": refresh_tok},
    )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # New token pair should differ from the original
    assert data["access_token"] != login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_token_missing(client: AsyncClient) -> None:
    """Calling /refresh with no token returns HTTP 401."""
    response = await client.post(f"{BASE}/refresh", json={})
    assert response.status_code in (401, 422)


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient) -> None:
    """Supplying a garbage refresh token returns HTTP 401."""
    response = await client.post(
        f"{BASE}/refresh",
        json={"refresh_token": "garbage.token.value"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_access_token_as_refresh(
    client: AsyncClient, oh_user: User
) -> None:
    """Passing an access token where a refresh token is expected returns 401."""
    login_resp = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "Test@123"},
    )
    access_tok = login_resp.json()["access_token"]

    response = await client.post(
        f"{BASE}/refresh",
        json={"refresh_token": access_tok},  # wrong token type
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /me/change-password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_success(
    client: AsyncClient, oh_user: User, auth_headers: dict
) -> None:
    """
    Authenticated user can change their own password.

    After the change the old credentials should fail and the new ones succeed.
    """
    resp = await client.post(
        f"{BASE}/me/change-password",
        headers=auth_headers,
        json={
            "current_password": "Test@123",
            "new_password": "NewPass@456",
            "confirm_new_password": "NewPass@456",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "message" in data

    # Old credentials should now fail
    old_login = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "Test@123"},
    )
    assert old_login.status_code == 401

    # New credentials should work
    new_login = await client.post(
        f"{BASE}/login",
        json={"email": oh_user.email, "password": "NewPass@456"},
    )
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Supplying the wrong current password returns HTTP 400."""
    resp = await client.post(
        f"{BASE}/me/change-password",
        headers=auth_headers,
        json={
            "current_password": "WrongOldPass!",
            "new_password": "NewPass@456",
            "confirm_new_password": "NewPass@456",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_password_mismatch_confirm(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Mismatched new_password / confirm returns HTTP 422."""
    resp = await client.post(
        f"{BASE}/me/change-password",
        headers=auth_headers,
        json={
            "current_password": "Test@123",
            "new_password": "NewPass@456",
            "confirm_new_password": "DifferentPass@789",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_password_unauthenticated(client: AsyncClient) -> None:
    """Unauthenticated request to /me/change-password returns 401."""
    resp = await client.post(
        f"{BASE}/me/change-password",
        json={
            "current_password": "Test@123",
            "new_password": "NewPass@456",
            "confirm_new_password": "NewPass@456",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password_too_short(
    client: AsyncClient, auth_headers: dict
) -> None:
    """New password shorter than 8 characters returns HTTP 422."""
    resp = await client.post(
        f"{BASE}/me/change-password",
        headers=auth_headers,
        json={
            "current_password": "Test@123",
            "new_password": "Sh0rt",
            "confirm_new_password": "Sh0rt",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_success(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Logout returns HTTP 200 and a success message."""
    resp = await client.post(f"{BASE}/logout", headers=auth_headers)
    assert resp.status_code == 200
    assert "message" in resp.json()


@pytest.mark.asyncio
async def test_logout_unauthenticated(client: AsyncClient) -> None:
    """Logout without auth returns 401."""
    resp = await client.post(f"{BASE}/logout")
    assert resp.status_code == 401
