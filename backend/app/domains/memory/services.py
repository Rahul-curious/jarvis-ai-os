from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domains.governance.audit import record_audit_event
from app.domains.identity.models import User
from app.domains.memory.models import MemoryItem
from app.domains.memory.repository import MemoryRepository
from app.domains.memory.schemas import (
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryRead,
    MemoryReferenceRead,
    MemoryReinforceRequest,
    MemorySearchRequest,
    MemoryType,
    MemoryUpdateRequest,
)


class MemoryNotFoundError(Exception):
    """Raised when a memory cannot be found for the authenticated user."""


class MemoryValidationError(Exception):
    """Raised when a memory request violates a domain rule."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def calculate_memory_score(memory: MemoryItem) -> float:
    importance_component = memory.importance_score * 0.7
    reinforcement_component = min(memory.reinforcement_count * 0.03, 0.3)
    return round(min(1.0, importance_component + reinforcement_component), 4)


def serialize_memory(memory: MemoryItem) -> MemoryRead:
    references = [
        MemoryReferenceRead.model_validate(reference) for reference in sorted(
            memory.references,
            key=lambda item: item.created_at,
        )
    ]
    return MemoryRead(
        id=memory.id,
        user_id=memory.user_id,
        memory_type=MemoryType(memory.memory_type),
        category=memory.category,
        content=memory.content,
        importance_score=memory.importance_score,
        reinforcement_count=memory.reinforcement_count,
        memory_score=calculate_memory_score(memory),
        source=memory.source,
        expires_at=memory.expires_at,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        last_accessed_at=memory.last_accessed_at,
        references=references,
    )


class BaseMemoryService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repository = MemoryRepository(db)

    async def _get_active_memory(
        self,
        *,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        include_expired: bool = False,
    ) -> MemoryItem:
        memory = await self.repository.get_for_user(
            memory_id=memory_id,
            user_id=user_id,
            include_expired=include_expired,
            now=utc_now(),
        )
        if memory is None:
            raise MemoryNotFoundError("Memory not found")
        return memory

    async def _record_memory_event(
        self,
        *,
        memory: MemoryItem,
        user_id: uuid.UUID,
        event_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.repository.add_event(
            memory_item_id=memory.id,
            user_id=user_id,
            event_type=event_type,
            score_after=calculate_memory_score(memory),
            metadata=metadata,
        )

    async def _record_audit(
        self,
        *,
        action: str,
        request: Request,
        user_id: uuid.UUID,
        memory_id: uuid.UUID,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await record_audit_event(
            self.db,
            action=action,
            outcome="success",
            request=request,
            user_id=user_id,
            resource_type="memory_item",
            resource_id=str(memory_id),
            metadata=metadata,
        )


class MemoryCreateService(BaseMemoryService):
    async def create(
        self,
        *,
        current_user: User,
        payload: MemoryCreateRequest,
        request: Request,
    ) -> MemoryRead:
        expires_at = self._resolve_expiration(payload)
        memory = await self.repository.create(
            user_id=current_user.id,
            memory_type=payload.memory_type,
            category=payload.category,
            content=payload.content,
            importance_score=payload.importance_score,
            source=payload.source,
            expires_at=expires_at,
            references=payload.references,
        )
        await self.db.flush()
        await self._record_memory_event(
            memory=memory,
            user_id=current_user.id,
            event_type="created",
            metadata={"source": payload.source, "memory_type": payload.memory_type.value},
        )
        await self._record_audit(
            action="memory.create",
            request=request,
            user_id=current_user.id,
            memory_id=memory.id,
            metadata={"memory_type": payload.memory_type.value, "category": payload.category},
        )
        await self.db.commit()
        return serialize_memory(
            await self.repository.get_for_user(
                memory_id=memory.id,
                user_id=current_user.id,
                include_expired=True,
            )
            or memory
        )

    def _resolve_expiration(self, payload: MemoryCreateRequest) -> datetime | None:
        if payload.expires_at is not None:
            expires_at = ensure_aware(payload.expires_at)
            if expires_at <= utc_now():
                raise MemoryValidationError("expires_at must be in the future")
            return expires_at

        if payload.memory_type == MemoryType.short_term:
            return utc_now() + timedelta(hours=self.settings.short_term_memory_default_ttl_hours)

        return None


class MemoryUpdateService(BaseMemoryService):
    async def update(
        self,
        *,
        memory_id: uuid.UUID,
        current_user: User,
        payload: MemoryUpdateRequest,
        request: Request,
    ) -> MemoryRead:
        memory = await self._get_active_memory(memory_id=memory_id, user_id=current_user.id)
        updates = payload.model_dump(exclude_unset=True, exclude={"references"})
        if "memory_type" in updates and updates["memory_type"] is not None:
            updates["memory_type"] = updates["memory_type"].value

        if "expires_at" in updates and updates["expires_at"] is not None:
            expires_at = ensure_aware(updates["expires_at"])
            if expires_at <= utc_now():
                raise MemoryValidationError("expires_at must be in the future")
            updates["expires_at"] = expires_at

        for field_name, value in updates.items():
            setattr(memory, field_name, value)

        if payload.references is not None:
            await self.repository.replace_references(memory.id, payload.references)

        if memory.memory_type == MemoryType.short_term.value and memory.expires_at is None:
            memory.expires_at = utc_now() + timedelta(
                hours=self.settings.short_term_memory_default_ttl_hours
            )

        await self.db.flush()
        await self._record_memory_event(
            memory=memory,
            user_id=current_user.id,
            event_type="updated",
            metadata={"updated_fields": sorted(payload.model_fields_set)},
        )
        await self._record_audit(
            action="memory.update",
            request=request,
            user_id=current_user.id,
            memory_id=memory.id,
            metadata={"updated_fields": sorted(payload.model_fields_set)},
        )
        await self.db.commit()
        refreshed = await self.repository.get_for_user(
            memory_id=memory.id,
            user_id=current_user.id,
            include_expired=True,
        )
        return serialize_memory(refreshed or memory)

    async def delete(
        self,
        *,
        memory_id: uuid.UUID,
        current_user: User,
        request: Request,
    ) -> None:
        memory = await self._get_active_memory(
            memory_id=memory_id,
            user_id=current_user.id,
            include_expired=True,
        )
        memory.deleted_at = utc_now()
        await self.db.flush()
        await self._record_memory_event(
            memory=memory,
            user_id=current_user.id,
            event_type="deleted",
        )
        await self._record_audit(
            action="memory.delete",
            request=request,
            user_id=current_user.id,
            memory_id=memory.id,
        )
        await self.db.commit()


class MemorySearchService(BaseMemoryService):
    async def list_memories(
        self,
        *,
        current_user: User,
        memory_type: MemoryType | None,
        category: str | None,
        include_expired: bool,
        limit: int,
        offset: int,
    ) -> MemoryListResponse:
        items, total = await self.repository.list_for_user(
            user_id=current_user.id,
            memory_type=memory_type,
            category=category,
            include_expired=include_expired,
            limit=limit,
            offset=offset,
            now=utc_now(),
        )
        return MemoryListResponse(
            items=[serialize_memory(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def search(
        self,
        *,
        current_user: User,
        payload: MemorySearchRequest,
    ) -> MemoryListResponse:
        items, total = await self.repository.search_for_user(
            user_id=current_user.id,
            keyword=payload.keyword,
            category=payload.category,
            memory_type=payload.memory_type,
            min_importance_score=payload.min_importance_score,
            include_expired=payload.include_expired,
            limit=payload.limit,
            offset=payload.offset,
            now=utc_now(),
        )
        return MemoryListResponse(
            items=[serialize_memory(item) for item in items],
            total=total,
            limit=payload.limit,
            offset=payload.offset,
        )


class MemoryRecallService(BaseMemoryService):
    async def recall(
        self,
        *,
        memory_id: uuid.UUID,
        current_user: User,
        request: Request,
    ) -> MemoryRead:
        memory = await self._get_active_memory(memory_id=memory_id, user_id=current_user.id)
        memory.reinforcement_count += 1
        memory.last_accessed_at = utc_now()
        await self.db.flush()
        await self._record_memory_event(
            memory=memory,
            user_id=current_user.id,
            event_type="accessed",
        )
        await self._record_audit(
            action="memory.access",
            request=request,
            user_id=current_user.id,
            memory_id=memory.id,
        )
        await self.db.commit()
        refreshed = await self.repository.get_for_user(
            memory_id=memory.id,
            user_id=current_user.id,
        )
        return serialize_memory(refreshed or memory)


class MemoryReinforcementService(BaseMemoryService):
    async def reinforce(
        self,
        *,
        current_user: User,
        payload: MemoryReinforceRequest,
        request: Request,
    ) -> MemoryRead:
        memory = await self._get_active_memory(memory_id=payload.memory_id, user_id=current_user.id)
        memory.reinforcement_count += payload.amount
        memory.last_accessed_at = utc_now()
        await self.db.flush()
        await self._record_memory_event(
            memory=memory,
            user_id=current_user.id,
            event_type="reinforced",
            metadata={"amount": payload.amount, "reason": payload.reason},
        )
        await self._record_audit(
            action="memory.reinforce",
            request=request,
            user_id=current_user.id,
            memory_id=memory.id,
            metadata={"amount": payload.amount},
        )
        await self.db.commit()
        refreshed = await self.repository.get_for_user(
            memory_id=memory.id,
            user_id=current_user.id,
        )
        return serialize_memory(refreshed or memory)
