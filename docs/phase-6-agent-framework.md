# Phase 6 Agent Framework Architecture

## Planning Summary

Phase 6 introduces the first governed AI Agent Framework foundation for JARVIS. The goal is to support agent run planning, state, context assembly, execution events, and LangGraph orchestration contracts without destabilizing completed Phase 0-5 work.

This is a design and implementation plan only. It does not implement Phase 6 behavior.

## Current Repository Observations

This plan is based on the current repository and Phase 0-5 implementation:

- FastAPI exposes versioned routes through `backend/app/api/router.py`.
- Authentication resolves users through `get_current_user` in `backend/app/api/dependencies.py`.
- Domain services use explicit dependencies such as `AsyncSession`, `Settings`, embedding providers, and vector stores.
- The Memory Engine is implemented under `backend/app/domains/memory` with relational records, events, references, search, recall, reinforcement, and audit logging.
- The RAG Knowledge Engine is implemented under `backend/app/domains/documents` with document parsing, chunking, embeddings, ChromaDB retrieval, confidence, citations, and extractive grounded answers.
- Governance audit logging exists in `backend/app/domains/governance/audit.py`.
- `backend/app/domains/agents` is currently reserved for agent definitions, runs, steps, approvals, tool executions, and evaluations.
- The top-level `agents` package contains the Phase 1 LangGraph scaffold with `AgentRunState` and `create_agent_graph()`.

Phase 6 should add an agent layer beside existing Memory and RAG services. It should not move Memory or RAG responsibilities into agent code.

## Goals

- Provide a production-grade foundation for user-requested agent runs.
- Persist agent definitions, runs, steps, events, context references, and outputs.
- Provide extensible context provider interfaces that allow future integration with Memory and RAG through stable service-layer adapters.
- Use LangGraph for orchestrated state transitions while keeping persistence, authorization, and audit in the backend.
- Support a synchronous MVP run path with a clean route to future async workers, streaming, and resumable runs.
- Preserve user isolation, current HttpOnly cookie authentication, auditability, and least-privilege data access.
- Keep Phase 6 independently testable and safe to release before browser automation, computer control, voice, or autonomous scheduling.

## Scope

Phase 6 should design and later implement:

- Agent run API resources under `/api/v1/agents`.
- Agent domain models for definitions, runs, steps, events, and artifacts.
- Backend services for validation, authorization, persistence, audit, context assembly, and runtime invocation.
- Extensible context provider interfaces and the Context Assembly pipeline. Concrete Memory and Knowledge provider integrations are implemented in later phases.
- A LangGraph runtime adapter that executes a minimal planner/synthesizer graph.
- Explicit lifecycle states and safe error transitions.
- Structured run events suitable for future streaming.
- Tests for API routes, services, repositories, context providers, and graph runtime behavior.

## Non-Goals

Phase 6 should not implement:

- Browser automation.
- Computer control.
- Voice assistant behavior.
- Autonomous scheduled agents.
- Multi-agent delegation beyond reserved interfaces.
- Tool marketplace or connector execution.
- New memory semantics or changes to existing Memory APIs.
- New RAG ingestion, vector store, or citation behavior.
- A full model provider gateway unless a narrow interface is needed for testable orchestration.
- Redesign of completed Phase 0-5 services.

## Architecture Overview

The Agent Framework sits above the existing platform capabilities and orchestrates the complete agent execution lifecycle while remaining independent of infrastructure-specific implementations.

- API routes accept authenticated agent run requests and delegate execution to the Agent domain.
- `AgentRunService` validates requests, creates durable run records, assembles execution context, invokes a runtime adapter, persists execution events, and returns typed responses.
- `AgentContextAssembler` coordinates registered context providers, validates and merges their output, and produces a single execution context for the runtime.
- During Phase 6.3, the Context Assembly layer supports the following providers:
  - Conversation History Provider
  - Runtime Metadata Provider
  - User Information Provider
  - Agent Configuration Provider
