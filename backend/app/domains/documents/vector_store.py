from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import chromadb


class VectorStoreError(Exception):
    """Raised when vector storage or retrieval fails."""


@dataclass(frozen=True)
class VectorSearchHit:
    vector_id: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    distance: float | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorRecord:
    vector_id: str
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    user_id: uuid.UUID
    chunk_index: int
    filename: str
    content: str
    embedding: list[float]


class ChromaVectorStore:
    def __init__(self, *, client, collection_name: str) -> None:
        self.client = client
        self.collection_name = collection_name
        self.collection = client.get_or_create_collection(name=collection_name)

    @classmethod
    def from_http(cls, *, host: str, port: int, collection_name: str) -> ChromaVectorStore:
        return cls(
            client=chromadb.HttpClient(host=host, port=port),
            collection_name=collection_name,
        )

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        try:
            self.collection.upsert(
                ids=[record.vector_id for record in records],
                embeddings=[record.embedding for record in records],
                documents=[record.content for record in records],
                metadatas=[
                    {
                        "user_id": str(record.user_id),
                        "document_id": str(record.document_id),
                        "chunk_id": str(record.chunk_id),
                        "chunk_index": record.chunk_index,
                        "filename": record.filename,
                    }
                    for record in records
                ],
            )
        except Exception as exc:
            raise VectorStoreError("Unable to upsert document vectors") from exc

    def search(
        self,
        *,
        user_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int,
        document_id: uuid.UUID | None = None,
    ) -> list[VectorSearchHit]:
        where: dict[str, Any]
        if document_id is None:
            where = {"user_id": str(user_id)}
        else:
            where = {
                "$and": [
                    {"user_id": str(user_id)},
                    {"document_id": str(document_id)},
                ]
            }

        try:
            result = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            raise VectorStoreError("Unable to query document vectors") from exc

        ids = result.get("ids", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        hits: list[VectorSearchHit] = []
        for index, vector_id in enumerate(ids):
            metadata = metadatas[index] or {}
            hits.append(
                VectorSearchHit(
                    vector_id=vector_id,
                    chunk_id=uuid.UUID(str(metadata["chunk_id"])),
                    document_id=uuid.UUID(str(metadata["document_id"])),
                    distance=float(distances[index]) if distances else None,
                    metadata=metadata,
                )
            )
        return hits

    def delete_document(
        self,
        *,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        vector_ids: list[str] | None = None,
    ) -> None:
        try:
            if vector_ids:
                self.collection.delete(ids=vector_ids)
                return

            self.collection.delete(
                where={
                    "$and": [{"document_id": str(document_id)}, {"user_id": str(user_id)}],
                }
            )
        except Exception as exc:
            raise VectorStoreError("Unable to delete document vectors") from exc
