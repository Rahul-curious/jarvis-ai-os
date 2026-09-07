# JARVIS AI OS — AI DEVELOPMENT RULES

## 1. Single Active Agent

Only ONE AI agent may actively modify the repository at any given time.

The agent listed as `ACTIVE` in `.ai/ACTIVE_AGENT.md` is the only authorized development agent.

---

## 2. Agent Ownership

Possible agents:

- CODEX
- ANTIGRAVITY

The non-active agent must remain in STANDBY.

---

## 3. No Simultaneous Development

Codex and Antigravity must never actively edit the same working tree at the same time.

Before switching agents, the current agent must complete a Git checkpoint.

---

## 4. Git Is the Source of Truth

All meaningful development work must be represented by Git commits.

Before handing the project to another agent:

- Review `git status`
- Review `git diff`
- Run relevant tests
- Commit the work
- Push to GitHub

---

## 5. Mandatory Handoff

Before changing the active agent:

1. Finish or checkpoint the current work.
2. Run relevant tests.
3. Review the changes.
4. Commit the changes.
5. Push to GitHub.
6. Update `.ai/PROJECT_STATE.md`.
7. Update `.ai/HANDOFF.md`.
8. Change `.ai/ACTIVE_AGENT.md`.
9. Commit and push the handoff state.

---

## 6. Receiving Agent Must Verify

Before modifying the repository, the receiving agent must read:

- `AGENTS.md`
- `.ai/ACTIVE_AGENT.md`
- `.ai/PROJECT_STATE.md`
- `.ai/HANDOFF.md`
- `.ai/RULES.md`

Then verify:

```bash
git status
git log -1 --oneline