- The Context Assembly architecture is designed to support additional providers through extensible interfaces.
- `MemoryContextProvider` is defined as an extension point for supplying memory context to the Context Assembly pipeline. During Phase 6.3, it does **not** perform memory retrieval. Concrete Memory integration is implemented in **Phase 6.7 – Memory Integration**.
- `KnowledgeContextProvider` is defined as an extension point for supplying knowledge context to the Context Assembly pipeline. During Phase 6.3, it does **not** perform RAG retrieval. Concrete Knowledge (RAG) integration is implemented in **Phase 6.8 – Knowledge Integration**.
- `AgentRuntimeAdapter` converts backend runtime state into the runtime-specific execution state (for example, LangGraph) and converts execution results back into persistable backend models. Runtime implementations remain pluggable and framework-agnostic.
- The `agents` package remains a pure orchestration layer. It must not import FastAPI, SQLAlchemy, database models, ORM sessions, HTTP request objects, or any other infrastructure-specific implementation details. Infrastructure concerns are injected through interfaces and dependency injection.

## Component Diagram

```mermaid
flowchart TB
    Client["Web Client / API Client"] --> AgentsAPI["/api/v1/agents Routes"]
    AgentsAPI --> Auth["Current User Dependency"]
    AgentsAPI --> AgentService["AgentRunService"]

    AgentService --> AgentRepo["AgentRepository"]
    AgentRepo --> Postgres["PostgreSQL"]

    AgentService --> Audit["Audit Service"]
    AgentService --> ContextAssembler["AgentContextAssembler"]

    ContextAssembler --> ConversationProvider["ConversationHistoryProvider"]
    ContextAssembler --> RuntimeProvider["RuntimeMetadataProvider"]
    ContextAssembler --> UserProvider["UserInformationProvider"]
    ContextAssembler --> ConfigProvider["AgentConfigurationProvider"]
    ContextAssembler --> MemoryProvider["MemoryContextProvider (Extension Point)"]
    ContextAssembler --> KnowledgeProvider["KnowledgeContextProvider (Extension Point)"]

    AgentService --> RuntimeAdapter["AgentRuntimeAdapter"]

    RuntimeAdapter --> LangGraph["jarvis_agents LangGraph"]
    LangGraph --> Planner["Planner Node"]
    LangGraph --> Synthesizer["Synthesizer Node"]
```

## Folder Structure

Planned implementation folders should be introduced incrementally by milestone.

```text
backend/app/api/routes/
  agents.py

backend/app/domains/agents/
  README.md
  models.py
  schemas.py
  repository.py
  services.py
  context.py
  runtime.py
  errors.py
  policies.py

backend/alembic/versions/
  <phase_6_agent_framework_migration>.py

agents/src/jarvis_agents/
  state.py
  graph.py
  nodes.py
  prompts.py
  events.py
  errors.py

backend/tests/
  test_agents_api.py
  test_agents_repository.py
  test_agents_services.py
  test_agents_context.py
  test_agents_runtime.py

agents/tests/
  test_graph.py
  test_nodes.py
```

## Class Hierarchy

```mermaid
classDiagram

    class AgentRunService {
        +create_run(current_user, payload, request)
        +get_run(current_user, run_id)
        +list_runs(current_user, filters)
        +cancel_run(current_user, run_id, request)
        +execute_run(run_id, current_user, request)
    }

    class AgentRepository {
        +create_run()
        +add_step()
        +add_event()
        +update_run_status()
        +get_run_for_user()
        +list_runs_for_user()
    }

    class AgentContextAssembler {
        +build_context(current_user, request)
        +register_provider(provider)
        +validate_context()
        +merge_context()
    }

    class ConversationHistoryProvider {
        +build_context()
    }

    class RuntimeMetadataProvider {
        +build_context()
    }

    class UserInformationProvider {
        +build_context()
    }

    class AgentConfigurationProvider {
        +build_context()
    }

    class MemoryContextProvider {
        +build_context()
    }

    class KnowledgeContextProvider {
        +build_context()
    }

    class AgentRuntimeAdapter {
        +invoke(initial_state)
        +stream(initial_state)
    }

    class AgentRunState {
        +tenant_id
        +workspace_id
        +user_id
        +run_id
        +task
        +status
        +execution_context
        +messages
        +events
        +output
        +error
    }

    AgentRunService --> AgentRepository
    AgentRunService --> AgentContextAssembler
    AgentRunService --> AgentRuntimeAdapter

    AgentContextAssembler --> ConversationHistoryProvider
    AgentContextAssembler --> RuntimeMetadataProvider
    AgentContextAssembler --> UserInformationProvider
    AgentContextAssembler --> AgentConfigurationProvider
    AgentContextAssembler --> MemoryContextProvider
    AgentContextAssembler --> KnowledgeContextProvider

    AgentRuntimeAdapter --> AgentRunState
```
## Agent Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Requested
    Requested --> Validating
    Validating --> Rejected
    Validating --> Queued
    Queued --> Running
    Running --> WaitingForApproval
    WaitingForApproval --> Running
    WaitingForApproval --> Cancelled
    Running --> Succeeded
    Running --> Failed
    Running --> Cancelled
    Failed --> Retriable
    Retriable --> Queued
    Rejected --> [*]
    Succeeded --> [*]
    Cancelled --> [*]
