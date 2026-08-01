# JARVIS AI OS

JARVIS AI OS is a modular, production-oriented AI platform designed to combine authentication, persistent memory, Retrieval-Augmented Generation (RAG), document intelligence, and governed AI agent execution behind a clean and extensible architecture.

The long-term goal is to evolve JARVIS from an intelligent assistant platform into a secure AI operating system capable of reasoning across user memory, private knowledge, tools, and external systems while maintaining explicit execution boundaries, auditability, and user control.

> JARVIS is inspired by the idea of Tony Stark's JARVIS, but the project is being engineered as a real-world AI systems platform rather than a fictional assistant clone.

---

## Current Status

JARVIS has completed the core platform foundation through **Phase 5** and the first three foundations of the **Phase 6 AI Agent Framework**.

### Implemented

- ✅ Core backend and frontend foundation
- ✅ Authentication and session management
- ✅ Persistent Memory Engine
- ✅ Document management
- ✅ Retrieval-Augmented Generation (RAG)
- ✅ Vector storage with ChromaDB
- ✅ Agent Domain Foundation
- ✅ Agent Runtime Abstraction
- ✅ Agent Context Assembly Foundation
- ✅ Docker-based local development environment
- ✅ Automated backend test coverage
- ✅ Alembic database migrations

### In Progress / Planned

- 🚧 Tool Registry
- 🚧 Agent Planner
- 🚧 Agent Executor
- 🚧 Memory-to-Agent integration
- 🚧 Knowledge/RAG-to-Agent integration
- 🚧 Agent API execution layer
- 🚧 Advanced agent orchestration
- 🚧 Streaming execution events
- 🚧 Multi-agent capabilities
- 🚧 Browser/computer interaction
- 🚧 Voice interface

---

# Architecture

JARVIS follows a layered architecture designed to keep infrastructure, domain logic, AI orchestration, and user-facing interfaces separated.

```text
                    ┌──────────────────────┐
                    │      Frontend        │
                    │ React + TypeScript   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     FastAPI API      │
                    │ Authentication / API │
                    └──────────┬───────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
      ┌────────────┐    ┌────────────┐    ┌──────────────┐
      │   Memory   │    │ Documents  │    │    Agents    │
      │   Engine   │    │  + RAG     │    │   Domain     │
      └─────┬──────┘    └─────┬──────┘    └──────┬───────┘
            │                 │                   │
            │                 │            ┌──────▼────────┐
            │                 │            │Context Assembly│
            │                 │            └──────┬────────┘
            │                 │                   │
            │                 │            ┌──────▼────────┐
            │                 │            │Runtime Contract│
            │                 │            └───────────────┘
            │                 │
            ▼                 ▼
      ┌────────────┐    ┌────────────┐
      │ PostgreSQL │    │  ChromaDB  │
      └────────────┘    └────────────┘
```

The Agent Framework is intentionally being introduced incrementally. Memory and RAG already exist as independent platform capabilities, but concrete agent-to-Memory and agent-to-RAG integration is deferred to later Phase 6 milestones.

---

# Phase Progress

## Phase 0 — Architecture & Planning ✅

Established the initial product vision and engineering architecture.

Includes:

- System architecture
- API design
- Database design
- Feature planning
- Development roadmap
- Product vision

Architecture documentation lives under:

```text
docs/
```

---

## Phase 1 — Platform Foundation ✅

Established the initial monorepo and development environment.

Includes:

- FastAPI backend scaffold
- React + Vite + TypeScript frontend
- PostgreSQL
- Docker Compose
- LangGraph package scaffold
- Environment configuration
- Health checks

---

## Phase 2 — Core Platform Foundation ✅

Established the supporting backend structure required by later domains.

The platform follows explicit domain/service boundaries and dependency injection conventions used by later Authentication, Memory, RAG, and Agent components.

---

## Phase 3 — Authentication & Identity ✅

Implemented authenticated user sessions and identity management.

### Features

- User registration
- Login
- JWT access tokens
- Refresh tokens
- HttpOnly cookie sessions
- Session persistence
- Logout
- Current-user resolution
- Audit logging

### Authentication Endpoints

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout

