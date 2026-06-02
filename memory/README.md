# JARVIS Memory

Phase 1 establishes the storage boundaries for future long-term memory and knowledge retrieval.

Configured foundation:

- PostgreSQL remains the source of truth for memory metadata, provenance, retention, and audit links.
- ChromaDB provides the local vector-store service for future embeddings.
- Collection naming is tenant and workspace aware, matching the data isolation requirements in `docs/database-design.md`.

No memory creation, retrieval, ranking, or deletion business logic is implemented in Phase 1.