```

| State | Responsibility |
| --- | --- |
| `requested` | Persist the authenticated user request. |
| `validating` | Check payload, limits, policy, and supported agent type. |
| `queued` | Reserve async execution semantics. MVP may transition immediately. |
| `running` | Execute graph nodes and persist run events. |
| `waiting_for_approval` | Reserve gated approval for future tool use. |
| `succeeded` | Persist final answer, citations, context references, and metrics. |
| `failed` | Persist structured error details and a safe user-facing message. |
| `cancelled` | Stop pending work and record audit/event entries. |
| `retriable` | Mark failures safe to retry without duplicate side effects. |

## Request Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as Agents API
    participant Auth as Auth Dependency
    participant Service as AgentRunService
    participant Context as AgentContextAssembler
    participant Runtime as AgentRuntimeAdapter
    participant DB as PostgreSQL
    participant Audit as Audit Service

    Client->>API: POST /api/v1/agents/runs
    API->>Auth: Resolve current user
    Auth-->>API: User

    API->>Service: create_run(payload, user)

    Service->>DB: Insert agent_run(status=requested)
    Service->>Audit: Record agents.run.requested

    Service->>Context: Build execution context
    Context-->>Service: Execution Context

    Service->>Runtime: Invoke graph(initial_state)
    Runtime-->>Service: Output and events

    Service->>DB: Persist steps, events, output, status
    Service->>Audit: Record agents.run.succeeded

    Service-->>API: AgentRunRead
    API-->>Client: Run response
```
## API Integration Strategy

Phase 6 should add routes without changing existing Memory, RAG, Auth, or User endpoints.

Proposed endpoints:

- `POST /api/v1/agents/runs`
- `GET /api/v1/agents/runs`
- `GET /api/v1/agents/runs/{run_id}`
- `POST /api/v1/agents/runs/{run_id}/cancel`
- `GET /api/v1/agents/runs/{run_id}/events`

MVP behavior:

- `POST /agents/runs` may execute synchronously and return the completed run.
- `GET /agents/runs/{run_id}/events` should return persisted events as a list.
- Streaming over SSE or WebSocket should be deferred until event persistence is stable.

Representative request:

```json
{
  "agent_type": "assistant",
  "task": "Summarize my uploaded knowledge about the deployment plan.",
  "context": {
    "include_conversation": true,
    "include_runtime": true,
    "include_user": true
}
}
```

Representative response:

```json
{
  "id": "agent-run-id",
  "agent_type": "assistant",
  "status": "succeeded",
  "task": "Summarize my uploaded knowledge about the deployment plan.",
  "output": "Concise grounded response.",
  "citations": [],
  "memory_references": [],
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```




## Dependency Injection Strategy

Phase 6 should follow the existing FastAPI dependency conventions and keep all dependencies explicit, testable, and replaceable.

General principles:

- Define route constants for `DB_SESSION_DEP`, `SETTINGS_DEP`, and `CURRENT_USER_DEP`.
- Add shared agent-specific providers in `backend/app/api/dependencies.py` only when multiple routes require them.
- Keep dependencies explicit in route signatures.
- Construct services using dependency injection rather than global state.
- Keep `AgentRuntimeAdapter` behind a dependency so tests can replace it with fakes or mock implementations.
- Keep `AgentContextAssembler` independent of infrastructure-specific implementations.

### Proposed Providers

- `get_agent_runtime_adapter(settings)`
- `get_agent_context_assembler(settings)`
- `get_agent_policy(settings)`

During Phase 6.3, `AgentContextAssembler` should assemble context only from the providers implemented in this milestone:

- Conversation History Provider
- Runtime Metadata Provider
- User Information Provider
- Agent Configuration Provider

`MemoryContextProvider` and `KnowledgeContextProvider` are registered as extension interfaces only. They do not require Memory, RAG, embedding, or vector store dependencies during this milestone. Concrete dependency injection for Memory and Knowledge providers is introduced in:

- Phase 6.7 – Memory Integration
- Phase 6.8 – Knowledge Integration