GET  /api/v1/users/me
```

Access and refresh JWTs are stored using HttpOnly cookies. The frontend does not store authentication tokens in JavaScript-accessible storage.

---

## Phase 4 — Memory Engine ✅

Implemented persistent user-scoped memory.

### Capabilities

- Short-term memory
- Long-term memory
- User preferences
- Project memories
- Corrections
- Expiration
- Soft deletion
- Memory references
- Recall reinforcement
- Memory events
- Deterministic scoring
- User-scoped search

### Memory Endpoints

```text
POST   /api/v1/memory
GET    /api/v1/memory
GET    /api/v1/memory/{id}
PUT    /api/v1/memory/{id}
DELETE /api/v1/memory/{id}

POST /api/v1/memory/search
POST /api/v1/memory/reinforce
```

Current Memory search remains based on the implemented Phase 4 retrieval behavior. Semantic agent-memory integration is not part of the current Phase 6.3 implementation.

---

## Phase 5 — RAG Knowledge Engine ✅

Implemented private document ingestion and Retrieval-Augmented Generation infrastructure.

### Capabilities

- Document upload
- Text extraction
- Document chunking
- Embedding abstraction
- Vector storage
- Semantic retrieval
- Confidence information
- Citations
- Grounded query responses
- User-scoped document access

### Supported Documents

Current ingestion supports:

- TXT
- Markdown
- PDF

### Knowledge Endpoints

```text
POST   /api/v1/documents/upload
GET    /api/v1/documents
GET    /api/v1/documents/{id}
DELETE /api/v1/documents/{id}

POST /api/v1/rag/search
POST /api/v1/rag/query
```

Document metadata and relational state are stored in PostgreSQL while document chunk vectors are stored in ChromaDB.

---

# Phase 6 — AI Agent Framework 🚧

Phase 6 introduces a governed agent architecture on top of the existing JARVIS platform.

The framework is being built incrementally so agent execution does not destabilize Authentication, Memory, or RAG.

## Phase 6.1 — Agent Domain Foundation ✅

Introduced persistent agent-domain primitives.

### Implemented

- Agent definitions
- Agent runs
- Agent steps
- Agent events
- Agent artifacts
- Lifecycle policies
- Validation limits
- Domain errors
- Owner-scoped repositories
- Agent services
- PostgreSQL persistence
- Alembic migration
- Agent-domain tests

---

## Phase 6.2 — Agent Runtime Abstraction ✅

Introduced a framework-independent execution contract.

### Implemented

- Runtime interface
- Runtime context
- Runtime execution models
- Runtime result models
- Runtime events
- Runtime statuses
- Runtime lifecycle
- Runtime validation
- Runtime factory
- Runtime dependency injection
- Timeout handling
- Cancellation handling
- Retryable failure handling

The runtime backend intentionally remains replaceable so future execution engines can be introduced without coupling the Agent domain to a specific orchestration framework.

---

## Phase 6.3 — Context Assembly Foundation ✅

Introduced the structured context pipeline used to prepare information before agent execution.

### Implemented

- `AgentContextAssembler`
- Context builder
- Typed context models
- Context metadata
- Async context provider interfaces
- Provider registry
- Deterministic priority-based merging
- Context validation
- Duplicate-provider detection
- Required-section validation
- JSON validation
- Context size limits

### Current Context Providers

- Conversation History Provider
- Runtime Metadata Provider
- User Information Provider
- Agent Configuration Provider

### Reserved Extension Points

The architecture also reserves:

- `MemoryContextProvider`
- `KnowledgeContextProvider`

These are extension interfaces only at this stage.

Concrete Memory retrieval is deferred to a later Phase 6 milestone.

Concrete Knowledge/RAG retrieval is also deferred to a later Phase 6 milestone.

---

# Phase 6 Roadmap

```text
6.1 Agent Domain Foundation             ✅
        ↓
6.2 Runtime Abstraction                 ✅
        ↓
6.3 Context Assembly                    ✅
        ↓
6.4 Tool Registry                       🚧
        ↓
6.5 Planner
        ↓
6.6 Executor
        ↓
6.7 Memory Integration
        ↓
6.8 Knowledge (RAG) Integration
        ↓
6.9 Agent API / Integration
```

The architecture is intentionally incremental. Future milestones should extend existing contracts rather than bypass or replace them.

---

# Technology Stack

## Backend

- Python
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- PostgreSQL

## AI / Knowledge

- ChromaDB
- Embedding abstraction
- Retrieval-Augmented Generation
- LangGraph scaffold
- Custom Agent Framework

## Frontend

- React
- TypeScript
- Vite

## Infrastructure

- Docker
- Docker Compose
- PostgreSQL
- ChromaDB

---

# Project Structure

```text
jarvis-ai-os/
│
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   └── domains/
│   │       ├── agents/
│   │       ├── documents/
│   │       ├── governance/
│   │       ├── identity/
│   │       └── memory/
│   └── tests/
│
├── frontend/
│   └── React + TypeScript application
│
├── agents/
│   └── Agent orchestration package / LangGraph scaffold
│
├── memory/
│   └── Memory and vector configuration boundary
│
├── rag/
│   └── Retrieval pipeline boundary
│
├── docs/
│   └── Architecture and product documentation
│
├── docker-compose.yml
└── README.md
```

---

# Local Development

## Prerequisites

Install:

- Docker
- Docker Compose
- Git

For frontend development outside Docker, Node.js/npm is also required.

---

## 1. Clone the Repository

```bash
git clone <repository-url>
cd jarvis-ai-os
```

## 2. Configure Environment

```bash
cp .env.example .env
```

Review `.env` and configure any environment-specific values before running the stack.

## 3. Start JARVIS

```bash
docker compose up --build
```

The default development stack starts:

```text
postgres
chromadb
backend
frontend
```

## 4. Open Services

Frontend:

```text
http://localhost:5173
```

Backend health:

```text
http://localhost:8000/api/v1/health
```

OpenAPI:

```text
http://localhost:8000/docs
```

---

# Development Checks

## Backend Tests

```bash
cd backend
pytest
```

## Backend Linting

Run the repository's configured Ruff checks from the backend development environment.

## Frontend

```bash
cd frontend
npm install
npm run build
```

## Docker Configuration

```bash
docker compose config
```

## Full Local Stack

```bash
docker compose up --build
```

Then verify:

```text
GET /api/v1/health
```

---

# Security Principles

JARVIS is designed around explicit security boundaries.

Current principles include:

- HttpOnly authentication cookies
- User-scoped data access
- Owner-scoped agent resources
- Explicit dependency injection
- Audit logging
- Controlled agent lifecycle transitions
- Bounded context assembly
- No silent agent-created memories
- No autonomous tool execution
- No browser/computer control
- No unrestricted background agents

Future autonomous capabilities should be introduced behind explicit policies, permissions, approvals, and audit trails.

---

# Current Limitations

JARVIS is under active development.

The current system does **not** yet provide:

- Autonomous agent execution
- Tool calling
- Browser automation
- Computer control
- Voice interaction
- Multi-agent delegation
- Autonomous scheduling
- Agent-driven Memory retrieval
- Agent-driven RAG retrieval
- Production distributed worker execution
- Long-running agent event streaming

These capabilities are intentionally deferred rather than partially implemented.

---

# Engineering Philosophy

JARVIS is being developed using several core principles:

1. **Architecture before autonomy**  
   Agent capabilities should be built on explicit contracts and lifecycle boundaries.

2. **Incremental implementation**  
   Each milestone should be independently testable and reviewable.

3. **Separation of concerns**  
   Authentication, Memory, Knowledge, Agents, Runtime, and Context Assembly remain separate domains.

4. **Framework independence**  
   Core Agent-domain contracts should not depend directly on a specific orchestration framework.

5. **Security by default**  
   User isolation, bounded execution, auditing, and explicit permissions take priority over unrestricted autonomy.

6. **Test before expansion**  
   New capabilities should preserve existing Phase 0–5 behavior and maintain regression coverage.

---

# Vision

The long-term direction for JARVIS is a personal AI operating system capable of securely combining:

```text
Conversation
     +
Long-Term Memory
     +
Private Knowledge
     +
Reasoning
     +
Tools
     +
External Systems
     +
Multimodal Interaction
     ↓
Governed AI Agent System
```

Future capabilities may include advanced document intelligence, multimodal retrieval, structured information extraction, cross-document reasoning, tool-enabled workflows, multi-agent orchestration, browser/computer interaction, and richer JARVIS-style interfaces.

The objective is not simply to build a chatbot.

The objective is to build a modular AI system that can progressively understand context, reason over private information, execute governed workflows, and evolve without sacrificing architectural integrity.

---

# License

Add the project's chosen license here before public distribution.
