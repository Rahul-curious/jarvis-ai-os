from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.domains.agents.context import KnowledgeContextProvider as KnowledgeContextProviderExtension
from app.domains.agents.errors import (
    AgentKnowledgeLimitError,
    AgentKnowledgeProviderError,
    AgentKnowledgeValidationError,
)
from app.domains.agents.schemas import ContextAssemblyRequest, ContextSection
from app.domains.documents.schemas import (
    RagCitation,
    RagQueryRequest,
    RagQueryResponse,
    RagSearchResult,
)


@dataclass(frozen=True, slots=True)
class KnowledgeUserIdentity:
    """Minimal user identity passed to the existing Knowledge/RAG service boundary."""

    id: uuid.UUID


class RagQueryPort(Protocol):
    """Read-only port implemented by the existing RagQueryService."""

    async def query(
        self,
        *,
        current_user: KnowledgeUserIdentity,
        payload: RagQueryRequest,
    ) -> RagQueryResponse:
        """Return user-scoped RAG context through the existing Knowledge Engine."""


class KnowledgeContextLimits(BaseModel):
    """Bounds applied to the transformed Knowledge/RAG context payload."""

    model_config = ConfigDict(frozen=True)

    max_results: int = Field(default=5, ge=1, le=20)
    max_context_bytes: int = Field(default=64_000, ge=1)
    max_query_length: int = Field(default=2000, ge=1, le=2000)
    max_answer_chars: int = Field(default=4000, ge=1, le=100_000)


class KnowledgeRetrievalPolicy(BaseModel):
    """Explicit retrieval policy delegated to the existing RAG service."""

    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID | None = None
    include_answer: bool = True
    use_task_as_query: bool = True
    ranking: str = Field(default="rag_engine", min_length=1, max_length=120)

    @field_validator("ranking")
    @classmethod
    def strip_ranking(cls, value: str) -> str:
        return _strip_required(value)


class KnowledgeDocumentReference(BaseModel):
    """Reference to a source document returned by Knowledge retrieval."""

    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=1024)

    @field_validator("filename")
    @classmethod
    def strip_filename(cls, value: str) -> str:
        return _strip_required(value)


class KnowledgeChunkReference(BaseModel):
    """Reference to a retrieved document chunk."""

    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int = Field(ge=0)
    citation_label: str = Field(min_length=1, max_length=2048)

    @field_validator("citation_label")
    @classmethod
    def strip_citation_label(cls, value: str) -> str:
        return _strip_required(value)


class KnowledgeCitation(BaseModel):
    """Citation metadata preserved from the existing Knowledge Engine."""

    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID
    document_filename: str = Field(min_length=1, max_length=1024)
    chunk_id: uuid.UUID
    chunk_index: int = Field(ge=0)
    citation: str = Field(min_length=1, max_length=2048)
    citation_label: str = Field(min_length=1, max_length=2048)

    @field_validator("document_filename", "citation", "citation_label")
    @classmethod
    def strip_citation_values(cls, value: str) -> str:
        return _strip_required(value)


