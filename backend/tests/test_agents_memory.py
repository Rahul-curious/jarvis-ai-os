from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domains.agents.context import (
    AgentConfigurationProvider,
    AgentContextAssembler,
    ContextBuilder,
    ConversationHistoryProvider,
    RuntimeMetadataProvider,
    UserInformationProvider,
)
from app.domains.agents.errors import (
    AgentMemoryLimitError,
    AgentMemoryProviderError,
    AgentMemoryValidationError,
    AgentValidationError,
)
from app.domains.agents.memory import (
    MemoryContextLimits,
    MemoryContextProvider,
    MemoryRetrievalPolicy,
)
from app.domains.agents.schemas import (
    AgentConfiguration,
    ContextAssemblyRequest,
    UserInformation,
)
from app.domains.memory.schemas import (
    MemoryListResponse,
    MemoryRead,
    MemoryReferenceRead,
    MemorySearchRequest,
    MemoryType,
)


class FakeMemorySearchService:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[uuid.UUID, MemorySearchRequest]] = []

    async def search(self, *, current_user, payload: MemorySearchRequest) -> object:
        self.calls.append((current_user.id, payload))
        return self.response


def make_request(
    *,
    user_id: uuid.UUID | None = None,
    memory_query: str | None = "deployment",
) -> ContextAssemblyRequest:
    user_id = user_id or uuid.uuid4()
    return (
        ContextBuilder()
        .with_run_id(uuid.uuid4())
        .with_user_id(user_id)
        .with_task("Summarize the deployment plan")
        .with_memory_query(memory_query)
        .with_runtime_metadata({"source": "memory-integration-test"})
        .with_user_information(
            UserInformation(
                user_id=user_id,
                email="rahul@example.com",
                full_name="Rahul Prakash",
            )
        )
        .with_agent_configuration(
            AgentConfiguration(
                agent_key="assistant",
                agent_type="assistant",
                version="1.0",
                configuration={"mode": "memory-aware"},
            )
        )
        .build()
    )


def make_memory(user_id: uuid.UUID, *, content: str = "Deployment preference") -> MemoryRead:
    return MemoryRead(
        id=uuid.uuid4(),
        user_id=user_id,
        memory_type=MemoryType.user_preference,
        category="workflow",
        content=content,
        importance_score=0.8,
        reinforcement_count=2,
        memory_score=0.62,
        source="manual",
        expires_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        last_accessed_at=None,
        references=[
            MemoryReferenceRead(
                id=uuid.uuid4(),
                reference_type="project",
                reference_id="jarvis-ai-os",
                label="JARVIS",
                url="https://example.com/jarvis",
                metadata={"phase": "4"},
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
    )


def make_response(items: list[MemoryRead], *, limit: int | None = None) -> MemoryListResponse:
    return MemoryListResponse(
        items=items,
        total=len(items),
        limit=limit or len(items) or 1,
        offset=0,
    )


def test_memory_provider_uses_user_scope_and_preserves_score_and_references() -> None:
    request = make_request()
    memory = make_memory(request.user_id)
    service = FakeMemorySearchService(make_response([memory]))
    provider = MemoryContextProvider(service)

    section = asyncio.run(provider.build_context(request))

    assert service.calls[0][0] == request.user_id
    assert service.calls[0][1].keyword == "deployment"
    assert service.calls[0][1].include_expired is False
    assert section.provider == "memory"
    assert section.data["memories"][0]["id"] == str(memory.id)
    assert section.data["memories"][0]["memory_score"] == 0.62
    assert section.data["memories"][0]["references"][0]["metadata"] == {"phase": "4"}
    assert section.metadata["ranking"] == "memory_engine"
    assert section.metadata["references_preserved"] is True


def test_memory_context_transformation_is_deterministic() -> None:
    request = make_request()
    memory = make_memory(request.user_id)

    first = asyncio.run(
        MemoryContextProvider(FakeMemorySearchService(make_response([memory]))).build_context(
            request
        )
    )
    second = asyncio.run(
        MemoryContextProvider(FakeMemorySearchService(make_response([memory]))).build_context(
            request
        )
    )

    assert first == second


def test_memory_provider_enforces_retrieval_limit_and_context_size() -> None:
    request = make_request()
    memories = [make_memory(request.user_id), make_memory(request.user_id)]

    limited_service = FakeMemorySearchService(make_response(memories, limit=2))
    with pytest.raises(AgentMemoryLimitError, match="retrieval limit"):
        asyncio.run(
            MemoryContextProvider(
                limited_service,
                limits=MemoryContextLimits(max_memories=1),
            ).build_context(request)
        )

    large_service = FakeMemorySearchService(make_response([make_memory(request.user_id)]))
    with pytest.raises(AgentMemoryLimitError, match="configured size limit"):
        asyncio.run(
            MemoryContextProvider(
                large_service,
                limits=MemoryContextLimits(max_context_bytes=100),
            ).build_context(request)
        )


def test_memory_provider_rejects_out_of_scope_and_malformed_service_output() -> None:
    request = make_request()
    out_of_scope = make_memory(uuid.uuid4())
    with pytest.raises(AgentMemoryValidationError, match="out-of-scope"):
        asyncio.run(
            MemoryContextProvider(
                FakeMemorySearchService(make_response([out_of_scope]))
            ).build_context(request)
        )

    with pytest.raises(AgentMemoryValidationError, match="invalid response"):
        asyncio.run(MemoryContextProvider(FakeMemorySearchService(object())).build_context(request))


def test_memory_provider_wraps_memory_service_failures_without_mutating_memory() -> None:
    class FailingMemoryService:
        async def search(self, *, current_user, payload: MemorySearchRequest) -> object:
            del current_user, payload
            raise RuntimeError("database unavailable")

    with pytest.raises(AgentMemoryProviderError, match="search failed"):
        asyncio.run(MemoryContextProvider(FailingMemoryService()).build_context(make_request()))


def test_memory_provider_can_derive_a_bounded_task_keyword() -> None:
    request = make_request(memory_query=None)
    service = FakeMemorySearchService(make_response([]))
    provider = MemoryContextProvider(
        service,
        policy=MemoryRetrievalPolicy(use_task_as_keyword=True),
    )

    asyncio.run(provider.build_context(request))

    assert service.calls[0][1].keyword == request.task


def test_memory_provider_integrates_with_context_assembler() -> None:
    request = make_request()
    memory = make_memory(request.user_id)
    provider = MemoryContextProvider(FakeMemorySearchService(make_response([memory])))
    assembler = AgentContextAssembler(
        providers=[
            ConversationHistoryProvider(),
            RuntimeMetadataProvider(),
            UserInformationProvider(),
            AgentConfigurationProvider(),
            provider,
        ],
        required_provider_names={
            "conversation_history",
            "runtime_metadata",
            "user_information",
            "agent_configuration",
            "memory",
        },
    )

    context = asyncio.run(assembler.build_context(request))

    assert "memory" in context.metadata.provider_names
    assert context.data["memories"][0]["content"] == memory.content
    assert context.data["memories"][0]["references"][0]["reference_type"] == "project"


def test_memory_limits_and_query_validation_are_typed() -> None:
    with pytest.raises(ValidationError):
        MemoryContextLimits(max_memories=101)

    with pytest.raises(AgentValidationError):
        make_request(memory_query="x" * 201)

    request = make_request(memory_query="x" * 10)
    with pytest.raises(AgentMemoryLimitError, match="query"):
        asyncio.run(
            MemoryContextProvider(
                FakeMemorySearchService(make_response([])),
                limits=MemoryContextLimits(max_query_length=5),
            ).build_context(request)
        )
