from __future__ import annotations

from datetime import datetime

from fastapi import Response

from app.core.config import Settings
from app.domains.identity.security import TokenPair, utc_now


def set_auth_cookies(response: Response, *, tokens: TokenPair, settings: Settings) -> None:
    _set_cookie(
        response,
        name=settings.access_cookie_name,
        value=tokens.access_token,
        expires_at=tokens.access_expires_at,
        settings=settings,
    )
    _set_cookie(
        response,
        name=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        expires_at=tokens.refresh_expires_at,
        settings=settings,
    )


def clear_auth_cookies(response: Response, *, settings: Settings) -> None:
    response.delete_cookie(
        settings.access_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )
    response.delete_cookie(
        settings.refresh_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


def _set_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    expires_at: datetime,
    settings: Settings,
) -> None:
    max_age = max(0, int((expires_at - utc_now()).total_seconds()))
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )
