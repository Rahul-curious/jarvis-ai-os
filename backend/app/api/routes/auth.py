from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import clear_auth_cookies, set_auth_cookies
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domains.identity.schemas import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
)
from app.domains.identity.service import AuthService, DuplicateEmailError, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])
DB_SESSION_DEP = Depends(get_db_session)
SETTINGS_DEP = Depends(get_settings)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> AuthResponse:
    auth_service = AuthService(db, settings)
    try:
        result = await auth_service.register(payload, request)
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from exc

    set_auth_cookies(response, tokens=result.tokens, settings=settings)
    return AuthResponse(user=result.user)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> AuthResponse:
    auth_service = AuthService(db, settings)
    try:
        result = await auth_service.login(payload, request)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from exc

    set_auth_cookies(response, tokens=result.tokens, settings=settings)
    return AuthResponse(user=result.user)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> AuthResponse:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    auth_service = AuthService(db, settings)
    try:
        result = await auth_service.refresh(refresh_token, request)
    except InvalidCredentialsError as exc:
        clear_auth_cookies(response, settings=settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalid",
        ) from exc

    set_auth_cookies(response, tokens=result.tokens, settings=settings)
    return AuthResponse(user=result.user)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MessageResponse:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    auth_service = AuthService(db, settings)
    await auth_service.logout(refresh_token, request)
    clear_auth_cookies(response, settings=settings)
    return MessageResponse(detail="logged_out")
