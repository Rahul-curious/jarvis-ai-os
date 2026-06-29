from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domains.documents.models import Document, DocumentChunk

REGISTER_PAYLOAD = {
    "full_name": "Knowledge User",
    "email": "knowledge@example.com",
    "password": "correct-horse-battery",
}


def authenticate(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201


def upload_sample_document(client: TestClient, *, filename: str = "jarvis-notes.md") -> dict:
    content = (
        "# JARVIS Knowledge\n\n"
        "FastAPI powers the JARVIS control plane. "
        "ChromaDB stores vector embeddings for document chunks. "
        "The RAG query flow retrieves relevant context and returns citations.\n\n"
        "PostgreSQL stores document metadata and chunk records for auditability."
    )
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 201
    return response.json()


def test_upload_document_stores_postgres_metadata_and_chroma_vectors(
    client: TestClient,
) -> None:
    authenticate(client)
    body = upload_sample_document(client)

    assert body["filename"] == "jarvis-notes.md"
    assert body["status"] == "indexed"
    assert body["chunk_count"] >= 1
    assert body["embedding_model"] == "hash/deterministic"
    assert body["chunks"][0]["content"]

    async def inspect_db() -> tuple[int, int]:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            documents = await session.scalar(select(func.count(Document.id)))
            chunks = await session.scalar(select(func.count(DocumentChunk.id)))
            return int(documents or 0), int(chunks or 0)

    document_count, chunk_count = asyncio.run(inspect_db())
    assert document_count == 1
    assert chunk_count == body["chunk_count"]
    assert client.app.state.test_vector_store.collection.count() == body["chunk_count"]


def test_document_list_detail_and_delete_flow(client: TestClient) -> None:
    authenticate(client)
    document = upload_sample_document(client)

    list_response = client.get("/api/v1/documents")
    detail_response = client.get(f"/api/v1/documents/{document['id']}")
    delete_response = client.delete(f"/api/v1/documents/{document['id']}")
    missing_detail_response = client.get(f"/api/v1/documents/{document['id']}")
    list_after_delete_response = client.get("/api/v1/documents")

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert detail_response.status_code == 200
    assert len(detail_response.json()["chunks"]) == document["chunk_count"]
    assert delete_response.status_code == 200
    assert missing_detail_response.status_code == 404
    assert list_after_delete_response.json()["total"] == 0
    assert client.app.state.test_vector_store.collection.count() == 0


def test_upload_rejects_unsupported_document_type(client: TestClient) -> None:
    authenticate(client)

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("notes.docx", b"unsupported", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_rag_search_and_query_return_context_and_citations(client: TestClient) -> None:
    authenticate(client)
    document = upload_sample_document(client)

    search_response = client.post(
        "/api/v1/rag/search",
        json={"query": "Where are vector embeddings stored?", "top_k": 3},
    )
    query_response = client.post(
        "/api/v1/rag/query",
        json={"query": "How does the RAG query flow work?", "top_k": 3},
    )
    scoped_search_response = client.post(
        "/api/v1/rag/search",
        json={
            "query": "PostgreSQL metadata",
            "top_k": 3,
            "document_id": document["id"],
        },
    )

    assert search_response.status_code == 200
    assert search_response.json()["results"]
    assert "citation" in search_response.json()["results"][0]
    assert query_response.status_code == 200
    assert query_response.json()["context"]
    assert query_response.json()["citations"]
    assert "Grounded answer" in query_response.json()["answer"]
    assert scoped_search_response.status_code == 200
    assert scoped_search_response.json()["results"]
