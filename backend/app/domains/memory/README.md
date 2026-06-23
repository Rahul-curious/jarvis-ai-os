# Memory Domain

Phase 4 implements the relational Memory Engine foundation for JARVIS.

## Responsibilities

- Store authenticated user memories in `memory_items`.
- Track lifecycle actions in `memory_events`.
- Link memories to future conversations, projects, tasks, documents, or external sources through `memory_references`.
- Support short-term expiration, long-term recall, user preferences, project memory, and correction memory.
- Keep search keyword/category/type based for this phase.
- Reinforce memories when they are recalled or explicitly reinforced.

## Current Boundaries

Implemented:

- SQLAlchemy models.
- Repository pattern.
- Service layer classes.
- Authenticated FastAPI routes.
- Alembic migration.

Deferred:

- Embeddings.
- Vector search.
- RAG ingestion.
- Agent-driven memory extraction.
- Knowledge graph relationships.
