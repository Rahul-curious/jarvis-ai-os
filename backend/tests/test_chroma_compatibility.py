from __future__ import annotations

import uuid
from importlib.metadata import version

import chromadb

from app.domains.documents.vector_store import ChromaVectorStore, VectorRecord


def test_chromadb_dependency_matches_compose_server_version() -> None:
    assert version("chromadb") == "0.5.23"


def test_chroma_collection_contract_supports_document_vector_lifecycle() -> None:
    store = ChromaVectorStore(
        client=chromadb.EphemeralClient(),
        collection_name=f"test_chroma_compatibility_{uuid.uuid4().hex}",
    )
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    record = VectorRecord(
        vector_id=f"document:{document_id}:chunk:0",
        document_id=document_id,
        chunk_id=chunk_id,
        user_id=user_id,
        chunk_index=0,
        filename="jarvis-chroma-compatibility.md",
        content="ChromaDB stores vectors for uploaded JARVIS knowledge documents.",
        embedding=[1.0, 0.0, 0.0],
    )

    store.upsert([record])
    hits = store.search(
        user_id=user_id,
        query_embedding=[1.0, 0.0, 0.0],
        top_k=1,
    )

    assert len(hits) == 1
    assert hits[0].vector_id == record.vector_id
    assert hits[0].document_id == document_id
    assert hits[0].chunk_id == chunk_id
    assert hits[0].metadata["filename"] == "jarvis-chroma-compatibility.md"

    store.delete_document(
        document_id=document_id,
        user_id=user_id,
        vector_ids=[record.vector_id],
    )

    assert store.collection.count() == 0
