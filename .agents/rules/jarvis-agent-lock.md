---
trigger: always_on
---

# JARVIS AI OS — Antigravity Agent Lock

## Purpose

This repository uses a single-active-agent model for AI-assisted development.

Codex and Antigravity operate on the same JARVIS repository, but only one agent may actively modify the working tree at a time.

The authoritative ownership state is:

`.ai/ACTIVE_AGENT.md`

---

# Mandatory Startup Inspection

Before making any modification, read:

- `AGENTS.md`
- `.ai/ACTIVE_AGENT.md`
- `.ai/PROJECT_STATE.md`
- `.ai/HANDOFF.md`
- `.ai/RULES.md`

Then inspect:

```bash
git status
git branch --show-current
git log -1 --oneline

