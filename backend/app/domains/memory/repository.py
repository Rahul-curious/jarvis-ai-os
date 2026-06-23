from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.memory.models import MemoryEvent, MemoryItem, MemoryReference
from app.domains.memory.schemas import MemoryReferenceCreate, MemoryType


class MemoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        memory_type: MemoryType,
        category: str,
        content: str,
        importance_score: float,
        source: str,
        expires_at: datetime | None,
        references: list[MemoryReferenceCreate],
    ) -> MemoryItem:
        memory = MemoryItem(
            user_id=user_id,
            memory_type=memory_type.value,
            category=category,
            content=content,
            importance_score=importance_score,
            source=source,
            expires_at=expires_at,
        )
        self.db.add(memory)
        await self.db.flush()
        await self.replace_references(memory.id, references)
        await self.db.flush()
        return memory

    async def get_for_user(
        self,
        *,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        include_deleted: bool = False,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        statement = (
            select(MemoryItem)
            .options(selectinload(MemoryItem.references))
            .where(MemoryItem.id == memory_id, MemoryItem.user_id == user_id)
        )
        statement = self._apply_lifecycle_filters(
            statement,
            include_deleted=include_deleted,
            include_expired=include_expired,
            now=now,
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        memory_type: MemoryType | None,
        category: str | None,
        include_expired: bool,
        limit: int,
        offset: int,
        now: datetime,
    ) -> tuple[list[MemoryItem], int]:
        statement = (
            select(MemoryItem)
            .options(selectinload(MemoryItem.references))
            .where(MemoryItem.user_id == user_id)
        )
        count_statement = select(func.count(MemoryItem.id)).where(MemoryItem.user_id == user_id)

        statement, count_statement = self._apply_search_filters(
            statement=statement,
            count_statement=count_statement,
            memory_type=memory_type,
            category=category,
            keyword=None,
            min_importance_score=None,
        )
        statement = self._apply_lifecycle_filters(
            statement,
            include_deleted=False,
            include_expired=include_expired,
            now=now,
        )
        count_statement = self._apply_lifecycle_filters(
            count_statement,
            include_deleted=False,
            include_expired=include_expired,
            now=now,
        )

        statement = self._apply_ranking(statement).limit(limit).offset(offset)

        items_result = await self.db.execute(statement)
        total_result = await self.db.execute(count_statement)
        return list(items_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def search_for_user(
        self,
        *,
        user_id: uuid.UUID,
        keyword: str | None,
        category: str | None,
        memory_type: MemoryType | None,
        min_importance_score: float | None,
        include_expired: bool,
        limit: int,
        offset: int,
        now: datetime,
    ) -> tuple[list[MemoryItem], int]:
        statement = (
            select(MemoryItem)
            .options(selectinload(MemoryItem.references))
            .where(MemoryItem.user_id == user_id)
        )
        count_statement = select(func.count(MemoryItem.id)).where(MemoryItem.user_id == user_id)

        statement, count_statement = self._apply_search_filters(
            statement=statement,
            count_statement=count_statement,
            memory_type=memory_type,
            category=category,
            keyword=keyword,
            min_importance_score=min_importance_score,
        )
        statement = self._apply_lifecycle_filters(
            statement,
            include_deleted=False,
            include_expired=include_expired,
            now=now,
        )
        count_statement = self._apply_lifecycle_filters(
            count_statement,
            include_deleted=False,
            include_expired=include_expired,
            now=now,
        )

        statement = self._apply_ranking(statement).limit(limit).offset(offset)

        items_result = await self.db.execute(statement)
        total_result = await self.db.execute(count_statement)
        return list(items_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def add_event(
        self,
        *,
        memory_item_id: uuid.UUID,
        user_id: uuid.UUID | None,
        event_type: str,
        score_after: float | None,
        metadata: dict[str, Any] | None = None,
        outcome: str = "success",
    ) -> MemoryEvent:
        event = MemoryEvent(
            memory_item_id=memory_item_id,
            user_id=user_id,
            event_type=event_type,
            outcome=outcome,
            score_after=score_after,
            event_metadata=metadata or {},
        )
        self.db.add(event)
        return event

    async def replace_references(
        self,
        memory_item_id: uuid.UUID,
        references: list[MemoryReferenceCreate],
    ) -> None:
        await self.db.execute(
            delete(MemoryReference).where(MemoryReference.memory_item_id == memory_item_id)
        )
        for reference in references:
            self.db.add(
                MemoryReference(
                    memory_item_id=memory_item_id,
                    reference_type=reference.reference_type,
                    reference_id=reference.reference_id,
                    label=reference.label,
                    url=reference.url,
                    reference_metadata=reference.metadata,
                )
            )

    async def refresh(self, memory: MemoryItem) -> MemoryItem:
        await self.db.refresh(memory)
        refreshed = await self.get_for_user(
            memory_id=memory.id,
            user_id=memory.user_id,
            include_deleted=True,
            include_expired=True,
        )
        return refreshed or memory

    def _apply_search_filters(
        self,
        *,
        statement,
        count_statement,
        memory_type: MemoryType | None,
        category: str | None,
        keyword: str | None,
        min_importance_score: float | None,
    ):
        if memory_type is not None:
            statement = statement.where(MemoryItem.memory_type == memory_type.value)
            count_statement = count_statement.where(MemoryItem.memory_type == memory_type.value)

        if category is not None:
            normalized_category = category.strip().lower()
            statement = statement.where(func.lower(MemoryItem.category) == normalized_category)
            count_statement = count_statement.where(
                func.lower(MemoryItem.category) == normalized_category
            )

        if keyword is not None:
            keyword_pattern = f"%{keyword.strip()}%"
            keyword_filter = or_(
                MemoryItem.content.ilike(keyword_pattern),
                MemoryItem.category.ilike(keyword_pattern),
                MemoryItem.source.ilike(keyword_pattern),
            )
            statement = statement.where(keyword_filter)
            count_statement = count_statement.where(keyword_filter)

        if min_importance_score is not None:
            statement = statement.where(MemoryItem.importance_score >= min_importance_score)
            count_statement = count_statement.where(
                MemoryItem.importance_score >= min_importance_score
            )

        return statement, count_statement

    def _apply_lifecycle_filters(
        self,
        statement,
        *,
        include_deleted: bool,
        include_expired: bool,
        now: datetime | None,
    ):
        if not include_deleted:
            statement = statement.where(MemoryItem.deleted_at.is_(None))
        if not include_expired:
            if now is None:
                now = datetime.now(UTC)
            statement = statement.where(
                or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now)
            )
        return statement

    def _apply_ranking(self, statement):
        return statement.order_by(
            desc(MemoryItem.importance_score),
            desc(MemoryItem.reinforcement_count),
            desc(MemoryItem.last_accessed_at),
            desc(MemoryItem.updated_at),
        )
