# Phase 5 RAG Knowledge Engine

## Summary

Phase 5 adds the first retrieval-augmented generation foundation for JARVIS. Users can upload supported documents, the backend parses and chunks them, embeddings are generated through a provider abstraction, vectors are stored in ChromaDB, and PostgreSQL keeps durable metadata for documents and chunks.

This phase returns grounded context and citations from uploaded knowledge. It does not implement autonomous agents, browser ingestion, voice, or advanced LLM synthesis.

## Architecture

```mermaid
flowchart LR
    Upload["Document Upload"] --> Parse["Parse txt, md, pdf"]
    Parse --> Chunk["Chunk Text"]
    Chunk --> Embed["Embedding Provider"]
    Embed --> Chroma["ChromaDB Vectors"]
    Chunk --> Postgres["PostgreSQL Metadata"]
    Query["User Query"] --> QueryEmbed["Embed Query"]
    QueryEmbed --> Chroma
    Chroma --> Hydrate["Hydrate Chunks From PostgreSQL"]
    Hydrate --> Response["Context And Citations"]
```

## Scope

Implemented:

- `documents` and `document_chunks` relational tables.
- Alembic migration for document metadata.
- Parser support for `.txt`, `.md`, `.markdown`, and `.pdf`.
- Deterministic overlapping chunking.
- Embedding provider abstraction.
- Default embedding provider: `sentence-transformers/all-MiniLM-L6-v2`.
- ChromaDB vector storage and top-k retrieval.
- Chroma Python client and server pinned together at `1.5.9`.
- Authenticated document APIs.
- Authenticated RAG search/query APIs.
- Knowledge Base and Upload Document frontend pages.

Deferred:

- LLM-generated answer synthesis.
- Async ingestion workers.
- Workspace-scoped knowledge collections.
- Enterprise connector ingestion.
- Hybrid keyword/vector retrieval.
- Knowledge graph extraction.

## Schema

```mermaid
erDiagram
    USER ||--o{ DOCUMENT : owns
    DOCUMENT ||--o{ DOCUMENT_CHUNK : splits

    DOCUMENT {
      uuid id
      uuid user_id
      string filename
      string content_type
      int file_size_bytes
      string checksum_sha256
      string status
      int chunk_count
      int text_length
      string embedding_model
      string vector_collection
      json metadata
      datetime created_at
      datetime updated_at
      datetime deleted_at
    }

    DOCUMENT_CHUNK {
      uuid id
      uuid document_id
      uuid user_id
      int chunk_index
      text content
      int char_count
      string content_hash
      string vector_id
      json metadata
      datetime created_at
    }
```

## API

- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `DELETE /api/v1/documents/{id}`
- `POST /api/v1/rag/search`
- `POST /api/v1/rag/query`

All endpoints require the Phase 3 HttpOnly cookie authentication flow.

## RAG Query Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Embed as Embedding Provider
    participant Chroma as ChromaDB
    participant DB as PostgreSQL

    Client->>API: POST /rag/query
    API->>Embed: Embed query
    API->>Chroma: Retrieve top-k vectors
    Chroma-->>API: Chunk vector hits
    API->>DB: Hydrate chunk metadata and text
    DB-->>API: Chunks and document metadata
    API-->>Client: Grounded answer, context, citations
```

## Risks

| Risk | Mitigation |
| --- | --- |
| Unsupported or malformed documents | Explicit parser validation and errors |
| Vector store drift from relational records | Chunk IDs and document IDs are stored in both systems |
| Chroma client/server protocol mismatch | Pin both components to `1.5.9` and upgrade them together |
| Unauthorized retrieval | User-scoped metadata filters and authenticated APIs |
| Large upload cost | Configurable upload size and chunk settings |
| Poor answer synthesis | Current phase returns grounded context and citations, not unsupported claims |

## Migration

Run:

```bash
cd backend
alembic upgrade head
```

Docker Compose runs migrations automatically before Uvicorn starts.
