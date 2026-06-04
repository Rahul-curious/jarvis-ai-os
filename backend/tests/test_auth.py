from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domains.governance.models import AuditLog
from app.domains.identity.models import AuthSession, User

REGISTER_PAYLOAD = {
    "full_name": "Rahul Prakash",
    "email": "rahul@example.com",
    "password": "correct-horse-battery",
}


def test_register_creates_user_session_cookies_and_audit(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "rahul@example.com"
    assert client.cookies.get("jarvis_access_token") is not None
    assert client.cookies.get("jarvis_refresh_token") is not None

    async def inspect_db() -> tuple[int, int, int]:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            users = await session.scalar(select(func.count(User.id)))
            sessions = await session.scalar(select(func.count(AuthSession.id)))
            audits = await session.scalar(select(func.count(AuditLog.id)))
            return int(users or 0), int(sessions or 0), int(audits or 0)

    users, sessions, audits = asyncio.run(inspect_db())
    assert users == 1
    assert sessions == 1
    assert audits == 1


def test_duplicate_email_returns_conflict(client: TestClient) -> None:
    first_response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    duplicate_response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409


def test_login_succeeds_and_invalid_login_fails(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    client.post("/api/v1/auth/logout")

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "rahul@example.com", "password": "correct-horse-battery"},
    )
    failed_response = client.post(
        "/api/v1/auth/login",
        json={"email": "rahul@example.com", "password": "wrong-password"},
    )

    assert login_response.status_code == 200
    assert failed_response.status_code == 401


def test_profile_requires_authentication_and_returns_current_user(client: TestClient) -> None:
    unauthenticated_response = client.get("/api/v1/users/me")
    register_response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    profile_response = client.get("/api/v1/users/me")

    assert unauthenticated_response.status_code == 401
    assert register_response.status_code == 201
    assert profile_response.status_code == 200
    assert profile_response.json()["email"] == "rahul@example.com"


def test_refresh_rotates_session_and_logout_revokes_session(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    original_refresh_token = client.cookies.get("jarvis_refresh_token")

    refresh_response = client.post("/api/v1/auth/refresh")
    rotated_refresh_token = client.cookies.get("jarvis_refresh_token")
    logout_response = client.post("/api/v1/auth/logout")
    profile_response = client.get("/api/v1/users/me")

    assert refresh_response.status_code == 200
    assert rotated_refresh_token is not None
    assert rotated_refresh_token != original_refresh_token
    assert logout_response.status_code == 200
    assert profile_response.status_code == 401

    async def revoked_sessions() -> int:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            result = await session.scalar(
                select(func.count(AuthSession.id)).where(AuthSession.revoked_at.is_not(None))
            )
            return int(result or 0)

    assert asyncio.run(revoked_sessions()) == 1