class KnowledgeContextItem(BaseModel):
    """One retrieved chunk transformed for agent Context Assembly."""

    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID
    document_filename: str = Field(min_length=1, max_length=1024)
    chunk_id: uuid.UUID
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    distance: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    citation: str = Field(min_length=1, max_length=2048)
    citation_label: str = Field(min_length=1, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_filename", "content", "citation", "citation_label")
    @classmethod
    def strip_item_values(cls, value: str) -> str:
        return _strip_required(value)


class KnowledgeContextMetadata(BaseModel):
    """Typed metadata describing Knowledge/RAG retrieval semantics."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=2000)
    requested_limit: int = Field(ge=1)
    returned_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    user_scoped: bool = True
    document_id: uuid.UUID | None = None
    ranking: str = Field(default="rag_engine", min_length=1, max_length=120)
    citations_preserved: bool = True
    confidence_available: bool = False

    @field_validator("query", "ranking")
    @classmethod
    def strip_metadata_values(cls, value: str) -> str:
        return _strip_required(value)


class KnowledgeContext(BaseModel):
    """Typed, bounded Knowledge payload transformed for Context Assembly."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    answer: str | None = None
    items: tuple[KnowledgeContextItem, ...] = Field(default_factory=tuple)
    citations: tuple[KnowledgeCitation, ...] = Field(default_factory=tuple)
    documents: tuple[KnowledgeDocumentReference, ...] = Field(default_factory=tuple)
    chunks: tuple[KnowledgeChunkReference, ...] = Field(default_factory=tuple)
    metadata: KnowledgeContextMetadata

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("answer")
    @classmethod
    def strip_answer(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class KnowledgeContextProvider(KnowledgeContextProviderExtension):
    """Concrete read-only provider backed by the existing RagQueryService."""

    name = "knowledge"
    priority = 70

    def __init__(
        self,
        rag_service: RagQueryPort,
        *,
        limits: KnowledgeContextLimits | None = None,
        policy: KnowledgeRetrievalPolicy | None = None,
    ) -> None:
        self.rag_service = rag_service
        self.limits = limits or KnowledgeContextLimits()
        self.policy = policy or KnowledgeRetrievalPolicy()

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        query = self._resolve_query(request)
        try:
            payload = RagQueryRequest(
                query=query,
                top_k=self.limits.max_results,
                document_id=self.policy.document_id,
            )
        except ValidationError as exc:
            raise AgentKnowledgeValidationError("Invalid Knowledge retrieval request") from exc

        try:
            response = await self.rag_service.query(
                current_user=KnowledgeUserIdentity(id=request.user_id),
                payload=payload,
            )
        except AgentKnowledgeValidationError:
            raise
        except Exception as exc:
            raise AgentKnowledgeProviderError("Knowledge/RAG query failed") from exc

        self._validate_response(response, query)
        context = self._build_knowledge_context(request, query, response)
        serialized = context.model_dump(mode="json")
        if _json_size(serialized) > self.limits.max_context_bytes:
            raise AgentKnowledgeLimitError("Knowledge context exceeds the configured size limit")

        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data={
                "knowledge_answer": context.answer,
                "knowledge_chunks": [item.model_dump(mode="json") for item in context.items],
                "knowledge_citations": [
                    citation.model_dump(mode="json") for citation in context.citations
                ],
                "knowledge_documents": [
                    document.model_dump(mode="json") for document in context.documents
                ],
                "knowledge_chunk_refs": [chunk.model_dump(mode="json") for chunk in context.chunks],
                "knowledge_count": len(context.items),
                "knowledge_query": context.query,
            },
            metadata=context.metadata.model_dump(mode="json"),
        )

    def _resolve_query(self, request: ContextAssemblyRequest) -> str:
        if request.knowledge_query is not None:
            if len(request.knowledge_query) > self.limits.max_query_length:
                raise AgentKnowledgeLimitError(
                    "Knowledge query exceeds the configured length limit"
                )
            return request.knowledge_query
        if self.policy.use_task_as_query:
            if len(request.task) > self.limits.max_query_length:
                raise AgentKnowledgeLimitError(
                    "Knowledge query exceeds the configured length limit"
                )
            return request.task
        raise AgentKnowledgeValidationError("Knowledge query is required")

    def _validate_response(self, response: object, query: str) -> None:
        if not isinstance(response, RagQueryResponse):
            raise AgentKnowledgeValidationError("Knowledge Engine returned an invalid response")
        if response.question != query:
            raise AgentKnowledgeValidationError("Knowledge Engine returned an invalid question")
        if len(response.context) > self.limits.max_results:
            raise AgentKnowledgeLimitError("Knowledge Engine response exceeds the retrieval limit")
        if len(response.answer) > self.limits.max_answer_chars:
            raise AgentKnowledgeLimitError("Knowledge answer exceeds the configured length limit")

        seen_chunks: set[tuple[uuid.UUID, uuid.UUID, int]] = set()
        for result in response.context:
            self._validate_result(result)
            chunk_key = (result.document_id, result.chunk_id, result.chunk_index)
            if chunk_key in seen_chunks:
                raise AgentKnowledgeValidationError("Knowledge Engine returned duplicate chunks")
            seen_chunks.add(chunk_key)

        for citation in response.citations:
            self._validate_citation(citation)
            citation_key = (citation.document_id, citation.chunk_id, citation.chunk_index)
            if citation_key not in seen_chunks:
                raise AgentKnowledgeValidationError(
                    "Knowledge Engine returned an uncoupled citation"
                )

    def _validate_result(self, result: object) -> None:
        if not isinstance(result, RagSearchResult):
            raise AgentKnowledgeValidationError("Knowledge Engine returned an invalid result")
        if not result.content.strip():
            raise AgentKnowledgeValidationError("Knowledge Engine returned empty content")
        if result.confidence is not None and not 0 <= result.confidence <= 1:
            raise AgentKnowledgeValidationError("Knowledge Engine returned invalid confidence")

    def _validate_citation(self, citation: object) -> None:
        if not isinstance(citation, RagCitation):
            raise AgentKnowledgeValidationError("Knowledge Engine returned an invalid citation")
        if not citation.citation.strip() or not citation.citation_label.strip():
            raise AgentKnowledgeValidationError("Knowledge Engine returned an empty citation")

    def _build_knowledge_context(
        self,
        request: ContextAssemblyRequest,
        query: str,
        response: RagQueryResponse,
    ) -> KnowledgeContext:
        items = tuple(self._item_from_result(result) for result in response.context)
        citations = tuple(self._citation_from_rag(citation) for citation in response.citations)
        documents = self._document_references(response.context)
        chunks = tuple(
            KnowledgeChunkReference(
                document_id=result.document_id,
                chunk_id=result.chunk_id,
                chunk_index=result.chunk_index,
                citation_label=result.citation_label,
            )
            for result in response.context
        )
        answer = response.answer if self.policy.include_answer else None
        return KnowledgeContext(
            user_id=request.user_id,
            query=query,
            answer=answer,
            items=items,
            citations=citations,
            documents=documents,
            chunks=chunks,
            metadata=KnowledgeContextMetadata(
                query=query,
                requested_limit=self.limits.max_results,
                returned_count=len(items),
                citation_count=len(citations),
                document_id=self.policy.document_id,
                ranking=self.policy.ranking,
                confidence_available=any(item.confidence is not None for item in items),
            ),
        )

    def _item_from_result(self, result: RagSearchResult) -> KnowledgeContextItem:
        try:
            return KnowledgeContextItem(
                document_id=result.document_id,
                document_filename=result.document_filename,
                chunk_id=result.chunk_id,
                chunk_index=result.chunk_index,
                content=result.content,
                distance=result.distance,
                confidence=result.confidence,
                citation=result.citation,
                citation_label=result.citation_label,
                metadata=dict(result.metadata),
            )
        except ValidationError as exc:
            raise AgentKnowledgeValidationError(
                "Knowledge Engine returned an invalid result"
            ) from exc

    def _citation_from_rag(self, citation: RagCitation) -> KnowledgeCitation:
        try:
            return KnowledgeCitation(
                document_id=citation.document_id,
                document_filename=citation.document_filename,
                chunk_id=citation.chunk_id,
                chunk_index=citation.chunk_index,
                citation=citation.citation,
                citation_label=citation.citation_label,
            )
        except ValidationError as exc:
            raise AgentKnowledgeValidationError(
                "Knowledge Engine returned an invalid citation"
            ) from exc

    def _document_references(
        self,
        results: list[RagSearchResult],
    ) -> tuple[KnowledgeDocumentReference, ...]:
        references: list[KnowledgeDocumentReference] = []
        seen: set[uuid.UUID] = set()
        for result in results:
            if result.document_id in seen:
                continue
            seen.add(result.document_id)
            try:
                references.append(
                    KnowledgeDocumentReference(
                        document_id=result.document_id,
                        filename=result.document_filename,
                    )
                )
            except ValidationError as exc:
                raise AgentKnowledgeValidationError(
                    "Knowledge Engine returned an invalid document reference"
                ) from exc
        return tuple(references)


def _strip_required(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be blank")
    return stripped


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
        raise AgentKnowledgeValidationError("Knowledge context must be JSON serializable") from exc
    return len(serialized.encode("utf-8"))
