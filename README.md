# JARVIS AI OS

JARVIS is an AI Operating System inspired by Tony Stark's JARVIS.

This repository currently contains the Phase 4 Memory Engine foundation:

- FastAPI backend control-plane scaffold.
- JWT authentication with HttpOnly cookie sessions.
- PostgreSQL-backed `users`, `sessions`, and `audit_logs` tables.
- PostgreSQL-backed `memory_items`, `memory_events`, and `memory_references` tables.
- React + Vite + TypeScript frontend scaffold.
- Login, register, dashboard, and memory dashboard pages.
- PostgreSQL service for relational persistence.
- Alembic migrations that run on backend container startup.
- Optional ChromaDB service for future memory and RAG vectors.
- LangGraph package scaffold for future agent orchestration.
- Docker Compose local development stack.

Business logic for assistant chat, RAG, agents, automation, voice, and advanced governance is intentionally not implemented yet.

## Local Setup

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Start the local stack:

   ```bash
   docker compose up --build
   ```

3. Open the services:

   - Frontend: `http://localhost:5173`
   - Backend health: `http://localhost:8000/api/v1/health`
   - Backend OpenAPI docs: `http://localhost:8000/docs`

The default Compose stack starts `postgres`, `backend`, and `frontend`. ChromaDB is available behind the optional `memory` profile for future phases:

```bash
docker compose --profile memory up --build
```

## Auth Endpoints

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/users/me`

Access and refresh JWTs are stored in HttpOnly cookies. The frontend never stores tokens in JavaScript.

## Memory Endpoints

- `POST /api/v1/memory`
- `GET /api/v1/memory`
- `GET /api/v1/memory/{id}`
- `PUT /api/v1/memory/{id}`
- `DELETE /api/v1/memory/{id}`
- `POST /api/v1/memory/search`
- `POST /api/v1/memory/reinforce`

Phase 4 memory search is keyword, category, and type based. Embeddings, vector search, RAG, and agent-created memories remain deferred.

## Development Checks

```bash
cd backend
pytest
```

```bash
cd frontend
npm install
npm run build
```

## Project Structure

```text
backend/   FastAPI control-plane scaffold
frontend/  React + Vite + TypeScript client scaffold
memory/    ChromaDB and memory/RAG configuration boundary
agents/    LangGraph package scaffold
docs/      Product and architecture documentation
rag/       Reserved for future retrieval pipelines
```
