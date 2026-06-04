from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()


class TokenError(Exception):
    """Raised when a JWT cannot be trusted."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    refresh_token_jti: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def create_token_pair(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    settings: Settings,
) -> TokenPair:
    now = utc_now()
    access_expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    refresh_expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    refresh_token_jti = secrets.token_urlsafe(32)

    access_token = _encode_token(
        settings=settings,
        user_id=user_id,
        session_id=session_id,
        token_type="access",
        expires_at=access_expires_at,
    )
    refresh_token = _encode_token(
        settings=settings,
        user_id=user_id,
        session_id=session_id,
        token_type="refresh",
        expires_at=refresh_expires_at,
        jti=refresh_token_jti,
    )

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        refresh_token_jti=refresh_token_jti,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )


def decode_token(
    token: str,
    *,
    expected_type: Literal["access", "refresh"],
    settings: Settings,
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid authentication token") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Invalid authentication token type")

    return payload


def _encode_token(
    *,
    settings: Settings,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    token_type: Literal["access", "refresh"],
    expires_at: datetime,
    jti: str | None = None,
) -> str:
    now = utc_now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": expires_at,
        "type": token_type,
    }
    if jti is not None:
        payload["jti"] = jti

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
