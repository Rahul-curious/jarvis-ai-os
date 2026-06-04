from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.domains.governance.audit import get_request_ip, get_request_user_agent, record_audit_event
from app.domains.identity.models import AuthSession, User
from app.domains.identity.schemas import LoginRequest, RegisterRequest
from app.domains.identity.security import (
    TokenError,
    TokenPair,
    create_token_pair,
    decode_token,
    ensure_aware,
    hash_password,
    hash_token,
    utc_now,
    verify_password,
)


class DuplicateEmailError(Exception):
    """Raised when a user registers with an existing email."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials or tokens are invalid."""


@dataclass(frozen=True)
class AuthResult:
    user: User
    session: AuthSession
    tokens: TokenPair


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def register(self, payload: RegisterRequest, request: Request) -> AuthResult:
        email = normalize_email(payload.email)
        existing_user = await self.get_user_by_email(email)
        if existing_user is not None:
            raise DuplicateEmailError("Email is already registered")

        user = User(
            email=email,
            full_name=payload.full_name.strip(),
            password_hash=hash_password(payload.password),
        )
        self.db.add(user)

        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise DuplicateEmailError("Email is already registered") from exc

        result = await self._create_session_for_user(user=user, request=request)
        await record_audit_event(
            self.db,
            action="auth.register",
            outcome="success",
            request=request,
            user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
        )
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(result.session)
        return result

    async def login(self, payload: LoginRequest, request: Request) -> AuthResult:
        email = normalize_email(payload.email)
        user = await self.get_user_by_email(email)

        invalid_credentials = (
            user is None
            or not user.is_active
            or not verify_password(payload.password, user.password_hash)
        )

        if invalid_credentials:
            await record_audit_event(
                self.db,
                action="auth.login",
                outcome="failure",
                request=request,
                metadata={"email": email},
            )
            await self.db.commit()
            raise InvalidCredentialsError("Invalid email or password")

        user.last_login_at = utc_now()
        result = await self._create_session_for_user(user=user, request=request)
        await record_audit_event(
            self.db,
            action="auth.login",
            outcome="success",
            request=request,
            user_id=user.id,
            resource_type="session",
            resource_id=str(result.session.id),
        )
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(result.session)
        return result

    async def refresh(self, refresh_token: str, request: Request) -> AuthResult:
        session, user = await self._get_valid_refresh_session(refresh_token)
        tokens = create_token_pair(user_id=user.id, session_id=session.id, settings=self.settings)
        session.refresh_token_hash = hash_token(tokens.refresh_token)
        session.refresh_token_jti = tokens.refresh_token_jti
        session.expires_at = tokens.refresh_expires_at

        await record_audit_event(
            self.db,
            action="auth.refresh",
            outcome="success",
            request=request,
            user_id=user.id,
            resource_type="session",
            resource_id=str(session.id),
        )
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(session)
        return AuthResult(user=user, session=session, tokens=tokens)

    async def logout(self, refresh_token: str | None, request: Request) -> None:
        if refresh_token is None:
            return

        try:
            session, _user = await self._get_valid_refresh_session(refresh_token)
        except InvalidCredentialsError:
            return

        session.revoked_at = utc_now()
        await record_audit_event(
            self.db,
            action="auth.logout",
            outcome="success",
            request=request,
            user_id=session.user_id,
            resource_type="session",
            resource_id=str(session.id),
        )
        await self.db.commit()

    async def get_current_user_from_access_token(self, access_token: str, request: Request) -> User:
        try:
            payload = decode_token(access_token, expected_type="access", settings=self.settings)
            session_id = uuid.UUID(str(payload["sid"]))
            user_id = uuid.UUID(str(payload["sub"]))
        except (KeyError, TypeError, ValueError, TokenError) as exc:
            await self._audit_auth_failure(request, reason="invalid_access_token")
            raise InvalidCredentialsError("Invalid authentication token") from exc

        result = await self.db.execute(
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(AuthSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if (
            session is None
            or session.user_id != user_id
            or session.revoked_at is not None
            or ensure_aware(session.expires_at) <= utc_now()
        ):
            await self._audit_auth_failure(request, reason="inactive_session")
            raise InvalidCredentialsError("Invalid authentication session")

        user = await self.db.get(User, user_id)
        if user is None or not user.is_active:
            await self._audit_auth_failure(request, reason="inactive_user")
            raise InvalidCredentialsError("Invalid authentication user")

        return user

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == normalize_email(email)))
        return result.scalar_one_or_none()

    async def _create_session_for_user(self, *, user: User, request: Request) -> AuthResult:
        session = AuthSession(
            user_id=user.id,
            refresh_token_hash="pending",
            refresh_token_jti="pending",
            user_agent=get_request_user_agent(request),
            ip_address=get_request_ip(request),
            expires_at=utc_now(),
        )
        self.db.add(session)
        await self.db.flush()

        tokens = create_token_pair(user_id=user.id, session_id=session.id, settings=self.settings)
        session.refresh_token_hash = hash_token(tokens.refresh_token)
        session.refresh_token_jti = tokens.refresh_token_jti
        session.expires_at = tokens.refresh_expires_at
        await self.db.flush()

        return AuthResult(user=user, session=session, tokens=tokens)

    async def _get_valid_refresh_session(self, refresh_token: str) -> tuple[AuthSession, User]:
        try:
            payload = decode_token(refresh_token, expected_type="refresh", settings=self.settings)
            session_id = uuid.UUID(str(payload["sid"]))
            refresh_token_jti = str(payload["jti"])
        except (KeyError, TypeError, ValueError, TokenError) as exc:
            raise InvalidCredentialsError("Invalid refresh token") from exc

        session = await self.db.get(AuthSession, session_id)
        if (
            session is None
            or session.revoked_at is not None
            or ensure_aware(session.expires_at) <= utc_now()
            or session.refresh_token_jti != refresh_token_jti
            or session.refresh_token_hash != hash_token(refresh_token)
        ):
            raise InvalidCredentialsError("Invalid refresh session")

        user = await self.db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError("Invalid refresh user")

        return session, user

    async def _audit_auth_failure(self, request: Request, *, reason: str) -> None:
        await record_audit_event(
            self.db,
            action="auth.access",
            outcome="failure",
            request=request,
            metadata={"reason": reason},
        )
        await self.db.commit()
