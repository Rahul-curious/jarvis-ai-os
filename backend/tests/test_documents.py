from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domains.documents.models import Document, DocumentChunk

REGISTER_PAYLOAD = {
    "full_name": "Knowledge User",
    "email": "knowledge@example.com",
    "password": "correct-horse-battery",
}


DOCUMENT_TEXT = (
    "FastAPI powers the JARVIS control plane. "
    "ChromaDB stores vector embeddings for document chunks. "
    "The RAG query flow retrieves relevant context and returns citations. "
    "PostgreSQL stores document metadata and chunk records for auditability."
)


def authenticate(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201


def build_test_pdf(text: str) -> bytes:
    escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT\n/F1 12 Tf\n72 720 Td\n({escaped_text}) Tj\nET\n".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def upload_sample_document(
    client: TestClient,
    *,
    filename: str = "jarvis-notes.md",
    content: bytes | None = None,
    content_type: str = "text/markdown",
) -> dict:
    document_content = content or f"# JARVIS Knowledge\n\n{DOCUMENT_TEXT}".encode()
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, document_content, content_type)},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("jarvis-notes.txt", DOCUMENT_TEXT.encode(), "text/plain"),
        ("jarvis-notes.md", f"# JARVIS Knowledge\n\n{DOCUMENT_TEXT}".encode(), "text/markdown"),
        ("jarvis-notes.pdf", build_test_pdf(DOCUMENT_TEXT), "application/pdf"),
    ],
)
def test_upload_supported_documents_store_postgres_metadata_and_chroma_vectors(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    authenticate(client)
    body = upload_sample_document(
        client,
        filename=filename,
        content=content,
        content_type=content_type,
    )

    assert body["filename"] == filename
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
    search_after_delete_response = client.post(
        "/api/v1/rag/search",
        json={"query": "FastAPI control plane", "top_k": 3},
    )

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert detail_response.status_code == 200
    assert len(detail_response.json()["chunks"]) == document["chunk_count"]
    assert delete_response.status_code == 200
    assert missing_detail_response.status_code == 404
    assert list_after_delete_response.json()["total"] == 0
    assert search_after_delete_response.status_code == 200
    assert search_after_delete_response.json()["results"] == []
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
    search_results = search_response.json()["results"]
    assert search_results
    assert search_results[0]["citation"] == search_results[0]["citation_label"]
    assert " - Chunk " in search_results[0]["citation_label"]
    assert 0 <= search_results[0]["confidence"] <= 1
    assert query_response.status_code == 200
    query_body = query_response.json()
    assert query_body["context"]
    assert query_body["citations"]
    assert query_body["citations"][0]["citation_label"]
    assert "Grounded answer" not in query_body["answer"]
    assert "Citations:" in query_body["answer"]
    assert "RAG query flow retrieves relevant context" in query_body["answer"]
    assert scoped_search_response.status_code == 200
    assert scoped_search_response.json()["results"]
