# JARVIS Backend

FastAPI foundation for the JARVIS cloud control plane.

Phase 5 responsibilities:

- Provide versioned API routing under `/api/v1`.
- Connect to PostgreSQL through SQLAlchemy async sessions.
- Manage Alembic migrations for auth, memory, and document persistence.
- Support open registration, login, refresh, logout, and user profile endpoints.
- Store JWT access and refresh tokens in HttpOnly cookies.
- Persist users, sessions, and audit logs.
- Persist explicit user memories, memory events, and memory references.
- Support memory create, list, recall, update, delete, search, and reinforcement APIs.
- Persist document metadata and chunk records in PostgreSQL.
- Store document chunk vectors in ChromaDB.
- Support document upload/list/detail/delete and RAG search/query APIs.

The Python Chroma client and Chroma server are intentionally pinned to `1.5.9`.
Upgrade them together because Chroma does not guarantee wire compatibility across
independently selected client and server releases.

Business logic for autonomous agents, browser automation, and voice is intentionally deferred.

## Environment

Required production-sensitive settings:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `BACKEND_CORS_ORIGINS`
- `AUTH_COOKIE_SECURE`
- `SHORT_TERM_MEMORY_DEFAULT_TTL_HOURS`
- `CHROMA_HOST`
- `CHROMA_PORT`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL_NAME`

Local defaults are documented in the repository `.env.example`.

## Migrations

Run migrations manually:

```bash
alembic upgrade head
```

The backend Docker container runs this command automatically before starting Uvicorn.

## API

- `GET /api/v1/health`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/users/me`
- `POST /api/v1/memory`
- `GET /api/v1/memory`
- `GET /api/v1/memory/{id}`
- `PUT /api/v1/memory/{id}`
- `DELETE /api/v1/memory/{id}`
- `POST /api/v1/memory/search`
- `POST /api/v1/memory/reinforce`
- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `DELETE /api/v1/documents/{id}`
- `POST /api/v1/rag/search`
- `POST /api/v1/rag/query`

Memory is relational. Document RAG uses ChromaDB vectors and PostgreSQL chunk metadata.

## Tests

```bash
pytest
```