### Avoid

- Global mutable graph state.
- Direct database access from graph nodes.
- FastAPI imports inside the `agents` package.
- SQLAlchemy imports inside the `agents` package.
- Passing `Request` objects into graph nodes.
- Coupling `AgentContextAssembler` directly to Memory or RAG infrastructure before their respective integration phases.

## Error Handling

Phase 6 should use domain-specific exceptions and route-level translation, matching Memory and RAG patterns.

Proposed exceptions:

- `AgentValidationError`
- `AgentNotFoundError`
- `AgentPolicyDeniedError`
- `AgentRuntimeError`
- `AgentTimeoutError`
- `AgentCancelledError`

HTTP mapping:

| Exception | HTTP status | User-facing behavior |
| --- | --- | --- |
| `AgentValidationError` | 400 | Show actionable request issue. |
| `AgentPolicyDeniedError` | 403 | Explain permission or policy denial without leaking internals. |
| `AgentNotFoundError` | 404 | Return generic not found. |
| `AgentTimeoutError` | 504 | Mark run failed or retriable. |
| `AgentRuntimeError` | 503 | Mark run failed with safe message. |
| Unexpected exception | 500 | Mark run failed, audit, and log exception. |

Graph errors should be captured as run events and summarized safely. Internal prompts, hidden reasoning, stack traces, and provider payloads should not be returned to clients.

## Logging Strategy

Logging should extend the existing `configure_logging()` foundation with structured fields where possible.

Required log fields:

- `request_id`
- `user_id`
- `agent_run_id`
- `agent_type`
- `status`
- `event_type`
- `duration_ms`
- `error_code`

Audit events:

- `agents.run.requested`
- `agents.run.started`
- `agents.run.succeeded`
- `agents.run.failed`
- `agents.run.cancelled`


Do not log:

- Access or refresh tokens.
- Full memory contents at info level.
- Full uploaded document snippets at info level.
- Hidden model reasoning or private graph internals.

## Testing Strategy

Testing should be layered and milestone-specific.

### Backend Unit Tests

- Validate agent schema constraints and lifecycle transitions.
- Verify repository queries are user-scoped.
- Verify service creates runs, records events, updates statuses, and audits actions.
- Verify domain exceptions map to API responses.

### Context Integration Tests

- Test Conversation Provider

- Test Runtime Provider

- Test User Provider

- Test Config Provider

- Test Context Merge

- Test Validation

- Test Limits


### Runtime Tests

- Test LangGraph state transitions with deterministic fake nodes.
- Verify graph output includes status, events, context references, and final output.
- Verify runtime errors become structured failure events.

### API Tests

- `POST /agents/runs` requires authentication.
- A valid request creates a run and returns a typed response.
- A run is visible only to its owner.
- Events can be listed.
- Cancellation works for cancellable states.

### Regression Tests

- Existing Memory tests remain unchanged and passing.
- Existing RAG tests remain unchanged and passing.
- Agent tests use service adapters and avoid Memory/RAG internals.

## Security Considerations

- All agent endpoints must require current user authentication.
- Agent runs must be user-scoped until tenants/workspaces are implemented.
- Agents must not create, edit, or delete memories in Phase 6.
- Agents must not upload, delete, or mutate knowledge sources in Phase 6.
- Tool execution is out of scope and denied by default.
- Context assembly should enforce size limits.
- Audit every run state transition and context retrieval summary.
- Store safe summaries and references instead of unnecessary raw sensitive context.
- Keep approval states in the lifecycle even while tool approvals are deferred.

## Scalability Considerations

Phase 6 can begin synchronously, but the architecture must not prevent async scale.

Short-term:

- Bounded context sizes.
- Bounded run duration.
- Bounded event counts.
- Idempotent request IDs where possible.

Medium-term:

- Move execution to a worker queue.
- Add run leasing and heartbeat timestamps.
- Add resumable LangGraph checkpoints.
- Stream run events to clients.

Long-term:

- Partition agent runs by tenant/workspace.
- Store high-volume events in append-only event storage.
- Separate orchestration workers from API containers.


## Future Extensibility

Phase 6 should reserve extension points for:

- Multi-agent supervisor/specialist delegation.
- Tool registry and policy-gated tool execution.
- Browser automation and computer control agents.
- Research and news intelligence agents.
- Voice-triggered agent runs.
- Workspace-scoped agents.
- Agent templates and user-configurable agent profiles.
- Evaluators for groundedness, memory use, policy compliance, and output quality.
- Event streaming and long-running background jobs.

