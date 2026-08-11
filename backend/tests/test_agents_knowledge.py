from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import ValidationError

from app.domains.agents import KnowledgeContextProvider as ExportedKnowledgeContextProvider
from app.domains.agents.context import (
    AgentConfigurationProvider,
    AgentContextAssembler,
    ContextBuilder,
    ConversationHistoryProvider,
    RuntimeMetadataProvider,
    UserInformationProvider,
)
from app.domains.agents.errors import (
    AgentKnowledgeLimitError,
    AgentKnowledgeProviderError,
    AgentKnowledgeValidationError,
    AgentValidationError,
)
from app.domains.agents.knowledge import (
    KnowledgeContextLimits,
    KnowledgeContextProvider,
    KnowledgeRetrievalPolicy,
)
from app.domains.agents.schemas import (
    AgentConfiguration,
    ContextAssemblyRequest,
    UserInformation,
)
from app.domains.documents.schemas import (
    RagCitation,
    RagQueryRequest,
    RagQueryResponse,
    RagSearchResult,
)


class FakeRagQueryService:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[uuid.UUID, RagQueryRequest]] = []

    async def query(self, *, current_user, payload: RagQueryRequest) -> object:
        self.calls.append((current_user.id, payload))
        return self.response


def make_request(
    *,
    user_id: uuid.UUID | None = None,
    knowledge_query: str | None = "deployment",
) -> ContextAssemblyRequest:
    user_id = user_id or uuid.uuid4()
    return (
        ContextBuilder()
        .with_run_id(uuid.uuid4())
        .with_user_id(user_id)
        .with_task("Summarize the deployment plan")
        .with_knowledge_query(knowledge_query)
        .with_runtime_metadata({"source": "knowledge-integration-test"})
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
                configuration={"mode": "knowledge-aware"},
            )
        )
        .build()
    )


def make_result(
    *,
    document_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    chunk_index: int = 0,
    content: str = "Deploy JARVIS with Docker Compose after indexing uploaded docs.",
    confidence: float | None = 0.8,
) -> RagSearchResult:
    document_id = document_id or uuid.uuid4()
    chunk_id = chunk_id or uuid.uuid4()
    citation = f"deployment-guide.md - Chunk {chunk_index + 1}"
    return RagSearchResult(
        document_id=document_id,
        document_filename="deployment-guide.md",
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        content=content,
        distance=0.25,
        confidence=confidence,
        citation=citation,
        citation_label=citation,
        metadata={"source": "upload", "rank": chunk_index + 1},
    )


def make_citation(result: RagSearchResult) -> RagCitation:
    return RagCitation(
        document_id=result.document_id,
        document_filename=result.document_filename,
        chunk_id=result.chunk_id,
        chunk_index=result.chunk_index,
        citation=result.citation,
        citation_label=result.citation_label,
    )


def make_response(
    results: list[RagSearchResult],
    *,
    query: str = "deployment",
    answer: str = "Use Docker Compose and cite the uploaded deployment guide.",
) -> RagQueryResponse:
    return RagQueryResponse(
        question=query,
        answer=answer,
        context=results,
        citations=[make_citation(result) for result in results],
    )


def test_knowledge_provider_uses_user_scope_and_preserves_citations_and_confidence() -> None:
    request = make_request()
    result = make_result()
    service = FakeRagQueryService(make_response([result]))
    provider = KnowledgeContextProvider(service)

    section = asyncio.run(provider.build_context(request))

    assert isinstance(provider, ExportedKnowledgeContextProvider)
    assert service.calls[0][0] == request.user_id
    assert service.calls[0][1].query == "deployment"
    assert service.calls[0][1].top_k == 5
    assert service.calls[0][1].document_id is None
    assert section.provider == "knowledge"
    assert section.data["knowledge_chunks"][0]["chunk_id"] == str(result.chunk_id)
    assert section.data["knowledge_chunks"][0]["confidence"] == 0.8
    assert section.data["knowledge_chunks"][0]["metadata"] == {"rank": 1, "source": "upload"}
    assert section.data["knowledge_citations"][0]["citation"] == result.citation
    assert section.data["knowledge_documents"][0]["document_id"] == str(result.document_id)
    assert section.metadata["ranking"] == "rag_engine"
    assert section.metadata["user_scoped"] is True
    assert section.metadata["citations_preserved"] is True
    assert section.metadata["confidence_available"] is True


