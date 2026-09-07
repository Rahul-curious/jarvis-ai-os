# JARVIS AI OS — PROJECT STATE

## Project

JARVIS AI Operating System

## Repository

GitHub:
https://github.com/Rahul-curious/jarvis-ai-os

## Current Branch

main

## Current Agent

CODEX

## Standby Agent

ANTIGRAVITY

---

# Current Development Phase

## Phase 7 — Workspace Foundation

Status: IN PROGRESS

Phase 7 establishes the workspace foundation and provider integration architecture for JARVIS.

### Phase 7 Progress

- 7.1 — Contracts ✅
- 7.2 — Credential Boundary ✅
- 7.3 — Provider Registry ✅
- 7.4 — GitHub Provider 🔵 IN PROGRESS

---

# Current Subphase

## Phase 7.4 — GitHub Provider

Status: IN PROGRESS

Codex is currently implementing the GitHub provider integration.

The implementation must preserve the provider-neutral architecture already established in Phase 7.1–7.3.

### Current Architecture Direction

GitHub-specific implementation details should remain isolated under:

`backend/app/integrations/github/`

This includes:

- GitHub-specific HTTP communication
- GitHub request and response schemas
- GitHub-specific error translation
- GitHub provider implementation details

The existing provider-neutral contracts must remain stable.

The existing provider registry should be reused rather than redesigned unnecessarily.

The GitHub provider should be registered through the existing provider registry.

Do not introduce GitHub-specific behavior into provider-neutral contracts unless a concrete compatibility requirement makes it necessary.

---

# Current Task

Continue Phase 7.4 — GitHub Provider from the current repository state.

Codex is the active development agent.

The current objective is to complete the GitHub provider integration while preserving the existing provider-neutral contracts, credential boundary, and provider registry.

The implementation should:

1. Follow the existing project architecture.
2. Keep GitHub-specific HTTP behavior isolated under `backend/app/integrations/github/`.
3. Keep request/response schemas isolated to the GitHub integration where appropriate.
4. Translate GitHub-specific errors at the integration boundary.
5. Register the GitHub provider through the existing provider registry.
6. Avoid unnecessary changes to the provider-neutral registry.
7. Add or update tests for critical functionality.
8. Preserve existing completed Phase 7 work.

---

# Project History

## Completed Major Phases

- Phase 0 — Architecture ✅
- Phase 1 — Foundation ✅
- Phase 2 — Security / REST / Migration ✅
- Phase 3 — Authentication ✅
- Phase 4 — Memory Engine ✅
- Phase 5 — RAG Knowledge Engine ✅

## Current Major Phase

- Phase 7 — Workspace Foundation 🔵 IN PROGRESS

## Completed Phase 7 Work

- 7.1 — Contracts ✅
- 7.2 — Credential Boundary ✅
- 7.3 — Provider Registry ✅

## Current Phase 7 Work

- 7.4 — GitHub Provider 🔵 IN PROGRESS

## Future

Continue the remaining JARVIS roadmap after Phase 7 according to the project's existing documentation and roadmap.

Do not assume future phases are complete.

---

# Current Git Checkpoint

## Repository State

Branch:

`main`

Latest verified committed checkpoint:

`ba8dab2`

Commit:

`chore: add AI agent handoff and locking system`

Remote:

`origin/main`

Working tree:

The AI handoff system was committed and pushed before the current Phase 7.4 implementation work.

Any newer uncommitted changes belong to the active Codex session and must not be overwritten during an agent handoff.

---

# Important Existing Project Instructions

Before modifying code, the active agent must read:

- `AGENTS.md`
- relevant documentation under `docs/`
- relevant source files
- relevant tests

The repository's existing architecture, conventions, and contracts take priority.

---

# Architecture Preservation Rules

Do not restart completed phases.

Do not replace existing architecture without a concrete technical reason.

Do not perform unrelated refactoring.

Do not delete functioning systems simply to introduce a new implementation.

Prefer small, incremental, production-ready changes.

Preserve existing provider-neutral abstractions.

Preserve existing credential boundaries.

Preserve existing provider registry behavior unless a concrete requirement requires modification.

---

# Phase 7.4 Architecture Constraint

The GitHub provider must remain isolated from provider-neutral abstractions as much as practical.

GitHub-specific details should stay inside:

`backend/app/integrations/github/`

Provider-neutral contracts should remain provider-neutral.

The provider registry should continue to act as the registration/discovery mechanism.

Do not redesign the provider registry merely to accommodate GitHub.

---

# Testing Expectations

Critical functionality must have appropriate tests.

Before a task is considered complete:

1. Run relevant tests.
2. Verify the GitHub provider behavior.
3. Verify provider registration.
4. Verify error translation where applicable.
5. Verify existing functionality has not regressed.

Record important test results during handoff.

---

# Agent Handoff

The active agent owns repository write access.

The standby agent must not modify the repository.

Current ownership:

CODEX = ACTIVE

ANTIGRAVITY = STANDBY

Before changing the active agent:

1. Finish or checkpoint the current task.
2. Run relevant tests.
3. Review `git status`.
4. Review `git diff`.
5. Commit the current work.
6. Push the checkpoint to GitHub.
7. Update this file.
8. Update `HANDOFF.md`.
9. Update `ACTIVE_AGENT.md`.
10. Commit and push the handoff state.

Never hand off meaningful uncommitted work.

---

# Receiving Agent Requirements

When another agent becomes ACTIVE, it must first read:

- `AGENTS.md`
- `.ai/ACTIVE_AGENT.md`
- `.ai/PROJECT_STATE.md`
- `.ai/HANDOFF.md`
- `.ai/RULES.md`

Then verify:

```bash
git status
git branch --show-current
git log -1 --oneline