## Implementation Milestones

Each milestone should be independently testable and commit-ready.

### Milestone 1: Agent Domain Persistence Foundation

Purpose:

Create durable agent run metadata without executing agent logic.

Deliverables:

- SQLAlchemy models for agent definitions, runs, run steps, and run events.
- Alembic migration for Phase 6 tables.
- Repository methods for create, read, list, status update, event append, and step append.
- Pydantic schemas for run create/read/list/event responses.

Files expected to change:

- `backend/app/domains/agents/models.py`
- `backend/app/domains/agents/schemas.py`
- `backend/app/domains/agents/repository.py`
- `backend/app/db/base.py`
- `backend/alembic/versions/<phase_6_agents>.py`
- `backend/tests/test_agents_repository.py`

Acceptance criteria:

- Migration creates Phase 6 tables and indexes.
- Agent runs are scoped by user ID.
- Repository tests cover create, list, get, status transition, event append, and owner isolation.
- Existing auth, memory, and RAG tests still pass.

Suggested commit message:

`Add Phase 6 agent run persistence foundation`

### Milestone 2: Agent API Resource Layer

Purpose:

Expose authenticated agent run resources without real graph execution.

Deliverables:

- `backend/app/api/routes/agents.py`.
- Router registration under `/api/v1/agents`.
- `POST /agents/runs`, `GET /agents/runs`, `GET /agents/runs/{run_id}`, and `GET /agents/runs/{run_id}/events`.
- Service layer that creates a run in `queued` or `requested` status.
- Audit events for run creation and lookup failures where useful.

Files expected to change:

- `backend/app/api/router.py`
- `backend/app/api/routes/agents.py`
- `backend/app/domains/agents/services.py`
- `backend/app/domains/agents/errors.py`
- `backend/tests/test_agents_api.py`
- `backend/tests/test_agents_services.py`

Acceptance criteria:

- Unauthenticated requests return 401.
- Authenticated users can create and list their own runs.
- Users cannot access another user's runs.
- API responses match typed schemas.
- No Memory or RAG behavior changes.

Suggested commit message:

`Expose authenticated agent run APIs`

### Milestone 3: Context Provider Adapters

Purpose

Build the Context Assembly foundation for the Agent Framework.

Deliverables

• AgentContextAssembler

• Context Builder

• Context Models

• Context Validation

• Context Merge Strategy

• Conversation History Provider

• Runtime Metadata Provider

• User Information Provider

• Agent Configuration Provider

• MemoryContextProvider (Extension Interface Only)

• KnowledgeContextProvider (Extension Interface Only)

• Unit Tests

Acceptance Criteria

✓ Context Assembly builds a validated execution context.

✓ Providers can be registered and composed.

✓ MemoryContextProvider exists only as an interface.

✓ KnowledgeContextProvider exists only as an interface.

✓ No Memory retrieval.

✓ No RAG retrieval.

✓ No Memory Engine changes.

✓ No Knowledge Engine changes.

Suggested Commit

feat(context): implement Phase 6.3 Context Assembly

### Milestone 4: LangGraph Runtime Adapter

Purpose:

Connect backend agent runs to the existing `agents` LangGraph package through a testable adapter.

Deliverables:

- Expanded `AgentRunState` with task, context, events, output, and error fields.
- Minimal graph nodes for planning and synthesis using deterministic behavior for tests.
- Backend `AgentRuntimeAdapter`.
- Runtime tests for successful and failed graph invocation.

Files expected to change:

- `agents/src/jarvis_agents/state.py`
- `agents/src/jarvis_agents/graph.py`
- `agents/src/jarvis_agents/nodes.py`
- `agents/src/jarvis_agents/events.py`
- `backend/app/domains/agents/runtime.py`
- `agents/tests/test_graph.py`
- `backend/tests/test_agents_runtime.py`

Acceptance criteria:

- Runtime can execute a minimal graph with no external model dependency.
- Runtime returns output, events, and status in a typed structure.
- Runtime errors are captured and do not crash API tests.
- The `agents` package remains free of FastAPI and SQLAlchemy imports.

Suggested commit message:

`Add LangGraph runtime adapter for agent runs`

### Milestone 5: End-to-End Synchronous Agent Execution

Purpose:

Allow a user to submit a task and receive a completed agent run response using Memory/RAG context.

