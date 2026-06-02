# JARVIS AI OS

JARVIS is an AI Operating System inspired by Tony Stark's JARVIS.

This repository currently contains the Phase 1 foundation:

- FastAPI backend control-plane scaffold.
- React + Vite + TypeScript frontend scaffold.
- PostgreSQL service for future relational persistence.
- ChromaDB service for future memory and RAG vectors.
- LangGraph package scaffold for future agent orchestration.
- Docker Compose local development stack.

Business logic for assistant chat, long-term memory, RAG, agents, automation, and governance is intentionally not implemented yet.

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

## Project Structure

```text
backend/   FastAPI control-plane scaffold
frontend/  React + Vite + TypeScript client scaffold
memory/    ChromaDB and memory/RAG configuration boundary
agents/    LangGraph package scaffold
docs/      Product and architecture documentation
rag/       Reserved for future retrieval pipelines
```
