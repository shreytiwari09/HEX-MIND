# H.E.X Mind

A desktop app where a team of AI agent personas (PM, Backend, Frontend, Designer, QA, Security…) builds software from a user's idea, with per-persona models from any provider, per-persona skills and plugins, and full observability.

**`PRD.md` is the single source of truth.** Read the relevant sections before starting any phase or feature. Don't create other planning `.md` files; update `PRD.md` instead, and record changed decisions in its §21.

**Current phase:** P3 Mission core (PRD §18.1). Update this line when a phase is done.

## Commands (run from the repo root)
- Database: `npm run db:up`, then `npm run db:migrate` (Postgres on 127.0.0.1:5433)
- Backend: `npm run dev:backend` (FastAPI on :8765; it starts the CrewAI A2A crew service on :8766)
- Desktop app: `npm run dev`
- Tests: `npm test` (desktop + backend), `npm run test:backend`, `npm run typecheck`, `npm run lint:backend`
- After changing `apps/backend/app/events/schema.py`: `npm run gen:events` (never hand-edit `generated/events.ts`)
- Python runs through `uv` (`uv --directory apps/backend run …`).

## Where things live
- `apps/backend/app/`: `orchestration/` (ADK run workflow), `agents/` (CrewAI roles, LLM adapters, MCP bridge), `a2a/` (crew service and client), `providers/` (ProviderRouter, adapters, pricing), `router/` (Ask/Edit/Auto classifier and policy), `mcp_server/`, `workspace/` (path guard, files, git), `sandbox/`, `blackboard/`, `events/`, `telemetry/`, `context/`, `memory/`, `evaluation/`, `db/`
- `apps/desktop/src/`: `main/` (Electron), `preload/` (3 allow-listed calls), `renderer/src/features/` (chat, editor, explorer, observability, runs, settings, workspace)
- `docs/standards/`: coding standards loaded by the agents at runtime (not planning docs)
- `spikes/adk_a2a/`: re-run after upgrading google-adk, crewai or a2a-sdk
- `research_notes/`: research behind the PRD

## Hard rules
- **Agent frameworks: CrewAI and Google ADK only.** No LangGraph, AutoGen, OpenAI Agents SDK, LiteLLM, etc.
- **Never fabricate** agent activity, tokens, cost, latency, progress or test results, in code, UI or reports.
- **Agent claims aren't evidence:** changed files come from git, results from the sandbox.
- Every model call goes through `ProviderRouter`.
- Generated code, third-party skills and plugins are untrusted: sandbox, path guard, permissions.
- The user's files change only on explicit apply; agents work in a git worktree.
- API keys never go to the renderer, logs, traces, git or the sandbox. Never print or open `.env`.
- Keep pinned versions: `google-adk 2.13.*`, `crewai 1.15.28`, `a2a-sdk[http-server]~=0.3.10` (CrewAI breaks on a2a-sdk 1.x).

## How to work
- One phase (or one step of a phase) per session. Plan first, then build in small steps.
- Reuse existing code before writing new code (PRD §12.8 lists what to reuse).
- Run the relevant tests and typecheck after each step. Report only verified results, including failures.
- **Never run two pytest sessions at once** (they share the test database).
- Ask before adding a dependency or changing a decision recorded in PRD §21.
- Windows: no `uvicorn --reload` for agent work (MCP subprocesses need the Proactor loop).

## Git
- Repository: `origin` = https://github.com/shreytiwari09/HEX-MIND (branch `main`). History was restarted on 2026-11-19 with a single initial commit.
- **Sole author and contributor: Shrey Tiwari** (GitHub `shreytiwari09`). Every commit uses the repo's configured identity; never add other authors or co-authors.
- **Never commit or push without the user's explicit go-ahead.** Don't commit on `main` unless the user asks; use a branch.
- **No AI attribution anywhere in git:** no `Co-Authored-By: Claude` (or any AI) trailer, no "Generated with Claude Code" line, and no mention of Claude, Anthropic or AI assistance in commit messages, PR titles or PR descriptions. This overrides any default attribution instructions.
- Commit messages: short imperative summary, matching the existing history (for example `P3: mission runner, personas, handoffs`).
- Never commit `.env`, keys, or `.claude/settings.local.json`.