Deliverables:

- `POST /agents/runs` executes the minimal graph synchronously.
- Run statuses transition from requested to running to succeeded or failed.
- Run events and final output are persisted.
- Audit events are recorded for start, success, and failure.

Files expected to change:

- `backend/app/domains/agents/services.py`
- `backend/app/api/routes/agents.py`
- `backend/tests/test_agents_api.py`
- `backend/tests/test_agents_services.py`

Acceptance criteria:

- Valid authenticated request returns `succeeded` with output.
- Run event list includes context assembly and graph execution events.
- Failure path persists `failed` status and safe error message.
- Existing Memory and RAG regression tests still pass unchanged.

Suggested commit message:

`Execute synchronous Phase 6 agent runs`

### Milestone 6: Cancellation And Event Inspection

Purpose:

Prepare the run model for long-running tasks before adding async workers.

Deliverables:

- `POST /agents/runs/{run_id}/cancel`.
- Cancellation rules for requested, queued, running, succeeded, failed, and cancelled states.
- Event listing filters and ordering.
- Tests for cancellation and event visibility.

Files expected to change:

- `backend/app/api/routes/agents.py`
- `backend/app/domains/agents/services.py`
- `backend/app/domains/agents/repository.py`
- `backend/tests/test_agents_api.py`
- `backend/tests/test_agents_services.py`

Acceptance criteria:

- Cancellable runs transition to `cancelled`.
- Terminal runs cannot be cancelled.
- Cancellation is owner-scoped.
- Cancellation records audit and event entries.

Suggested commit message:

`Add agent run cancellation and event inspection`

### Milestone 7: Frontend Agent Run Shell

Purpose:

Provide a minimal user surface for agent runs without adding advanced autonomy.

Deliverables:

- Agent run submission page.
- Run detail page showing status, output, events, memory references, and citations.
- Loading, empty, and error states.
- Typed frontend API client methods.

Files expected to change:

- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`
- `frontend/src/state/router.ts`
- `frontend/src/pages/AgentRunsPage.tsx`
- `frontend/src/pages/AgentRunDetailPage.tsx`
- `frontend/src/styles.css`

Acceptance criteria:

- Frontend builds successfully.
- Authenticated users can submit a run and view the result.
- UI clearly labels agent output as a Phase 6 controlled run.
- No browser automation, voice, or computer-control UI is introduced.

Suggested commit message:

`Add frontend shell for Phase 6 agent runs`

### Milestone 8: Documentation And Release Readiness

Purpose:

Finalize Phase 6 operational guidance before implementation is considered complete.

Deliverables:

- Update backend README with agent API usage.
- Add Phase 6 test commands and known limitations.
- Add release notes for the Agent Framework foundation.
- Verify Docker Compose, backend tests, agents package tests, and frontend build.

Files expected to change:

- `backend/README.md`
- `agents/README.md`
- `docs/phase-6-agent-framework.md`
- Optional release notes file if the repository adopts one.

Acceptance criteria:

- Documentation clearly states Phase 6 does not include autonomous tools.
- All test suites pass.
- Docker Compose runtime smoke validates auth plus a simple agent run.
- Implementation is ready for review as the Phase 6 foundation.

Suggested commit message:

`Document Phase 6 agent framework release readiness`

## Release Gate Checklist

Before Phase 6 is released:

- Existing Phase 3 auth tests pass.
- Existing Phase 4 memory tests pass.
- Existing Phase 5 RAG tests pass.
- New backend agent tests pass.
- New `agents` package tests pass.
- Frontend build passes if frontend pages are included.
- Docker Compose starts backend, frontend, Postgres, and Chroma.
- A runtime smoke can register/login, create an agent run, retrieve events, and inspect output.
- No browser automation, computer control, voice, or autonomous scheduled behavior is accidentally exposed.

## Final Architecture Position

Phase 6 establishes the foundation for JARVIS to become an agent-capable platform while remaining safe, modular, and production-ready.

The foundation consists of a governed run model, a durable execution lifecycle, a modular Context Assembly pipeline, and a replaceable LangGraph runtime boundary.

Context Assembly is intentionally designed around extensible provider interfaces so that future phases can integrate Memory, Knowledge (RAG), tools, and additional context sources without changing the core orchestration architecture.

This incremental design allows JARVIS to evolve toward advanced multi-agent systems while preserving the stability of the completed Phase 0–5 platform.
