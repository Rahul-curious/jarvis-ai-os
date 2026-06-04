from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.governance.models import AuditLog


def get_request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def get_request_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


async def record_audit_event(
    db: AsyncSession,
    *,
    action: str,
    outcome: str,
    request: Request,
    user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    event = AuditLog(
        user_id=user_id,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=get_request_ip(request),
        user_agent=get_request_user_agent(request),
        event_metadata=metadata or {},
    )
    db.add(event)
    return event