def test_knowledge_context_transformation_is_deterministic() -> None:
    request = make_request()
    result = make_result()

    first = asyncio.run(
        KnowledgeContextProvider(FakeRagQueryService(make_response([result]))).build_context(
            request
        )
    )
    second = asyncio.run(
        KnowledgeContextProvider(FakeRagQueryService(make_response([result]))).build_context(
            request
        )
    )

    assert first == second


def test_knowledge_provider_enforces_retrieval_limit_and_context_size() -> None:
    request = make_request()
    results = [make_result(chunk_index=0), make_result(chunk_index=1)]

    limited_service = FakeRagQueryService(make_response(results))
    with pytest.raises(AgentKnowledgeLimitError, match="retrieval limit"):
        asyncio.run(
            KnowledgeContextProvider(
                limited_service,
                limits=KnowledgeContextLimits(max_results=1),
            ).build_context(request)
        )

    large_service = FakeRagQueryService(make_response([make_result()]))
    with pytest.raises(AgentKnowledgeLimitError, match="configured size limit"):
        asyncio.run(
            KnowledgeContextProvider(
                large_service,
                limits=KnowledgeContextLimits(max_context_bytes=100),
            ).build_context(request)
        )


def test_knowledge_provider_rejects_malformed_service_output() -> None:
    request = make_request()
    with pytest.raises(AgentKnowledgeValidationError, match="invalid response"):
        asyncio.run(KnowledgeContextProvider(FakeRagQueryService(object())).build_context(request))

    result = make_result()
    mismatched_citation = make_citation(make_result())
    response = RagQueryResponse(
        question="deployment",
        answer="Use the cited context.",
        context=[result],
        citations=[mismatched_citation],
    )
    with pytest.raises(AgentKnowledgeValidationError, match="uncoupled citation"):
        asyncio.run(KnowledgeContextProvider(FakeRagQueryService(response)).build_context(request))


def test_knowledge_provider_wraps_rag_service_failures_without_reimplementing_rag() -> None:
    class FailingRagService:
        async def query(self, *, current_user, payload: RagQueryRequest) -> object:
            del current_user, payload
            raise RuntimeError("vector store unavailable")

    with pytest.raises(AgentKnowledgeProviderError, match="query failed"):
        asyncio.run(KnowledgeContextProvider(FailingRagService()).build_context(make_request()))


def test_knowledge_provider_can_use_task_as_query_and_document_policy() -> None:
    request = make_request(knowledge_query=None)
    document_id = uuid.uuid4()
    service = FakeRagQueryService(make_response([], query=request.task))
    provider = KnowledgeContextProvider(
        service,
        policy=KnowledgeRetrievalPolicy(document_id=document_id),
    )

    section = asyncio.run(provider.build_context(request))

    assert service.calls[0][1].query == request.task
    assert service.calls[0][1].document_id == document_id
    assert section.data["knowledge_query"] == request.task
    assert section.metadata["document_id"] == str(document_id)


def test_knowledge_provider_requires_query_when_task_fallback_is_disabled() -> None:
    request = make_request(knowledge_query=None)
    provider = KnowledgeContextProvider(
        FakeRagQueryService(make_response([])),
        policy=KnowledgeRetrievalPolicy(use_task_as_query=False),
    )

    with pytest.raises(AgentKnowledgeValidationError, match="query is required"):
        asyncio.run(provider.build_context(request))


def test_knowledge_provider_integrates_with_context_assembler() -> None:
    request = make_request()
    result = make_result()
    provider = KnowledgeContextProvider(FakeRagQueryService(make_response([result])))
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
            "knowledge",
        },
    )

    context = asyncio.run(assembler.build_context(request))

    assert "knowledge" in context.metadata.provider_names
    assert context.data["knowledge_chunks"][0]["content"] == result.content
    assert context.data["knowledge_citations"][0]["citation_label"] == result.citation_label


def test_knowledge_limits_and_query_validation_are_typed() -> None:
    with pytest.raises(ValidationError):
        KnowledgeContextLimits(max_results=21)

    with pytest.raises(AgentValidationError):
        make_request(knowledge_query="x" * 2001)

    request = make_request(knowledge_query="x" * 10)
    with pytest.raises(AgentKnowledgeLimitError, match="query"):
        asyncio.run(
            KnowledgeContextProvider(
                FakeRagQueryService(make_response([])),
                limits=KnowledgeContextLimits(max_query_length=5),
            ).build_context(request)
        )
