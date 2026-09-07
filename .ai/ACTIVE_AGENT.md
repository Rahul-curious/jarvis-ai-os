# JARVIS AI — ACTIVE AGENT

## Current Agent

CODEX

## Status

ACTIVE

## Lock

🔒 CODEX currently owns repository write access.

## Standby Agent

ANTIGRAVITY

## Rule

Only the agent listed as ACTIVE may modify the repository.

ANTIGRAVITY must remain in STANDBY while CODEX is ACTIVE.


## Current Phase

Phase 7 — Workspace Foundation

## Current Subphase

7.4 — GitHub Provider

## Current Work

Codex is actively implementing the GitHub provider integration.

The implementation keeps GitHub-specific HTTP, request/response schemas, and error translation isolated under:

backend/app/integrations/github/

The existing provider-neutral registry and contracts must remain unchanged unless a concrete compatibility issue requires modification.

## Handoff Rule

The active agent must:

1. Finish or checkpoint its current work.
2. Run relevant tests.
3. Review `git diff`.
4. Commit the changes.
5. Push the checkpoint to GitHub.
6. Update `PROJECT_STATE.md`.
7. Update `HANDOFF.md`.
8. Change this file so the receiving agent becomes ACTIVE.

## Important

Never have Codex and Antigravity actively modifying the same working tree at the same time.