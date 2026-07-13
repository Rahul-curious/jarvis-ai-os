from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    char_count: int
    content_hash: str
    vector_id: str
    metadata: dict[str, Any] = Field(
        validation_alias="chunk_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    content_type: str
    file_size_bytes: int
    checksum_sha256: str
    status: str
    chunk_count: int
    text_length: int
    embedding_model: str
    vector_collection: str
    metadata: dict[str, Any] = Field(
        validation_alias="document_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime
    updated_at: datetime
    chunks: list[DocumentChunkRead] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    items: list[DocumentRead]
    total: int
    limit: int
    offset: int


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: uuid.UUID | None = None


class RagSearchResult(BaseModel):
    document_id: uuid.UUID
    document_filename: str
    chunk_id: uuid.UUID
    chunk_index: int
    content: str
    distance: float | None
    confidence: float | None
    citation: str
    citation_label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagSearchResponse(BaseModel):
    query: str
    results: list[RagSearchResult]


class RagCitation(BaseModel):
    document_id: uuid.UUID
    document_filename: str
    chunk_id: uuid.UUID
    chunk_index: int
    citation: str
    citation_label: str


class RagQueryRequest(RagSearchRequest):
    pass


class RagQueryResponse(BaseModel):
    question: str
    answer: str
    context: list[RagSearchResult]
    citations: list[RagCitation]
