# Documents Domain

Phase 5 implements the JARVIS RAG Knowledge Engine foundation.

## Responsibilities

- Accept authenticated document uploads.
- Parse `.txt`, `.md`, `.markdown`, and `.pdf` files.
- Chunk extracted text deterministically.
- Generate embeddings through the embedding provider abstraction.
- Store document and chunk metadata in PostgreSQL.
- Store chunk vectors in ChromaDB.
- Retrieve top-k chunks for grounded search and query responses.

## Current Boundaries

Implemented:

- SQLAlchemy `documents` and `document_chunks` models.
- Alembic migration.
- Parser, chunker, embedding provider abstraction, Chroma vector store wrapper.
- Document upload/list/detail/delete APIs.
- RAG search/query APIs with citations.

Deferred:

- LLM answer synthesis.
- Workspace collections and RBAC.
- Web page ingestion.
- Async ingestion jobs.
- Hybrid keyword/vector ranking.
- Knowledge graph extraction.
