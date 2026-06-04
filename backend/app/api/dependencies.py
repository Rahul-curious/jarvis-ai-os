from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domains.identity.models import User
from app.domains.identity.service import AuthService, InvalidCredentialsError

DB_SESSION_DEP = Depends(get_db_session)
SETTINGS_DEP = Depends(get_settings)


async def get_current_user(
    request: Request,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> User:
    access_token = request.cookies.get(settings.access_cookie_name)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    auth_service = AuthService(db, settings)
    try:
        return await auth_service.get_current_user_from_access_token(access_token, request)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        ) from exc
