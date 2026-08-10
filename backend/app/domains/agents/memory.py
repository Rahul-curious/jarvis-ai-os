from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.domains.agents.context import MemoryContextProvider as MemoryContextProviderExtension
from app.domains.agents.errors import (
    AgentMemoryLimitError,
    AgentMemoryProviderError,
    AgentMemoryValidationError,
)
from app.domains.agents.schemas import ContextAssemblyRequest, ContextSection
from app.domains.memory.schemas import (
    MemoryListResponse,
    MemoryRead,
    MemoryReferenceRead,
    MemorySearchRequest,
    MemoryType,
)


@dataclass(frozen=True, slots=True)
class MemoryUserIdentity:
    """Minimal user identity passed to the existing Memory service boundary."""

    id: uuid.UUID


class MemorySearchPort(Protocol):
    """Read-only port implemented by the existing MemorySearchService."""

    async def search(
        self,
        *,
        current_user: MemoryUserIdentity,
        payload: MemorySearchRequest,
    ) -> MemoryListResponse:
        """Return user-scoped, ranked memories without mutating them."""


class MemoryContextLimits(BaseModel):
    """Bounds applied to the transformed Memory context payload."""

    model_config = ConfigDict(frozen=True)

    max_memories: int = Field(default=10, ge=1, le=100)
    max_context_bytes: int = Field(default=64_000, ge=1)
    max_query_length: int = Field(default=200, ge=1, le=200)


class MemoryRetrievalPolicy(BaseModel):
    """Explicit read policy passed to the existing Memory search service."""

    model_config = ConfigDict(frozen=True)

    category: str | None = Field(default=None, min_length=1, max_length=120)
    memory_type: MemoryType | None = None
    min_importance_score: float | None = Field(default=None, ge=0, le=1)
    include_expired: bool = False
    use_task_as_keyword: bool = False

    @field_validator("category")
    @classmethod
    def strip_category(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class MemoryContextMetadata(BaseModel):
    """Typed metadata describing Memory Engine retrieval semantics."""

    model_config = ConfigDict(frozen=True)

    query: str | None = None
    requested_limit: int = Field(ge=1)
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    user_scoped: bool = True
    include_expired: bool = False
    ranking: str = "memory_engine"
    references_preserved: bool = True


MemoryContextItem = MemoryRead
MemoryContextReference = MemoryReferenceRead


class MemoryContext(BaseModel):
    """Typed, bounded Memory payload transformed for Context Assembly."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    query: str | None = None
    items: tuple[MemoryContextItem, ...] = Field(default_factory=tuple)
    total_count: int = Field(ge=0)
    metadata: MemoryContextMetadata


class MemoryContextProvider(MemoryContextProviderExtension):
    """Concrete read-only provider backed by the existing MemorySearchService."""

    name = "memory"
    priority = 75

    def __init__(
        self,
        memory_service: MemorySearchPort,
        *,
        limits: MemoryContextLimits | None = None,
        policy: MemoryRetrievalPolicy | None = None,
    ) -> None:
        self.memory_service = memory_service
        self.limits = limits or MemoryContextLimits()
        self.policy = policy or MemoryRetrievalPolicy()

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        keyword = self._resolve_keyword(request)
        try:
            payload = MemorySearchRequest(
                keyword=keyword,
                category=self.policy.category,
                memory_type=self.policy.memory_type,
                min_importance_score=self.policy.min_importance_score,
                include_expired=self.policy.include_expired,
                limit=self.limits.max_memories,
                offset=0,
            )
        except ValidationError as exc:
            raise AgentMemoryValidationError("Invalid Memory retrieval request") from exc

        try:
            response = await self.memory_service.search(
                current_user=MemoryUserIdentity(id=request.user_id),
                payload=payload,
            )
        except AgentMemoryValidationError:
            raise
        except Exception as exc:
            raise AgentMemoryProviderError("Memory Engine search failed") from exc

        self._validate_response(response, request)
        context = MemoryContext(
            user_id=request.user_id,
            query=keyword,
            items=tuple(response.items),
            total_count=response.total,
            metadata=MemoryContextMetadata(
                query=keyword,
                requested_limit=self.limits.max_memories,
                returned_count=len(response.items),
                total_count=response.total,
                include_expired=self.policy.include_expired,
            ),
        )
        serialized = context.model_dump(mode="json")
        if _json_size(serialized) > self.limits.max_context_bytes:
            raise AgentMemoryLimitError("Memory context exceeds the configured size limit")

        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data={
                "memories": [item.model_dump(mode="json") for item in context.items],
                "memory_count": len(context.items),
                "total_count": context.total_count,
                "query": context.query,
            },
            metadata=context.metadata.model_dump(mode="json"),
        )

    def _resolve_keyword(self, request: ContextAssemblyRequest) -> str | None:
        if request.memory_query is not None:
            if len(request.memory_query) > self.limits.max_query_length:
                raise AgentMemoryLimitError("Memory query exceeds the configured length limit")
            return request.memory_query
        if self.policy.use_task_as_keyword and len(request.task) <= self.limits.max_query_length:
            return request.task
        return None

    def _validate_response(
        self,
        response: object,
        request: ContextAssemblyRequest,
    ) -> None:
        if not isinstance(response, MemoryListResponse):
            raise AgentMemoryValidationError("Memory Engine returned an invalid response")
        if (
            response.limit > self.limits.max_memories
            or len(response.items) > self.limits.max_memories
        ):
            raise AgentMemoryLimitError("Memory Engine response exceeds the retrieval limit")
        if response.offset != 0:
            raise AgentMemoryValidationError("Memory context must use the first result page")
        if response.total < len(response.items):
            raise AgentMemoryValidationError("Memory Engine returned an invalid total count")
        if any(item.user_id != request.user_id for item in response.items):
            raise AgentMemoryValidationError("Memory Engine returned an out-of-scope memory")


def _json_size(value: Any) -> int:
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise AgentMemoryValidationError("Memory context must be JSON serializable") from exc
    return len(serialized.encode("utf-8"))
