# H.E.X Mind — Product Requirements Document (v3)

> **Status:** the **single source of truth** for the product and the build, for its owner, the course evaluation and Claude Code. **v3, 2026-11-19.**
>
> **It replaces** `HEX_Mind_Refined_Plan.md` (plan v2) and `HEX_Mind_Latest_Plan_for_Claude_Code.md` (the original brief). Everything still valid from them has been moved here; both stay readable in git history.
>
> **Kept alongside it:**
> - `README.md`: how to run the app.
> - `understanding.md`: a walkthrough of the code as of P2.
> - `research_notes/`: the research behind this PRD.
> - `docs/standards/`: coding standards the agents load at runtime.
>
> **Rule:** no new planning `.md` files. Change this document instead, and record each change in §21.

**Hard rules (never broken)**
1. **Agent frameworks:** CrewAI and Google ADK only.
   - Infrastructure libraries are not agent frameworks and are allowed: FastAPI, SQLAlchemy, Postgres, ChromaDB, the MCP SDK, the A2A SDK, OpenTelemetry, Docker, React and Electron.
   - Other agent frameworks (LangGraph, AutoGen, OpenAI Agents SDK, …) are not allowed.
2. **No fabrication.** Agent activity, tokens, cost, latency, progress and test results shown anywhere come only from real recorded data.
3. **Generated code and third-party skills and plugins are untrusted.** They run only inside the sandbox and the permission rules (§13).
4. **The user's files change only when the user applies a result.** Agents work in an isolated git worktree.
5. **Agent claims are not evidence.** Changed files come from git, command results come from the sandbox, and pass/fail comes from tests that actually ran.
6. **No reuse of subscription logins.** Consumer logins (Claude Pro/Max, ChatGPT, Google accounts) are never used to call models directly. Only API keys are used, plus, as future scope, the official CLIs the user has installed (§10.9).
7. **API keys never reach the renderer, logs or git.** They're stored in the OS keychain locally and in a secret manager in the cloud.

---

## Contents

1. [Summary](#1-summary)
2. [Problem, market and positioning](#2-problem-market-and-positioning)
3. [Users and user stories](#3-users-and-user-stories)
4. [Goals, non-goals and success metrics](#4-goals-non-goals-and-success-metrics)
5. [Concepts and glossary](#5-concepts-and-glossary)
6. [User experience and UI](#6-user-experience-and-ui)
7. [The dev team: personas and runtime agents](#7-the-dev-team-personas-and-runtime-agents)
8. [Mission execution model](#8-mission-execution-model)
9. [Shared state, contracts and handoffs](#9-shared-state-contracts-and-handoffs)
10. [Models, connections and delegation](#10-models-connections-and-delegation)
11. [Skills and plugins](#11-skills-and-plugins)
12. [Technical architecture](#12-technical-architecture)
13. [Safety, security and privacy](#13-safety-security-and-privacy)
14. [Observability](#14-observability)
15. [Evaluation](#15-evaluation)
16. [Course requirements coverage](#16-course-requirements-coverage)
17. [Current state (what is already built)](#17-current-state-what-is-already-built)
18. [Roadmap](#18-roadmap)
19. [Non-functional requirements](#19-non-functional-requirements)
20. [Risks and mitigations](#20-risks-and-mitigations)
21. [Decision log](#21-decision-log)
22. [Open questions](#22-open-questions)
23. [Team and working rules](#23-team-and-working-rules)
24. [References](#24-references)

---

## 1. Summary

**H.E.X Mind (Hivemind Execution X) is a dev team in your hand.** It's a desktop app where a person, **including someone who can't code**, describes an idea for software and a team of specialised AI engineers builds it on their own machine. The team has a PM / Tech Lead, Researcher, Data, Backend, Designer, Frontend, DevOps, QA, Security and Reviewer.

What makes it different:

- **You build your own engineers.** Each team member is a **persona**: a model, skills, plugins and instructions. Users add skills (for example "motion graphics" for the Designer, or a security-audit skill for Security) and plugins through a simple panel. A better model or skill makes that engineer better. H.E.X ships with good built-in personas and skills; advanced users customise them.
- **Bring models from anywhere.** Users connect any provider with their own keys: OpenRouter, NVIDIA, Anthropic, OpenAI, Google, DeepSeek, GLM, Groq, local Ollama or any OpenAI-compatible URL. Each persona uses whichever model fits it best. H.E.X **picks the models automatically and explains why**, and the user can always see and override every choice.
- **It works like a real team, with discipline.**
  - The PM scopes the idea with the user and writes a plan, contracts and a validation contract, which the **user approves**.
  - Features are then built **one at a time**, each by a fresh agent with the right persona, which hands off a structured report.
  - **Validators that are separate from the builders** check every milestone, including a QA agent that **actually uses the app in a browser**.
  - Failures go back to the builder, then escalate to a stronger model, then to the user.
- **Everything is visible.** Mission Control shows progress, the active feature, live worker output, costs and which model did what. Developer mode exposes code, diffs, traces, A2A messages and the audit log.

Under the hood it's built from four runtime agent types on **Google ADK** (orchestration) and **CrewAI** (workers), connected over **A2A**, with tools over **MCP**. It is also a course project graded on 11 requirements (§16), which this design covers.

---

## 2. Problem, market and positioning

### 2.1 The problem
- **Non-coders can describe software but can't build it.** Today's AI coding tools assume a developer who can read diffs, fix builds and choose models.
- **A single agent doing everything degrades on large tasks.** Its context fills up, it grades its own work, and when it fails nobody can see why.
- **Models are scattered across providers.** People hold keys from several vendors. No tool lets them **assign the right model to the right job** and see the cost and reasoning.
- **Skills and plugins are scattered.** Users install skills into many tools and forget what lives where. There's no per-role toolbox.

### 2.2 Comparable products (researched November 2026)

| Product | What it is | How H.E.X differs |
|---|---|---|
| **T3 Code** | Open-source GUI over existing agent CLIs (Claude Code, Codex, Cursor, OpenCode, Antigravity, …), several threads at once | T3 runs agents **side by side**; H.E.X **coordinates** a team on one goal with separate validation. T3 relies on the CLIs' own logins; H.E.X uses the user's API keys with per-role choice |
| **Orchestrator.inc (agent-orchestrator)** | Desktop "fleet" manager: a main agent plans, workers run in parallel (one worktree each) through 35+ agent CLIs, CI and review feedback loops, Kanban (Working / Needs you / In review / Ready) | Parallel-first and aimed at developers. H.E.X is serial-first (§8.3), non-coder-first, has user-built personas with skills, and publishes evaluation numbers |
| **Factory Droid "Missions"** | Orchestrator → milestones → features run one at a time → scrutiny and user-testing validators; shared state in files; logic in skills | Closest in design; H.E.X adopts its proven ideas (§8, §9). H.E.X adds bring-your-own multi-provider models, user-built personas, non-coder UX and an open evaluation |
| **MetaGPT / ChatDev 2.0** | "Software company" agents (PM, architect, engineer); ChatDev 2.0 is a no-code workflow platform | Role play without strong execution-grounded validation; no per-role model or skill control by the user |
| **Claude Code / Codex / OpenCode** | Strong single-agent coding tools (with subagents) | Developer tools. In the future H.E.X can **use** them as workers (§10.9) |

### 2.3 Positioning
- **For the user:** "A dev team in your hand. You choose the engineers, their skills and their models."
- **For the course and portfolio:** "Agent-fleet tools run agents. H.E.X Mind coordinates, **measures and explains** them." It publishes whether a mission-style team beats a single agent, at what cost, and with which model per role (§15).
- **What we don't compete on:** wrapping 35 agent CLIs, a mobile app, cloud VMs per task.

---

## 3. Users and user stories

### 3.1 Users
| User | Description | Main need |
|---|---|---|
| **Builder (primary)** | Has an idea, little or no coding knowledge | Describe → approve → watch → get a working app, safely and within budget |
| **Power user** | Comfortable with models and keys; maybe a developer | Customise personas, skills, plugins and model routing; inspect code |
| **Evaluator** | Professor, team members, researchers | See every course requirement working, with traces and measured results |

### 3.2 User stories (v1)
**Setup**
- U1. As a builder, I can paste **one OpenRouter key**, or several provider keys, and H.E.X shows which models I now have.
- U2. As a builder, I get a **recommended team automatically**, with the reason each model was chosen.
- U3. As a power user, I can add **several keys for one provider**, a **custom OpenAI-compatible URL** (for example NVIDIA) or **local Ollama**.

**Missions**
- U4. As a builder, I describe an idea in plain words, and the PM asks me focused questions to scope it.
- U5. As a builder, I review a **PRD, milestone plan and validation contract** in plain language, edit them, and **approve** before anything is built.
- U6. As a builder, I watch progress in **Mission Control**: milestones, the current feature, live output, costs.
- U7. As a builder, I'm told when the team **needs me** (a decision, a failure it can't fix, a budget limit) and can answer in one click or one sentence.
- U8. As a builder, I can **preview the running app** at any time.
- U9. As a builder, I can **pause**, **redirect** ("also add Google login") or **stop** a mission.
- U10. As a builder, I can **go back to any checkpoint** ("undo the frontend change").
- U11. As a builder, I **apply** the finished result to my project folder, and can **revert** it.
- U12. As a builder, I can ask questions about my project (Ask) or request small follow-up changes (Change) without starting from scratch.

**Personas, skills, plugins, models**
- U13. As a power user, I open a persona (for example the Designer) and see its **model, fallback, budget, skills and plugins**. I can add a skill from a dropdown, a folder or GitHub.
- U14. As a power user, I can **create a new persona** (for example "Data scientist") from a template.
- U15. As any user, I see a **permission label** on each plugin (network, shell, files) and must approve risky ones.
- U16. As any user, I see a **delegation log**: for each feature, which persona and model did it, what it cost, and any fallback, key rotation or escalation, with the reason.
- U17. As any user, I can set a **budget** per mission and per persona, and a **privacy mode** per project.

**Evaluation and transparency**
- U18. As an evaluator, Developer mode shows code, diffs, the trace explorer, the A2A explorer, callbacks, schema checks, the audit log and provenance.
- U19. As an evaluator, I can open an **experiment dashboard** with reproducible benchmark results.

---

## 4. Goals, non-goals and success metrics

### 4.1 Goals (v1, the graded version)
- G1. A builder takes a **simple full-stack web app** from idea to a working, tested, applied result without writing code.
- G2. **Per-persona model delegation** from any provider, automatic by default, transparent and overridable.
- G3. **Per-persona skills and plugins**, managed in the UI.
- G4. **Mission discipline:** scoping → approval → serial features → separate validators → escalation → apply/revert.
- G5. All **11 course requirements** demonstrably met (§16), visible in the app.
- G6. **Measured results** comparing patterns, model delegation and state-sharing (§15).

### 4.2 Non-goals for v1 (later scope, §18.3)
- Driving external agent CLIs (Claude Code, Codex, OpenCode, Antigravity, …) via ACP.
- A Deploy agent that ships the **user's app** to the cloud.
- Mobile or desktop app targets for generated apps.
- Several missions running at once; cloud VM per task.
- A public skill marketplace; automatic skill learning.
- Fine-tuning or training models.

### 4.3 Success metrics
| Metric | Target for v1 demo / evaluation |
|---|---|
| Mission benchmark: apps that pass hidden acceptance tests | Reported honestly per configuration (no target is set before measuring) |
| Builder interventions per mission ("Needs you") | Reported; fewer is better |
| Cost per successful mission, per model preset | Reported |
| Mission team vs single-agent baseline | Measured and reported, including a null result if that's what happens |
| Course requirements met and visible in the app | 11 / 11 |
| Fabricated numbers anywhere in the UI | 0 |

---

## 5. Concepts and glossary

| Term | Meaning |
|---|---|
| **Mission** | One goal from the user ("build a to-do app with login"), carried from scoping to a finished, validated result. |
| **Milestone** | A group of features that ends with validation (for example "M2 Backend API"). |
| **Feature** | The unit of work one worker builds in one go, assigned to one persona. |
| **Persona** | A team member as the user sees it (for example Designer). It's a **profile**: name, kind, model assignment, skills, plugins, instructions, budget. Data, not code. |
| **Runtime agent type** | One of the 4 mechanisms that actually run (§7.2): Orchestrator/PM, Worker, Validator, Research. Every persona runs on one of them. |
| **Agent instance** | A fresh agent created for one job from a persona. It has its own context and is discarded after its handoff. |
| **Subagent** | A read-only helper an agent starts (research or review). It can read and report, but not edit. |
| **Skill** | A folder with a `SKILL.md` (instructions, examples) that an agent loads **when it needs it**. |
| **Plugin** | An **MCP server** that gives a persona extra tools (for example Figma import, Playwright). It has permission labels. |
| **Connection** | A model provider the user has added: provider type, base URL, one or more keys. |
| **Model assignment** | A persona's primary model, fallback chain and escalation model. |
| **Preset** | A ready-made assignment policy: Auto (Balanced), Best quality, Cheapest, Private (local only). |
| **Delegation log** | A record of which persona and model handled what, at what cost, and why (including fallback, key rotation and escalation). |
| **Contracts** | Files the PM writes before coding: `prd.md`, `schema.sql`, `openapi.yaml`, `design-tokens.json`. |
| **Validation contract** | `validation-contract.md`: checkable acceptance criteria for each feature, approved by the user. |
| **Run contract** | `.hex/project.json` plus `.hex/Dockerfile`: how to install, build, test, typecheck, lint and start this project. Validators and the preview read it. |
| **Handoff** | The structured report each worker files when it finishes (§9.4). |
| **Checkpoint** | A git commit on the mission branch after each feature. The user can restore any checkpoint. |
| **Needs you** | A state where the mission waits for a user decision. |
| **Scrutiny validator** | Runs tests, typecheck and lint, plus review subagents per feature. |
| **User-testing validator** | Uses the running app in a browser against the validation contract. |
| **Stack pack** | Optional curated bundle for a popular stack: skills, Dockerfile template, run contract template, benchmark tasks. |
| **Developer mode** | The power-user and evaluator view: editor, diffs, observability and A2A explorer. |

---

## 6. User experience and UI

### 6.1 Design direction (from the original brief, still valid)
- A polished, modern desktop tool: not a generic admin dashboard, a marketing page or a game.
- **Dark-first**, with an optional light theme.
  - Layered charcoal/slate surfaces, subtle borders, one primary accent (indigo or blue-violet).
  - Semantic colours used sparingly: green = success, amber = waiting or warning, red = failure or destructive, blue/violet = active work.
- 4/8 px spacing; restrained corner radii; a readable UI font plus a monospace font for code and telemetry; **Lucide** icons, no emoji as icons.
- Avoid gradients, glassmorphism, glows, oversized cards and decorative motion. Respect reduced-motion settings.
- Keyboard navigation, visible focus, tooltips on icon-only buttons, readable contrast.
- Loading, empty, disconnected, error, success and confirmation states are all designed deliberately.
- **Never display fabricated progress, status, tokens, cost or latency.**
- Plain language in the builder views ("QA's tests: 11 of 12 passed"). Technical detail lives in Developer mode.

### 6.2 Main flows

**F1. First run: connect models**
1. Welcome → "Connect your models".
2. Options:
   - **"Paste one OpenRouter key"** (simplest)
   - **"Add provider keys"** (Anthropic, OpenAI, Google, NVIDIA, DeepSeek, GLM, Groq, custom URL)
   - **"Use local models"** (Ollama detected)
3. Each key is tested, and the models it reaches are listed.
4. H.E.X proposes a **team** with a model for each persona and a one-line reason ("Security → Claude Opus 5.5: strongest reasoning model among your connections"). The user accepts or adjusts.

**F2. New mission**
1. "What do you want to build?" → free text, plus an optional folder for an existing project.
2. **Scoping chat with the PM.** It asks a few focused questions (users, must-have features, look and feel, login, data), and the Research subagents look things up.
3. **Plan review screen:**
   - a plain-language PRD;
   - milestones and features, each with its persona;
   - the **validation contract** ("A user can add a to-do and still see it after reloading");
   - an estimated cost range;
   - the team and its models.

   The user can edit any part, then **Approve**.
4. **Mission Control** opens and the mission runs (F3).

**F3. Running mission**
- Features run one after another; Mission Control shows each step.
- After each milestone, validators run, and QA tests the app in a browser.
- A failure goes back to the same persona. After repeated failure the model escalates, and then the mission moves to **Needs you** with a short summary and options.
- The user can **Pause**, **Redirect** (a new instruction is added to the plan by the PM, and the user approves the change), or **Stop** at any time.
- A **Preview** button shows the running app.

**F4. Finish**
- A summary of what was built, the validator results and the cost.
- The user can **apply** the result to their project folder, **keep it on the mission branch**, or **discard** it.
- **Revert** is available afterwards.

**F5. Follow-ups (persistent conversation per project)**
- **Ask:** "How does login work?" The answer comes from the project's files, and nothing changes.
- **Change:** "Make the login page dark." The Router sizes it. A small change becomes a one-feature mini-mission with only the scrutiny validator; a larger one gets full scoping.
- **Auto:** the Router decides between Ask, Change and New mission, and shows its confidence. A low-confidence decision leads to a clarifying question.
- **Context:** the workspace files are always the source of truth. The conversation summary and handoffs supplement them.

### 6.3 Screens

**S1. Mission Control (main screen)**
```
┌ H.E.X ─────────────────────────────────────────────────────────────────────┐
│ MISSIONS      │ ● RUNNING  ███████░░░░░░  Milestone 2/4 · Feature 5/11      │
│ ● Todo app    │ 56m · In 324k · Cached 16.8M · Out 111k · $2.10 / $5.00     │
│ ○ Portfolio   ├────────────────────────────────┬───────────────────────────┤
│ + New mission │ ACTIVE FEATURE                 │ MILESTONES / FEATURES     │
│               │ api-auth-routes                │ ✓ M1 Foundation           │
│ TEAM          │ Persona: Backend · Sonnet 5.5  │ ● M2 Backend API          │
│ PM     Fable  │ Skills: fastapi, auth-security │   ✓ todo-crud             │
│ Backend Son.  │ Preconditions ✓ schema.sql     │   ● api-auth-routes       │
│ Front. Gemini │ Expected: tests + typecheck    │   ○ scrutiny validator    │
│ QA     Haiku  │ pass; contract VC-2.3          │   ○ user-testing validator│
│ Sec.   Opus   │                                │ ○ M3 Frontend             │
│               ├────────────────────────────────┤ PROGRESS LOG              │
│ MODELS & KEYS │ LIVE WORKER OUTPUT             │ 2m  todo-crud ✓ handoff   │
│ SKILLS        │ > writing routes/auth.ts…      │ 9m  M1 validated ✓        │
│ SETTINGS      │ > vitest: 14 passed            │                           │
├───────────────┴────────────────────────────────┴───────────────────────────┤
│ [Pause] [Redirect] [Needs you (1)] [Preview] [Checkpoints] [Costs] [Dev ▸] │
└────────────────────────────────────────────────────────────────────────────┘
```
- **Left:** missions list (like T3 threads), the team with each persona's current model, Models & Keys, Skills, Settings.
- **Centre:** the active feature (persona, model, skills, preconditions, expected behaviour, description), then live worker output streamed over WebSocket.
- **Right:** the milestone and feature tree with status, then a progress log.
- **Header:** state, progress, elapsed time, input / cached / output tokens, cost vs budget. All of these are real numbers.

**S2. Persona panel (opens from the team list)**
```
┌ Designer ───────────────────────────────────────────────┐
│ Model     [Auto: Gemini 3.5 Pro ▾]                       │
│           "best design-capable model you have connected" │
│ Fallback  [OpenRouter · …        ▾]  Escalate [Opus ▾]   │
│ Budget    [$1.00 per mission]                            │
│ Skills                       Plugins                     │
│ ✓ UI/UX Pro       built-in   ✓ Figma import  network ⚠   │
│ ✓ Accessibility   built-in   + Add plugin ▾              │
│ ✓ Motion graphics added                                  │
│ + Add skill ▾ (built-in · folder · GitHub URL)           │
│ Instructions [edit]  ·  Recent work · Tokens · Cost      │
└──────────────────────────────────────────────────────────┘
```

**S3. Models & Keys**
- **Connections list:** provider, base URL, number of keys, status, data-policy badge (§13.5).
- **Model catalog** across all connections: price, context size, tool-calling support, tier.
- **Presets** and the **team table** (persona → model, set by "Auto" or "You", fallback, escalation).

**S4. Plan review / approval:** PRD, milestones, features, validation contract and cost estimate, all editable; Approve / Ask the PM to change.

**S5. Needs you:** a queue of decisions. Each shows a plain summary, the evidence (failing check, screenshot from QA), and options (retry with a stronger model, change the requirement, skip the feature, take over in Developer mode).

**S6. Preview:** an embedded browser pane showing the app as started from the run contract.

**S7. Checkpoints:** a timeline of features (one commit each) with "Restore to here" (code only, or code and plan).

**S8. Costs and delegation:** spend per persona, per model and per milestone; the delegation log with reasons.

**S9. Developer mode** (the current IDE, kept):
- Monaco editor and file tree; diff view per feature or checkpoint.
- Observability tabs: Blackboard/mission board, agent grid, callback stream, schema checks, pattern topology, A2A explorer; later trace explorer, metrics, audit log and provenance (§14).
- Bottom panel: Problems, Tasks, Agent Events, Logs.

**S10. Settings:** privacy mode, budgets, sandbox status (Docker), backend status, theme, reduced motion, diagnostics.

---

## 7. The dev team: personas and runtime agents

### 7.1 Two layers
1. **What the user sees: personas.** A familiar dev team that non-coders can relate to. Each persona is a **profile stored as data** (§11.1).
2. **What actually runs: 4 runtime agent types.** Each job creates a **new, separate agent instance** from the right persona. That instance loads **only that persona's** model, skills, plugins and instructions, does the job, files a handoff, and is discarded.

Personas don't share a context, and no agent juggles roles. They share the **same code** underneath (one worker loop, one validator loop), which is what keeps the build feasible.

### 7.2 Runtime agent types
| Type | Framework | Runs at once | Writes code? | Personas |
|---|---|---|---|---|
| **Orchestrator / PM** | ADK `LlmAgent` + deterministic ADK mission runner | 1 | No (writes plan and contract files) | PM / Tech Lead |
| **Worker** | CrewAI crew served over A2A | **1 at a time** | Yes, in the mission worktree | Data, Backend, Designer, Frontend, DevOps |
| **Validator** | ADK `LlmAgent` (Reviewer, Security) and CrewAI (QA) | Several in parallel | No (QA may only write test files to a separate tests folder; see §8.5) | Code Reviewer, Security, QA |
| **Research** | CrewAI or ADK, read-only | Several in parallel | No | Researcher (also started as subagents by any agent) |

The existing **Router** (ADK, Pydantic output plus a deterministic policy) still classifies each chat message (Ask / Change / New mission) and its complexity.

### 7.3 v1 personas (built in)
| Persona | Type | Job | Default model tier | Built-in skills (v1) | Built-in plugins |
|---|---|---|---|---|---|
| **PM / Tech Lead** | Orchestrator | Scoping chat; PRD; architecture and stack choice; contracts (schema, API spec); milestones and features; validation contract; re-planning; escalation decisions | Top reasoning, long context | `scoping-interview`, `prd-writing`, `feature-decomposition`, `api-contract-design`, `failure-handling`, `escalation-policy` | — |
| **Researcher** | Research | Reads the codebase, docs and APIs; answers specific questions with sources | Cheap / fast | `codebase-exploration`, `doc-research` | Web fetch (read-only, network ⚠) |
| **Data engineer** | Worker | Schema, migrations, seed data | Mid | `relational-schema-design`, `migrations` | — |
| **Backend engineer** | Worker | API that implements the contract, plus unit tests | Strong coding | `rest-api`, `auth-basics`, `testing-backend` | — |
| **Designer** | Worker | Design tokens, screen layouts, visual polish | Strong at UI | `ui-ux-pro`, `accessibility`, `design-tokens` | (optional) Figma import |
| **Frontend engineer** | Worker | UI against the API contract and design tokens | Strong coding | `react-ui`, `state-and-data-fetching`, `testing-frontend` | — |
| **DevOps (local)** | Worker | Project scaffold, run contract, Dockerfile, run scripts, so the app runs for preview and QA | Cheap | `run-contract`, `dockerfile-basics` | — |
| **QA engineer** | Validator | Writes acceptance tests **from the validation contract, independently of the builders**; then **uses the app in a browser** against the contract | Mid | `acceptance-testing`, `browser-testing` | Playwright (browser) |
| **Security reviewer** | Validator | Reviews each milestone's diff and dependencies for security problems | Top reasoning | `security-audit` (for example a Cloudflare-style audit skill), `secrets-hygiene` | — |
| **Code reviewer** | Validator | Runs the scrutiny checks (tests, typecheck, lint) and starts review subagents per feature; combines the findings | Strong | `code-review`, `contract-conformance` | — |

The "default model tier" is a requirement used by Auto assignment (§10.4), not a fixed model.

Users can **create personas** from a template (for example "Data scientist", "Docs writer"). They choose a type, write instructions, and pick skills, plugins and a model.

### 7.4 Subagents
- Any agent can start **read-only subagents**. For example: Backend → "Research: how does this library handle sessions?"; Code Reviewer → one review subagent per completed feature; PM → research during scoping.
- Subagents **can't edit files**. They return a short structured report.
- They run in parallel, count against the mission budget, and appear in the delegation log.

---

## 8. Mission execution model

### 8.1 Mission lifecycle
```
draft → scoping → awaiting_approval → running ⇄ paused
                                        │  ↘ needs_user ↗
                                        ↓
                                    completed → applied / kept / discarded
         (any state) → cancelled          running → failed (unrecoverable, with report)
```

### 8.2 Typical milestone plan (example: a to-do app)
```
M0 Scoping     PM chat → prd.md + contracts + validation-contract.md → USER APPROVES
M1 Foundation  DevOps scaffold + run contract → Data schema + migrations      → validators
M2 Backend     Backend features, one at a time                              → validators
M3 Frontend    Designer tokens and layouts → Frontend features               → validators + QA user-testing
M4 Hardening   Full security review, end-to-end QA, packaging               → done
```
The PM decides the actual milestones for each mission. Small "Change" requests become a single-milestone mission.

### 8.3 Serial building, parallel checking
- **Features run one at a time.** Each worker starts from the codebase the previous one committed to git.
- **Parallel only for work that can't conflict:** research, codebase exploration, reading docs, and validator reviews.
- **Why:** parallel builders conflict, duplicate work, drift apart architecturally and waste tokens on merges. This comes from Factory Missions and the MAST failure study (§24). It's slower on paper, but correctness compounds over long runs.
- **Parallel feature building is kept as an experimental pattern** (P-parallel) for the evaluation (§15), not as the default.

### 8.4 One feature, step by step
1. **The orchestrator picks the next feature** whose preconditions are met (from `features.json`).
2. **It builds the agent instance:** `build_agent(persona, feature, mission_context)` (§12.3).
3. **The context the worker gets:**
   - its persona instructions and its skill index;
   - the feature spec (description, preconditions, expected behaviour, contract references);
   - the relevant contracts;
   - the **handoffs** of earlier features, not their chat history;
   - a ranked **repo map** of about 1k tokens;
   - `AGENTS.md`, if present.
4. **It works in the worktree** through MCP tools only. Its commands run in the sandbox.
5. **It finishes with a Handoff** (§9.4).
   - The orchestrator fills in `commands` from the sandbox log and `files_changed` from `git diff`.
   - Empty changes are rejected, and so are checks that ran zero tests.
6. **Checkpoint:** a git commit on the mission branch (`hex/mission-<id>`), named after the feature id.
7. **The quick check** from the run contract (for example typecheck plus unit tests) runs right away. On failure, the feature retries (§8.6) before moving on.

### 8.5 Validation at the end of each milestone
Validators run **in parallel**, read-only, on the milestone's diff:
- **Scrutiny validator (Code reviewer):**
  - runs `test`, `typecheck` and `lint` from the run contract;
  - starts one **review subagent per feature** (contract conformance, code quality);
  - combines everything into a scrutiny report.
- **Security validator:** reviews the diff, dependencies and configuration with its security skills.
- **User-testing validator (QA):**
  - **Before the milestone:** writes acceptance tests from the validation contract, independently of the builders. The tests are committed to `tests/acceptance/` by QA only, and builders can't edit them.
  - **At the end:** starts the app (run contract `start`) in the sandbox and drives it with Playwright against the contract. It records its steps and screenshots as evidence.
- **Output:** each validator returns a `ValidatorReport` (§9.5). The milestone passes only if every required validator passes.

### 8.6 Failure handling and escalation ladder
For a failing feature or validator finding:
1. **Retry 1:** the same persona and model, given the exact findings (failing test output, file and line).
2. **Retry 2:** escalate to the persona's **escalation model**, or one tier up under Auto.
3. **Re-plan:** the PM adjusts the feature once (split it, clarify it or change the approach). A changed acceptance criterion needs user approval.
4. **Needs you:** a plain summary, the evidence, and options (retry with a model the user picks, change the requirement, skip, take over in Developer mode).

Notes:
- **Budget:** at 80% of the budget a warning is shown; at 100% the mission **pauses** in Needs you.
- **Provider errors** (rate limit, quota, outage) are handled by the provider layer (§10.6) and don't count as attempts.
- These rules (how many retries, when to re-plan, when to escalate) live in **orchestration skills** (§11.5), within hard limits set in code.

### 8.7 Pause, redirect, resume and long runs
- **Pause** finishes the current step and stops. **Stop** cancels.
- **Redirect:** the user's instruction goes to the PM, which updates the plan, features and contract. Changes are shown as a diff, and the mission resumes after the user approves.
- **Runs survive the UI being closed.** The backend is a separate process. All mission state is in Postgres and the mission folder, and ADK sessions are stored in the database. After a restart, the mission resumes from the last checkpoint.
- **Notifications:** a desktop notification on Needs you, a finished milestone, or mission completion.

### 8.8 Applying, discarding and reverting
- **New project:** H.E.X creates the project folder. The mission branch is merged into `main` on Apply.
- **Existing project:** the worktree is created from a snapshot that includes uncommitted and untracked files. On Apply, the changes are written to the user's working copy (checking for stale files), and the result is recorded as a commit or as a patch for a non-git folder.
- **Revert:** restore to the pre-apply state.
- **Restore checkpoint:** reset the mission branch to any feature commit; the plan state can be restored too.
- **Mission files:** `.hex/` files are applied too by default, so the project keeps its own documentation and run contract. This can be switched off in Settings.

---

## 9. Shared state, contracts and handoffs

### 9.1 Two stores, one job each
- **Mission folder (in the worktree, versioned by git):** what **agents** read and write. Plain text, inspectable, checkpointed with the code.
- **Postgres:** what the **system** needs: mission, feature and task state for scheduling, the event log, `llm_calls`, the delegation log, evaluations, and the audit log. It's the source for the UI and for resuming.

The orchestrator keeps them in sync: `features.json` is written from the database state, and handoffs are written to both.

### 9.2 Mission folder layout
```
.hex/
  project.json              run contract
  Dockerfile                sandbox image for this project
  mission/
    prd.md                  plain-language product requirements (user-approved)
    features.json           milestones → features, status, persona, preconditions, expected behaviour
    validation-contract.md  acceptance criteria per feature (user-approved)
    handoffs.jsonl          one Handoff per worker run
    validator-reports/      one JSON report per validator per milestone
    contracts/
      schema.sql
      openapi.yaml
      design-tokens.json
    skills.json             skills assigned to personas for this mission (PM additions included)
```

### 9.3 `features.json` (shape)
```json
{
  "mission_id": "m_7f3a",
  "milestones": [
    {
      "id": "m2-backend",
      "title": "Backend API",
      "status": "active",
      "validators": ["code-reviewer", "security"],
      "features": [
        {
          "id": "api-auth-routes",
          "title": "Sign-up, login and logout endpoints",
          "persona": "backend",
          "status": "in_progress",
          "preconditions": ["schema.sql has users table"],
          "expected_behavior": ["POST /auth/signup creates a user", "tests + typecheck pass"],
          "contract_refs": ["openapi.yaml#/paths/~1auth~1signup", "VC-2.3"],
          "extra_skills": [],
          "attempts": 1,
          "commit": null
        }
      ]
    }
  ]
}
```

### 9.4 Handoff (Pydantic, also a line in `handoffs.jsonl`)
```python
class CommandResult(BaseModel):
    command: str
    exit_code: int
    duration_s: float
    summary: str                  # trimmed output

class Handoff(BaseModel):
    feature_id: str
    persona_id: str
    model_used: str               # from the provider layer, not the agent
    implemented: list[str]        # agent-reported
    left_undone: list[str]        # agent-reported
    issues_found: list[str]       # agent-reported
    procedures_followed: bool     # agent-reported, checked by validators
    notes_for_next: list[str]     # agent-reported
    commands: list[CommandResult] # filled from sandbox logs
    files_changed: list[str]      # filled from git diff
    tokens_in: int; tokens_out: int; cost_usd: float   # from llm_calls
```

### 9.5 Validator report
```python
class Finding(BaseModel):
    feature_id: str | None
    file: str | None
    line: int | None
    severity: Literal["info", "minor", "major", "critical"]
    message: str
    contract_ref: str | None      # e.g. "VC-2.3"
    evidence: str | None          # e.g. test output, screenshot path

class ValidatorReport(BaseModel):
    validator: str                # persona id
    milestone_id: str
    verdict: Literal["pass", "fail", "needs_user"]
    findings: list[Finding]
    commands: list[CommandResult] # from the sandbox
```

### 9.6 Run contract `.hex/project.json`
```json
{
  "stack": "react-vite + node-hono + sqlite",
  "dockerfile": ".hex/Dockerfile",
  "install":   "npm ci",
  "build":     "npm run build",
  "test":      "npm test",
  "typecheck": "npx tsc --noEmit",
  "lint":      "npx eslint .",
  "start":     "npm run dev -- --host 0.0.0.0",
  "port":      5173,
  "healthcheck": "/",
  "network": { "install": "allowlist", "test": "none", "start": "none" }
}
```
- **Any stack is allowed.** The PM chooses it during scoping, and DevOps writes the run contract and Dockerfile. Validators, the preview and QA read their commands only from this file; nothing is hardcoded per stack.
- **Stack packs** (§11.6) give popular stacks tested templates and skills. Projects that use one are more reliable.

### 9.7 Validation contract (example excerpt)
```markdown
## VC-2.3 Sign-up
- Given no account, when a user signs up with email + password, then they are logged in.   [api test, browser]
- Signing up twice with the same email shows "account exists".                              [api test]
- Passwords are never stored in plain text.                                                   [security review]
```
Each criterion names **how it's checked**: `api test`, `unit test`, `browser`, `typecheck` or `security review`.

### 9.8 Coordination backends (course requirement 1)
The same mission can run with either of two backends:

| | **Blackboard** (default) | **Messaging** |
|---|---|---|
| Shared state | Postgres mission, feature and task tables + mission folder, readable by every agent through MCP tools | None. Agents only get what the orchestrator sends in the A2A message |
| Hand-off | Orchestrator posts a feature; the worker claims it atomically (`FOR UPDATE SKIP LOCKED`, lease with heartbeat) | Orchestrator sends an A2A `message/send` with the feature and its full context; the worker replies with an artifact |
| Dependencies | Database query on preconditions | Orchestrator orders messages by dependency |
| Recovery | Lease reaper re-queues the work | Timeout + resend with an idempotency key |
| Visibility | Any agent can read the board and handoffs | Only the orchestrator has the full picture |

The two are compared in experiment E4 (§15).

*Built in P7 (D58): choose the backend when a mission is started; with messaging the worker's tools and prompt contain no board and its criteria travel in the request.*

---

## 10. Models, connections and delegation

### 10.1 How users get model access
| Route | v1? | Notes |
|---|---|---|
| **OpenRouter key** | ✅ | One key, hundreds of models (Claude, GPT, Gemini, DeepSeek, GLM, Kimi…). Easiest onboarding. Supports a zero-data-retention filter |
| **Direct provider keys** | ✅ | Anthropic (native adapter), OpenAI, Google Gemini, NVIDIA (`https://integrate.api.nvidia.com/v1`), DeepSeek, Zhipu GLM, Moonshot, Groq, Mistral, xAI, … Most use the OpenAI-compatible format |
| **Custom OpenAI-compatible URL** | ✅ | Any endpoint that speaks `/v1/chat/completions` |
| **Local models** | ✅ | Ollama (existing adapter), LM Studio (OpenAI-compatible) |
| **Subscriptions via official CLIs** (Claude Code, Codex, Gemini CLI, OpenCode…) | Future (§10.9) | Never use consumer logins directly; launch the user's own installed CLI through ACP |

### 10.2 Connections and keys
- **Connection** = provider type + base URL + **one or more keys** + optional extra headers. When it's added, H.E.X tests it and lists the models it can reach.
- **Key storage:** keys are stored in the **OS keychain** (macOS Keychain, Windows Credential Manager) through the backend; this needs the `keyring` dependency (approval required). Postgres stores only a reference. Keys never go to the renderer, logs, traces or git. In the cloud they live in **Secret Manager**.
- **Key pools:** when a key hits its rate limit or quota (HTTP 429 or a quota error), it cools down (honouring `Retry-After`) and the next key in the pool is used. Every rotation is logged.
  - **Caution shown in the UI:** rate limits are often **per account or organisation**, so two keys from one account usually share a limit. Rotating across accounts just to get around limits may break a provider's terms. **Falling back to another provider or model is the default**; key rotation applies only to keys the user explicitly adds to a pool.

### 10.3 Model catalog
- **Sources:**
  - the **models.dev** open catalog (prices, context window, capabilities);
  - each connection's live model list (for example OpenRouter `/models`);
  - a curated `model_profiles.yaml` shipped with H.E.X: quality tier per capability (reasoning, coding, UI/design, tool use), the preferred **edit format**, known quirks (for example Gemini thought signatures), and tool-calling reliability.
- **Updates:** the catalog is refreshed in the background and cached for offline use. Evaluation results (§15) feed back into the curated profiles.

### 10.4 Automatic delegation (users aren't expected to choose)
- **Role requirements** (`role_requirements.yaml`). Examples:
  - **PM:** top reasoning, ≥128k context, reliable tool use.
  - **Security:** top reasoning.
  - **Backend and Frontend:** strong coding, reliable tool use, cost-efficient.
  - **Designer:** strong UI.
  - **QA:** mid, tool use.
  - **Research and DevOps:** cheap and fast.
- **Assigner:** for each persona, it picks the best model **the user can actually reach** that meets the requirement, according to the active preset. It returns a one-line **reason**, which is shown in the UI.
- **Presets:**
  - **Auto (Balanced):** strong where it matters (PM, Security, escalations), cheaper elsewhere.
  - **Best quality:** top tier everywhere.
  - **Cheapest:** the lowest-cost model that meets each minimum requirement.
  - **Private:** local models only.
- **Example result** for a user with Anthropic + NVIDIA + OpenRouter:
  - PM → Fable 5.2
  - Backend → Sonnet 5.5
  - Security → Opus 5.5
  - Designer → a Gemini model via OpenRouter
  - Research → a DeepSeek model via NVIDIA
  - QA → Haiku 5.5
  - Escalation → Fable 5.2
- **Overrides:** any persona can be set by the user. The UI shows "Set by: You" or "Set by: Auto (reason)".

### 10.5 Escalation
- Every persona has an **escalation model**: one tier up under Auto, or set by the user.
- It's used by the escalation ladder (§8.6), for example: "hard bugs go to Fable".
- **Cascade principle:** start with the assigned model; escalate only when tests or validators fail, not by default.

### 10.6 Fallback and provider errors (existing `ProviderRouter`, extended)
- **Order of handling:**
  1. retry with backoff (honour `Retry-After`);
  2. rotate the key within the pool;
  3. fall back along the persona's fallback chain;
  4. move the mission to Needs you.
- **Cooldown** per key and per provider after quota or auth errors.
- **Logging:** every attempt is a row in `llm_calls`, and every fallback, rotation and escalation is an event in the delegation log.
- **Pre-throttling:** a per-provider token bucket that reads rate-limit headers, to avoid storms of 429 errors.

### 10.7 Context, compaction and switching models
- **Provider-neutral history:** conversations are stored in H.E.X's own message format, so any model can continue them.
- **Switching keys on the same model** needs no compaction.
- **Switching to a model with a smaller context window, or exceeding the budget:** a **condenser** keeps the start and the recent tail of the conversation verbatim and summarises the middle with a cheap model. It records which events were dropped (the OpenHands-style design).
- **Workers rarely need compaction.** They're short-lived and start from handoffs, not chat history.
- **Redaction** (`context/redact.py`) always runs before content leaves the machine.

### 10.8 Edit formats per model
Models differ in how reliably they follow an edit format. Even frontier models produce malformed edits up to about 12% of the time on Aider's benchmark. So:
- **Formats:** search/replace blocks (the default), a fenced variant (often better for Gemini), or whole-file output (small or local models).
- **Choice:** the preferred format per model comes from `model_profiles.yaml`.
- **Applier:** a tolerant applier with fuzzy matching returns precise errors to the model. Lazy placeholders ("… rest unchanged") are rejected.
- **Metric:** **edit-format compliance** is recorded per model and shown in the evaluation.

### 10.9 Future: external agents as workers (ACP)
- **What:** let a persona be backed by an external agent CLI (Claude Code, Codex, Gemini CLI, OpenCode; Antigravity if it offers a headless mode). The CLI uses **its own login**, which is the legitimate way to use a subscription.
- **How:** an A2A wrapper that speaks **ACP (Agent Client Protocol)** to the CLI over stdio. It gets one worktree per job and the same feature/handoff/validator cycle.
- **Course constraint:** H.E.X's own agents stay CrewAI and ADK only. External CLIs are optional external workers, **off in the graded demo and evaluation**.

---

## 11. Skills and plugins

### 11.1 Persona definition (data)
```yaml
# personas/designer.yaml  (built-in; user personas are stored in Postgres)
id: designer
name: Designer
kind: worker                 # orchestrator | worker | validator | research
model:
  mode: auto                 # auto | manual
  primary: null              # e.g. openrouter:google/gemini-3.5-pro when manual
  fallback: []
  escalate: null
skills:  [ui-ux-pro, accessibility, design-tokens]
plugins: []
instructions: |
  You are the product designer on this team. You own design tokens and screen layouts …
budget_usd: 1.00
```
```python
class Persona(BaseModel):
    id: str
    name: str
    kind: Literal["orchestrator", "worker", "validator", "research"]
    model: ModelAssignment
    skills: list[str]
    plugins: list[str]
    instructions: str
    budget_usd: float | None = None
    version: int                       # every edit creates a new version (provenance)
```

### 11.2 Skill format
- Uses the open **Agent Skills** format: a folder with `SKILL.md` (front matter `name` and `description`, then instructions) plus optional files (examples, templates, scripts).
- **Sources:** built-in (shipped with H.E.X), a user folder, a GitHub URL (fetched, pinned to a commit, and shown to the user before it's enabled), and skills the PM adds for a mission.
- **Versioning:** each skill is hashed. The version used is recorded on every model call (provenance, §14).

### 11.3 Loading skills on demand (keeps context small)
- The agent's system prompt contains **only the skill index**: one line per skill ("motion-graphics: add animations and transitions to React UIs").
- The agent calls the MCP tool **`load_skill(name)`** to receive the full instructions when it needs them.
- **Why:** a persona with 10 skills costs about 10 lines of context. Research shows that **carefully selected context helps and dumping everything in hurts**. That's why skills are scoped per persona, and not every skill goes to every agent.

### 11.4 Assigning skills
- **User:** in the persona panel (S2), via a dropdown, folder or URL.
- **PM, per mission:** for example "this project uses Stripe → add `stripe-payments` to Backend for this mission". These additions are listed in the plan review and stored in `.hex/mission/skills.json`.
- **Feature-level:** `features.json` → `extra_skills` for one feature.

### 11.5 Orchestration logic in skills ("designed not to be made obsolete")
- **Code keeps the fixed skeleton:** mission state machine, safety rules, sandbox, validation gates, hard limits (maximum retries, budgets), event log. These are **never** left to a prompt.
- **PM skills hold the strategy:** how to decompose features, how to handle failures, when to re-plan, when to escalate, and how to size milestones.
- **Why:** when a better model arrives, the system improves without code changes, and these skills double as **prompt variants** for course requirement 8 (§15, E5).

### 11.6 Stack packs
- **Contents:** built-in skills + Dockerfile template + run contract template + benchmark tasks for one stack.
- **v1 ships one pack:** **React + Vite + TypeScript frontend, Node (Hono) backend, SQLite, Vitest + Playwright.** It matches the existing Node 22 sandbox image and to-do benchmark.
- **Later:** Python/FastAPI, Next.js, and others. Users can add packs too.

### 11.7 Plugins (MCP servers)
- A plugin is an **MCP server** (stdio or HTTP) attached to specific personas. Its tools are given **only** to those personas' agents.
- **Permission labels**, derived from its declared tools and configuration, and shown in the UI: `reads files`, `writes files`, `runs commands`, `network`, `secrets`.
- **Approval:**
  - risky permissions (network + writes, shell, secrets) need **explicit approval** when the plugin is added;
  - actions that change state outside the sandbox need **approval at the moment they happen**.
- Plugins run sandboxed where possible; network access goes through an allowlist.
- **Built-in v1 plugins:** the H.E.X workspace MCP server (§12.6); Playwright (QA); read-only web fetch (Research).

### 11.8 Learning loop (later scope)
- After a mission, **verified** lessons (only from features whose tests passed) are proposed as skill edits or new skills: "New task → Execute → Observe → Learn → Encode skill".
- The user approves each proposal.
- Raw trajectories are never stored as memory; the research shows they don't help.

---

## 12. Technical architecture

### 12.1 System diagram
```
┌──────────────────────────── Desktop app (Electron + React + TS) ─────────────────────────────┐
│ Mission Control · Plan review · Persona panel · Models & Keys · Needs you · Preview ·         │
│ Checkpoints · Costs · Developer mode (Monaco, diff, Observability, A2A explorer)               │
└──────────────────────────────▲──────────────────────────── REST + WebSocket (token) ─────────┘
                               │
┌──────────────────────────────┴────────────── FastAPI backend (:8765) ─────────────────────────┐
│ ADK layer: RouterAgent → policy → Answer | Clarify | Mission                                   │
│            PM LlmAgent (scoping, plan, contracts) · MissionRunner (deterministic loop)         │
│            Validators: Reviewer, Security (LlmAgent)                                           │
│ Registries: Personas · Skills · Plugins · Connections · Model catalog · Assigner               │
│ ProviderRouter (key pools, fallback, escalation, budgets, cost) ◄─ HexAdkLlm / HexLLM          │
│ Coordination backend: Blackboard | Messaging · Guardrails · TelemetryHub (events, OTel, audit) │
└──────┬─────────────────────────────┬───────────────────────────┬──────────────────────────────┘
       │ A2A (JSON-RPC, traceparent) │ MCP (stdio)               │
┌──────▼──────────────────────┐ ┌────▼──────────────────────┐ ┌──▼──────────────────────────────┐
│ CrewAI crew service (:8766) │ │ H.E.X MCP server (16 tools)│ │ Postgres · ChromaDB ·           │
│ build_agent(persona) →      │ │ + user plugins (MCP)       │ │ Docker sandbox (per-project     │
│ Worker / QA / Research crews│ │ + Playwright (QA)          │ │ image from .hex/Dockerfile) ·   │
│ (HexLLM → ProviderRouter)   │ └───────────────────────────┘ │ git worktrees · OS keychain     │
└─────────────────────────────┘                               └─────────────────────────────────┘
```

### 12.2 Which framework does what (course requirement 7)
| Concern | Framework | Why |
|---|---|---|
| Routing, conversation, PM, mission runner, Reviewer and Security validators | **ADK** | Orchestration, Pydantic `output_schema`, callbacks, OpenTelemetry, database sessions |
| Worker personas, QA, Research crews | **CrewAI** (served over A2A) | Role-based crews; a real cross-framework, cross-process boundary |
| Every model call | `ProviderRouter` via `HexAdkLlm` (ADK `BaseLlm`) and `HexLLM` (CrewAI `BaseLLM`) | One place for keys, fallback, cost and logging |

**No LiteLLM:** the existing OpenAI-compatible adapter covers most providers, a native Anthropic adapter is added, and our own router already provides the routing policy. This keeps dependencies and behaviour under our control (§21).

### 12.3 Core code changes (from today's code)
| Today | Change |
|---|---|
| `agents/roles.py`: fixed `planner()` / `coder()` functions | `Persona` model + **`build_agent(persona, feature, ctx)`** generic builder; Pydantic outputs (`Plan`, `ReviewResult`) evolve into `Handoff`, `ValidatorReport`, `MissionPlan` |
| `a2a/server.py`: serves fixed `planner` and `coder` crews | Serves **any persona**: request `{persona_id, feature, mission_dir, trace}` → `build_agent` → single-task crew → Handoff JSON |
| `orchestration/run.py`: fixed prepare → plan → code ⇄ review → finalize | **MissionRunner**: milestones → serial features → parallel validators → escalation ladder; patterns selectable for evaluation |
| `providers/factory.py`: hardcoded Groq + Gemini + Ollama | **Connection registry** with key pools; OpenAI-compatible presets; native Anthropic adapter |
| `providers/router.py`: one global `provider_order` | **Per-persona** model assignment (primary, fallback, escalate) + catalog + assigner; budgets |
| Blackboard `tasks` | Extended to missions, milestones and features (claims and leases kept) |
| 1 s polling in the UI | **WebSocket** push by event `seq` (gap detection already exists) |

```python
def build_agent(persona: Persona, feature: Feature, ctx: MissionContext) -> Agent:
    llm    = HexLLM(router, persona=persona.id, assignment=assigner.resolve(persona))
    skills = skill_registry.resolve(persona.skills + ctx.mission_skills(persona) + feature.extra_skills)
    tools  = (workspace_tools(ctx.worktree, writable=persona.kind == "worker")
              + plugin_tools(persona.plugins, approvals=ctx.approvals)
              + [load_skill_tool(skills)])
    return Agent(role=persona.name, goal=feature.title,
                 backstory=persona.instructions + skills.index_text(),
                 llm=llm, tools=tools, max_iter=limits.max_iter(persona))
```
```python
# MissionRunner (simplified)
for milestone in plan.milestones:
    for feature in ready_in_order(milestone):                  # serial
        handoff = await backend.dispatch(persona_for(feature), feature, ctx)   # Blackboard or Messaging
        handoff = enrich_from_evidence(handoff, sandbox_log, git)              # facts not claims
        checkpoint(ctx.worktree, feature.id); record(handoff)
        await quick_check_or_retry(feature, handoff)            # escalation ladder §8.6
    reports = await gather(*[run_validator(v, milestone, ctx) for v in milestone.validators])
    await resolve_or_escalate(milestone, reports)
```

### 12.4 API (REST + WebSocket)
- **Missions:**
  - `POST /api/missions` (create from an idea and project)
  - `GET /api/missions/{id}`
  - `POST .../approve`, `/pause`, `/resume`, `/redirect`, `/stop`
  - `POST .../apply`, `/discard`, `/revert`
  - `POST .../checkpoints/{commit}/restore`
- **Needs you:** `GET /api/missions/{id}/needs`, `POST /api/needs/{id}/answer`
- **Personas, skills, plugins:**
  - `GET/POST/PUT /api/personas`
  - `GET /api/skills`, `POST /api/skills/import`
  - `GET/POST /api/plugins`, `POST /api/plugins/{id}/approve`
- **Models:**
  - `GET/POST/DELETE /api/connections`, `POST /api/connections/{id}/test`
  - `GET /api/catalog`
  - `GET/PUT /api/assignments`, `POST /api/assignments/auto`
- **Observability:** the existing event, run, task, A2A and provider endpoints. Later: `/api/audit/verify`, provenance, metrics.
- **WebSocket:** `GET /ws/missions/{id}?after_seq=N`. A snapshot, then an ordered event stream. On reconnect, the client resumes from the last contiguous `seq`.
- **Auth:** the existing bearer token between app and backend; the backend binds to loopback.

### 12.5 Data model (Postgres; existing tables kept)
- **Existing:** `projects`, `conversations`, `messages`, `runs`, `tasks`, `events`, `llm_calls`, `eval_runs`, …
- **New:**
  - `missions`, `milestones`, `features` (or `tasks` extended with mission / milestone / persona columns)
  - `handoffs`, `validator_reports`, `needs`
  - `personas` (+ `persona_versions`), `skills` (index and hash), `plugins` (+ `plugin_approvals`)
  - `connections` (no secrets; keychain reference), `model_assignments`
  - `delegation_events` (or typed `events`), `checkpoints`, `audit_log`, `trace_spans`

### 12.6 MCP server: 16 tools (course requirement 2)
| Group | Tools (✅ = built) |
|---|---|
| Workspace (7) | ✅ `list_files`, ✅ `read_file`, ✅ `search_code`, ✅ `write_file`, ✅ `replace_in_file`, ✅ `delete_file`, ✅ `move_file` |
| Git (3) | ✅ `git_status`, ✅ `git_diff`, ✅ `git_log` (worktree-scoped, read-only) |
| Checks (2) | ✅ `run_check` (run-contract commands by name), `list_checks` |
| Mission (2) | ✅ `get_feature_context` (feature, contracts, earlier handoffs), ✅ `list_features` |
| Knowledge (2) | ✅ `load_skill`, `search_standards` (ChromaDB coding standards and verified lessons) |

- **Validation:** every tool has Pydantic argument and result models plus a path guard.
- **Allow-lists:** per-kind tool lists (validators and research can't write) are enforced in ADK `before_tool_callback`, the CrewAI tool guardrail, and the MCP server.
- **Tests:** unit tests per tool plus one stdio round trip.

### 12.7 Sandbox
- **Image:** per-project, built from `.hex/Dockerfile` (stack packs provide templates) and cached by content hash.
- **Hardening:**
  - `--network none` during test and start (network allowlisted for install only);
  - `--cap-drop ALL`, `no-new-privileges`, non-root user;
  - read-only root filesystem + tmpfs;
  - pid, memory and CPU limits; a wall-clock timeout;
  - no environment secrets, no Docker socket;
  - `.git/hooks` and git config mounted read-only.
- **Execution:** one process per command (`docker exec`). Output is captured as the evidence in `CommandResult`.
- **Without Docker,** checks **fail closed**; they never run unsafely on the host.

### 12.8 Reuse of what's built (nothing is thrown away)
- **Kept as is:** path guard, worktrees and snapshots, the sandbox runner, the MCP server and bridge, the Blackboard (claims, leases, reaper), the event log with gap-free `seq`, TelemetryHub (ADK + CrewAI callbacks), the A2A server and client with traceparent, the A2A explorer, `ProviderRouter` (retry, fallback, cooldown, `llm_calls`, pricing), `HexAdkLlm` / `HexLLM`, Groq pseudo-tool-call salvage, the context manager, redaction, the Router + policy (the scikit-learn baseline is not built yet, D59, D62), the 14-task benchmark, and the Electron security setup.
- **Moved behind Developer mode:** the Monaco editor, file tree, Observability tabs and diff view.

---

## 13. Safety, security and privacy

### 13.1 Principles
- **Meta's "Rule of Two":** an agent should have at most two of:
  - (A) untrusted input (repo content, web pages, third-party skills);
  - (B) access to sensitive data or secrets;
  - (C) the ability to change state or communicate externally.

  If it needs all three, it requires user approval. H.E.X maps this per runtime type:
  - **Workers:** A + C inside the sandbox only, with no secrets.
  - **Research:** A + network, read-only.
  - **Validators:** A, read-only.
- **Prompt injection isn't a solved problem.** Limiting capabilities (architecture) is relied on more than detection.

### 13.2 Guardrail layers (course requirement 8)
| Layer | Guardrail | Where |
|---|---|---|
| Input | Secret redaction ✅; prompt-injection screening of user messages, file content, web content and skill text (heuristics + an LLM classifier with a Pydantic verdict); untrusted content clearly marked as data | ADK `before_model_callback`, context manager |
| Plan | User approval of the PRD, validation contract and plan changes; Ask mode can't write ✅; low Router confidence leads to a clarifying question ✅ | Mission state machine, Router policy |
| Tool | Per-kind tool allow-list; path and argument validation ✅; plugin permissions + approvals; rate limit per mission | `before_tool_callback`, CrewAI tool guardrail, MCP server |
| Output | Pydantic schemas with one repair retry ✅; CrewAI task guardrails (the handoff must list files; a review must cite file and line); lazy-edit rejection | `after_model_callback`, CrewAI tasks, edit applier |
| Execution | Worktree isolation ✅; hardened sandbox; allow-listed checks ✅; no-change and zero-test rejection ✅; QA tests protected from builders | MissionRunner, sandbox |
| Budget | Per-mission and per-persona cost and token ceilings; warning at 80%, pause at 100% | `ProviderRouter`, `before_model_callback` |

Every trigger becomes an event, a span attribute and an audit record. Blocking triggers appear in **Needs you**.

### 13.3 Secrets
- Keys are kept in the OS keychain (local) or Secret Manager (cloud).
- They never reach the renderer, logs, traces, git or the sandbox.
- Secrets are redacted from model context and logs; `.env` files in user projects are excluded from context by default.

### 13.4 Electron security (kept)
- **Electron isolation:** `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`.
- **Narrow API:** the preload exposes 3 allow-listed calls; IPC rejects calls from other pages; navigation away from the app is blocked.
- **Backend:** bound to loopback, with a bearer token.

### 13.5 Privacy (data leaving the machine)
- **Privacy modes per project:**
  - **Local only:** Ollama / LM Studio.
  - **Trusted providers:** a user-chosen list.
  - **Any provider.**
- **Provider data badges:** whether the provider trains on data, how long it keeps it, and the server region. Shown from curated metadata, with a link to the provider's policy.
- **OpenRouter zero data retention:** a routing filter can be enabled.
- **What leaves the machine:** only the prompt of each model call. Mission state, contracts, handoffs, memory and code stay local.

---

## 14. Observability

### 14.1 Telemetry (built, extended)
- **Sources:** all 8 ADK callback types (agent, model and tool before/after, plus model and tool error), CrewAI step and task callbacks, kickoff hooks and event-bus listeners, plus our own sources (provider router, sandbox, guardrails, Blackboard). They all feed **TelemetryHub**.
- **Outputs:**
  1. the ordered **event log** (typed, gap-free `seq`, TS types generated from the backend schema);
  2. **OpenTelemetry spans** (mission → milestone → feature → agent → model / tool / A2A / sandbox / guardrail), propagated across A2A with `traceparent`;
  3. **metrics;**
  4. **audit records.**
- **New event types:**
  - mission and milestone lifecycle: `feature_started` / `feature_completed`, `handoff_recorded`, `validator_started` / `validator_report`;
  - delegation: `delegation_decided`, `model_fallback`, `key_rotated`, `model_escalated`, `budget_warning` / `budget_exceeded`;
  - user interaction: `needs_user`, `checkpoint_created`, `applied`, `reverted`;
  - skills and plugins: `skill_loaded`, `plugin_call`.

### 14.2 Tracing and audit
- **OTel export:** a local collector with Phoenix or Jaeger, plus `trace_spans` in Postgres so traces render offline. `gen_ai.*` semantic-convention names are used where they exist; note these are still at "Development" status, so versions are pinned.
- **Audit log:** append-only and hash-chained, built on the existing event log (`hash = sha256(prev_hash + canonical(record))`). It covers model calls (hashes plus redacted content), tool calls, file writes, guardrail decisions, approvals, apply and revert. `GET /api/audit/verify` checks the chain.
- **Provenance:**
  - **First, at feature level:** changed file → feature → handoff → agent instance → model call(s) → persona version + skill versions + model → plan → user approval.
  - **Hunk level** (which diff hunk came from which tool call) is a stretch goal.
  - Exportable as PROV-style JSON.

### 14.3 Views
| View | Where | Shows |
|---|---|---|
| Mission Control metrics | Main screen | Progress, tokens (in / cached / out), cost vs budget, time |
| Costs and delegation | S8 | Spend per persona, model and milestone; delegation reasons |
| Mission board (Blackboard) | Dev mode ✅ (to be extended) | Feature columns, claims, leases, attempts, dependencies |
| Agent grid, callback stream, schema checks, pattern topology | Dev mode ✅ | Live agents, callbacks, Pydantic validation results, active pattern |
| A2A explorer | Dev mode ✅ | Agent cards, task timelines across the boundary |
| Message flow | Dev mode | Messaging-backend sequence diagram |
| Tool catalog + live calls | Dev mode | 16 tools, per-kind allow-lists, call feed |
| Guardrail activity + prompt/skill variant manager | Dev mode | Triggers; variant comparison |
| Trace explorer, metrics dashboard, audit log, provenance | Dev mode | §14.2 |
| Experiment dashboard | Dev mode | §15 results |

**Rules for every view:** it's backed only by stored data, works after a reconnect (snapshot + resume), shows prompts **redacted**, and draws charts with one charting library (Recharts, approval needed). **The Phaser game map is dropped** (§21).

---

## 15. Evaluation

### 15.1 Benchmarks
- **Feature benchmark (exists):** 14 to-do-app tasks with hidden acceptance tests. Each test fails on the seed and passes on the reference (Node, `node:22` sandbox). Extend it to 20–30 tasks.
- **Mission benchmark (new):** 3–5 small full apps built from an idea, for example:
  - to-do app with login;
  - notes app with tags;
  - expense tracker with charts.

  Each has hidden acceptance tests (API + Playwright) and uses the **v1 stack pack**, so runs are comparable.
- **Safety negatives:** tasks that try path escape, network access, secret reads and plugin misuse. Each must be blocked.

### 15.2 Runner
- **Command:** `python -m app.evaluation.run --experiment E2 --repeats 3`.
- **Per run:** a fresh workspace and the full pipeline, graded by the hidden tests and recorded in `eval_runs`.
- **Reproducibility:** pinned model profiles, fixed budgets, an exact-match response cache for replays, and resumable runs (rate limits).

### 15.3 Experiments (not a full grid)
| ID | Question | Varies | Fixed |
|---|---|---|---|
| **E1 Patterns** | Does the mission team beat a single agent? | P-single, P-pipeline (plan → code → review), P-reflection, P-parallel, **P-mission** (default), P-adaptive | Model preset, Blackboard, base skills |
| **E2 Serial vs parallel** | Do parallel builders conflict? | P-mission vs P-parallel; conflict, duplicate-work and merge-failure counts | As E1 |
| **E3 Model delegation** | Does mixing models per role pay off? | All-cheap vs all-top vs Auto-mixed; escalation on/off; providers (covers the original "≥40 runs across providers" requirement) | P-mission, Blackboard |
| **E4 State sharing** | Blackboard vs messaging | Coordination backend | Best pattern and preset |
| **E5 Prompt / skill variance** | How much do instructions and skills matter? | ≥3 variants of PM and worker instructions or orchestration skills; skills on/off; repeats for variance | Best configuration |
| **E6 Router** | LLM Router vs scikit-learn baseline | Classifier | Labeled request set |

### 15.4 Metrics
- **Outcome:** pass rate (hidden tests), pass^k (consistency over k repeats), Needs-you count.
- **Efficiency:** wall time, time per phase, tokens in / cached / out, cost (from verified prices).
- **Process:** retries, escalations, fallbacks, key rotations, validator catch rate and false-positive rate, edit-format compliance, guardrail triggers.
- **Quality:** an LLM-judge score with human spot checks on ≥20% of runs. An LLM judge alone isn't ground truth.
- **PEAS metrics (from the original brief):**
  - PM / planner: completeness of subtasks; rate of duplicate or overlapping tasks.
  - Workers: compile and test success, standards compliance, rework.
  - Validators: defects caught before integration, false positives.

### 15.5 Honesty rules
- No performance claim before running the experiment.
- Report variability, failures, missing data and limitations. A null result ("the team didn't beat a single agent on small tasks") is reported as-is.
- Results go in a dated table generated by script from Postgres and are browsable in the experiment dashboard.

---

## 16. Course requirements coverage

| # | Requirement | How H.E.X v3 meets it | Status | Phase |
|---|---|---|---|---|
| 1 | State sharing: Blackboard vs messaging | Two coordination backends for missions (§9.8), compared in E4 | Blackboard ✅; messaging ✅ (D58); E4 runnable ✅ (D59), no live results yet | P7, P8 |
| 2 | Tools via MCP (16 tools) | H.E.X MCP server, 16 tools (§12.6), plus user plugins as MCP servers | 6/16 ✅ | P5–P6 |
| 3 | Structured output (Pydantic) | Router decision, MissionPlan, Handoff, ValidatorReport, guardrail verdicts, Persona, catalog, events, API models; one repair retry | ✅ (extended each phase) | all |
| 4 | Agentic design patterns, compared | Six patterns incl. P-mission and P-parallel (E1, E2) | 2 built ✅ (sequential, reflection) | P3, P8 |
| 5 | Monitoring via callbacks | All 8 ADK + CrewAI callbacks → TelemetryHub → live views | ✅ (CrewAI event bus to finish) | P3–P7 |
| 6 | A2A between ADK and CrewAI | ADK MissionRunner ↔ CrewAI persona crew service; traceparent; A2A explorer; reverse direction for the QA → Reviewer hand-off | ✅ one direction | P3, P5 |
| 7 | Only CrewAI + ADK | §12.2; external CLIs future and off in the graded build | ✅ | — |
| 8 | Guardrails + prompt variants | Layered guardrails (§13.2); persona instruction and orchestration skill variants with ids on every call (E5) | Partly ✅ | P5–P6 |
| 9 | Observability: tracing, audit, provenance | OTel spans across A2A, hash-chained audit, feature-level provenance, delegation log, views | Event log ✅ | P7 |
| 10 | End-to-end evaluation (cost, time, prompt variance) | Runner, benchmarks, E1–E6, dashboard (§15) | 14-task benchmark ✅; mission benchmark, runner, E4/E5, results, safety negatives and dashboard built ✅ (D59); E1–E3, E6 blocked; no live results yet | P8 |
| 11 | Cloud deployment | **H.E.X backend on Google Cloud** (§18.2, P9); details decided with the user at that phase | Planned | P9 |
| + | Original brief: scikit-learn baseline, ≥40 runs across providers, PEAS metrics | E6, E3, §15.4 | Label tools ✅; the scikit-learn baseline is not built (needs your approval of the dependency and your labels, D62) | P8 |

---

## 17. Current state (what is already built)

**Built M0–M4, P1, P2:**
- **App:** Electron + React IDE (Monaco, tabs, file tree, Ask/Edit/Auto chat, read-only diff), Postgres, typed event log.
- **Routing:** Router (ADK LlmAgent + policy) with a scikit-learn baseline; context manager with summaries and redaction.
- **Agents:** CrewAI Planner and Coder served over **A2A** (separate process, traceparent, bearer auth); ADK orchestration (Sequential + Loop) with an ADK Reviewer.
- **Workspace:** Blackboard with atomic claims and leases; git worktrees; Docker sandbox; 6 MCP tools; ChromaDB coding standards.
- **Providers:** `ProviderRouter` (Groq → Gemini → Ollama, retry, fallback, cooldown, cost, `llm_calls`) with native tool calling and Groq pseudo-tool-call salvage.
- **Observability:** TelemetryHub (ADK + CrewAI callbacks) and Observability UI (Blackboard board, agent grid, callback stream, schema checks, pattern topology, A2A explorer).
- **Evaluation:** 14-task benchmark with hidden tests.

**Built in P3 (Mission core; test-verified, not yet run live with real keys):** personas as data and `build_agent`; the persona crew over A2A; missions from a hand-written plan (D24) with the mission folder; the MissionRunner (serial features, retries, Needs you, checkpoints, pause/stop/resume); apply, revert, keep, discard and restore checkpoint; the WebSocket mission stream and mission events; Mission Control v1.

**Built in P4 (Models & keys; test-verified, not yet run live with real keys):** connections and key pools in the OS keychain; per-persona routes with key rotation and fallback; the native Anthropic adapter; the models.dev catalog with curated profiles; the Auto assigner with presets; escalation on the last attempt; mission and per-persona budgets; costs and the delegation log; the Models & Keys, Team and Costs views.

**Known gaps** (from the review, now planned):
- the diff can't be applied yet;
- "live" means 1 s polling;
- free-tier limits dominate results;
- medium and high complexity share one pipeline;
- A2A runs in one direction only;
- the workspace must be a git repo;
- Docker is required for checks.

**Pinned versions** (from the version-check spike, 2026-11-01): `google-adk 2.13.0`, `crewai 1.15.28`, `a2a-sdk[http-server]~=0.3.10` (0.3.26 tested; CrewAI's A2A code breaks on 1.x), `mcp 1.28.1`, `opentelemetry-sdk 1.44`. Re-run `spikes/adk_a2a/` after any upgrade.

**Spike findings to remember:**
- An ADK `LoopAgent` stops only when a step escalates.
- Every loop iteration sees the full history, so per-round context must be controlled.
- Trace metadata arrives in request-level `RequestContext.metadata`.
- On Windows, MCP subprocesses need a Proactor loop (run without `--reload`, or on the dedicated MCP thread).
- `DatabaseSessionService` needs `google-adk[db]`.
- **Provider quirks:**
  - Gemini 3 needs thought signatures on replayed tool calls.
  - Groq per-minute 429s are rate limits, even though the message mentions billing.
  - Reasoning models need larger output budgets.
  - Llama 3.3 and gemini-2.5-flash are retired.

---

## 18. Roadmap

### 18.1 Phases (from now)
| Phase | Goal | Main work | Requirements | Exit check |
|---|---|---|---|---|
| **P3 Mission core** | Close the loop with missions | `Persona` + `build_agent`; crew service serves any persona; mission folder, `features.json`, `Handoff`; MissionRunner (serial features, quick check, escalation ladder with current providers); per-feature checkpoints; **apply / discard / revert / restore**; **WebSocket** stream; **Mission Control v1** (progress, features, log, live output, pause/stop, checkpoints) | 3, 4, 5, 6 | A two-milestone to-do mission runs end to end, is applied to a workspace and reverted; the UI updates without polling |
| **P4 Models & keys** | Bring your own models, per persona | Connection registry (OpenRouter, Anthropic native, OpenAI, Google, NVIDIA, DeepSeek, GLM, Groq, Ollama, custom URL); key pools + keychain; model catalog (models.dev + profiles); role requirements, presets, Auto assigner with reasons; escalation models; budgets; delegation log; **Models & Keys screen, team chips, Costs view** | 3, 8, 9 | A mission where PM, Backend and QA use three different providers; a forced 429 rotates the key and falls back, all visible in the delegation log |
| **P5 Planning & validation** | Mission discipline | PM scoping chat; PRD, contracts, validation contract; **plan review + approval**; run contract + per-project hardened sandbox; scrutiny, security and QA validators (acceptance tests; Playwright user testing deferred, D41); research subagents; preview pane; edit-format layer; repo map; MCP tools to 16 | 2, 6, 8 | A builder goes from idea to approved plan to validated app; a deliberate bug is caught by a validator, retried, escalated and fixed |
| **P6 Skills & plugins** | User-built engineers | Skill registry (built-in, folder, GitHub); `load_skill`; persona panel with skill and plugin dropdowns; custom personas; plugin manager with permissions + approvals; orchestration-strategy skills; prompt/skill variant registry; input guardrails; privacy modes | 2, 8 | Adding "motion-graphics" to the Designer changes its output in the next mission; a risky plugin is blocked until approved |
| **P7 Observability & state sharing** | Prove and explain | Messaging backend; OTel export; trace explorer; hash-chained audit + verify; feature-level provenance; metrics dashboard; Needs-you notifications; resume after restart | 1, 5, 9 | The same mission runs on both backends; the audit chain verifies; any changed file traces back to persona, model, skill and approval |
| **P8 Evaluation** | Measured results | Mission benchmark; runner; E1–E6; report and experiment dashboard (built; E1 with 3 patterns, E4, E5 runnable; E2, E3, E6 blocked; D59-D61) | 10, 1, 4, 8 | Reproducible, dated report browsable in the app |
| **P9 Cloud** | Requirement 11 | H.E.X backend + A2A crew service on Google Cloud (§18.2) | 11 | The deployed system runs the demo |

### 18.2 Cloud deployment (P9): direction, details to decide with the user then
- **Backend + ADK orchestrator:** a Cloud Run service. The **CrewAI crew service** is a separate Cloud Run service, keeping the A2A boundary real.
- **Data:** Cloud SQL for Postgres. ChromaDB on a persistent volume or a managed alternative.
- **Sandbox:** Cloud Run Jobs (gVisor, no egress).
- **Secrets:** keys in Secret Manager.
- **Models:** hosted only; no Ollama in the cloud.
- **UI:** a web build of the renderer with real authentication. The desktop app stays for local use.
- **Observability:** OTel → Cloud Trace / Cloud Logging.
- **Workspaces:** cloned into per-mission storage.
- **Keep it cloud-ready from P3 onward:** stateless services, config through environment variables, and sandbox and storage behind interfaces.
- **Ask the user before starting P9.**

### 18.3 Later scope (after the graded version)
- External agent CLIs as workers via ACP (§10.9).
- A Deploy agent for the user's app (Cloud Run, Vercel, …) and a Docs writer persona.
- More stack packs; mobile and desktop app targets.
- Learning loop → skills (§11.8); a skill and plugin gallery.
- Several missions at once; scheduled missions; mobile monitoring.
- A2A 1.0 migration and ADK 2.x graph workflows (§20).

---

## 19. Non-functional requirements

- **Platforms:** macOS and Windows (the backend's data dir defaults to `%LOCALAPPDATA%\hexmind` on Windows); Linux best-effort. Requires Docker Desktop for checks.
- **Startup:** the app shows backend, Docker and provider readiness with actionable errors (port conflict, Docker off, invalid key).
- **Live updates:** WebSocket events appear in the UI within 500 ms of being recorded on a local machine. Reconnect resumes with no missing `seq`.
- **Resilience:** missions survive an app restart and a backend restart (resume from the last checkpoint). No duplicate feature execution (leases + idempotency).
- **Cost safety:** a budget can't be exceeded by more than one in-flight model call.
- **Accessibility:** keyboard navigable, visible focus, WCAG AA contrast, reduced motion.
- **Testing:**
  - backend: pytest (never run two sessions at once; they share the test database), ruff;
  - desktop: Vitest + typecheck;
  - Playwright for UI flows;
  - each guardrail has a triggering test; each MCP tool has unit and stdio tests.
- **Dependencies:** added only when a phase needs them, with approval. Candidates: `keyring`, Recharts, Playwright MCP.

---

## 20. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Scope:** 10 personas, skills, plugins, multi-provider support and 11 requirements | Personas are data on 4 runtime types; phases each end in a working vertical slice; later scope is explicit (§18.3) |
| Multi-agent doesn't beat a single agent | Measure it (E1) and report honestly; the value also comes from validation, transparency and per-role models |
| Validators depend on a correct run contract for any stack | DevOps writes it with templates; the quick check fails fast; stack packs for reliability; a single stack for the benchmark |
| Weak or cheap models break edit formats | Per-model edit formats, tolerant applier, escalation ladder |
| Rate limits and quotas across providers | Token buckets, cooldowns, key pools (with ToS caution), cross-provider fallback, budgets |
| Third-party skills and plugins are malicious or prompt-inject | Permission labels, approvals, sandbox, Rule of Two, untrusted-content marking, pinned skill commits |
| **ADK 2.x deprecates Sequential/Loop/Parallel agents** in favour of graph workflows | MissionRunner is a custom deterministic agent; evaluate a migration to graph workflows; keep patterns isolated behind one interface |
| **A2A 1.0 is out; we pin a2a-sdk 0.3** (CrewAI breaks on 1.x) | Stay on 0.3 and document it for graders; migrate when CrewAI supports 1.x; re-run the spikes |
| OTel GenAI conventions not yet stable | Pin versions; map our events to them |
| Windows quirks (MCP subprocesses, Docker Desktop) | No `--reload` for agent work, dedicated MCP thread, CI on Windows |
| Cloud migration is large | Cloud-ready interfaces from P3; decisions taken with the user at P9 |
| Key leakage | Keychain only, redaction, no keys in the renderer, logs or sandbox; tests for redaction |

---

## 21. Decision log

**v3 (2026-11-19).** Decided in the design review conversation. Items marked ⟲ **reverse or correct** earlier plans or suggestions, after critical feedback.

| # | Decision | Was | Why |
|---|---|---|---|
| D1 ⟲ | Product: **"a dev team in your hand"** for builders, including non-coders | An agent-native IDE for developers | The user's vision; differentiates from T3 Code and Orchestrator.inc |
| D2 ⟲ | **Mission Control** is the main screen; the IDE moves to Developer mode | Monaco-centred IDE layout | Non-coders think in idea → team → progress → preview |
| D3 ⟲ | **Apply / revert in P3** (first) | P7 | The core loop was open: results couldn't be accepted |
| D4 ⟲ | **WebSocket push** in P3 | 1 s polling until P5 | Live visibility is the headline feature |
| D5 ⟲ | **Features run serially; parallel only for read-only work** | 2 parallel coder workers | Conflicts and token waste (Factory Missions, MAST); kept as experimental pattern P-parallel |
| D6 ⟲ | **Personas (data) on 4 runtime agent types** | Fixed Planner / Coder / Reviewer roles in code | Relatable team + per-role models and skills without 10 code paths |
| D7 | **Milestones, structured handoffs, validation contract, separate scrutiny + user-testing validators** | Single review loop | Proven mission design; validation separate from implementation |
| D8 | **QA writes acceptance tests independently**; builders can't edit them | Reviewer only | AgentCoder evidence: an independent test designer helps |
| D9 ⟲ | **Bring your own keys from any provider; per-persona models; Auto with reasons; presets; budgets** | Global Groq → Gemini → Ollama on free tiers | Free-tier limits dominated results; user control over delegation is a core goal |
| D10 | **OpenRouter is one connection among many**, not required | — | User wants no dependence on one gateway |
| D11 ⟲ | **No LiteLLM**; extend own adapters (OpenAI-compatible presets + native Anthropic) | LiteLLM was suggested in conversation | Research: the custom policy layer already covers routing; fewer dependencies |
| D12 ⟲ | **Key rotation only within user-added pools, with ToS caution; cross-provider fallback preferred** | "Rotate keys when one hits its limit" | Limits are often per account; bypassing them can break provider terms |
| D13 ⟲ | **Token claim corrected:** total tokens may rise; benefits are smaller per-agent context, on-demand skills, and lower cost from mixing models | "Uses fewer tokens" | Multi-agent systems usually use more tokens in total |
| D14 ⟲ | **No reuse of subscription logins**; external CLIs via ACP are later scope and off for grading | "Integrate Antigravity / Claude subscriptions" | Provider terms; course requirement 7 |
| D15 ⟲ | **Any stack via a run contract**; one stack pack in v1; benchmark on one stack | "Ship one fixed stack" (first suggestion) | Models can write any stack; validators need a machine-readable run contract instead |
| D16 | **Skills = Agent Skills `SKILL.md`, loaded on demand; plugins = MCP servers with permissions** | — | Open standard; small context; safety |
| D17 | **Orchestration strategy in PM skills; hard limits in code** | All logic in `run.py` | Improves as models improve; doubles as prompt variants |
| D18 ⟲ | **Provenance at feature level first**; hash chain on the existing event log | Line-level provenance + separate audit system early | Scope control |
| D19 ⟲ | **Phaser game map dropped** | Original brief centrepiece; then optional | Not useful for non-coders; observability views cover it |
| D20 ⟲ | **Memory = verified lessons only; skills preferred; measure on/off** | General ChromaDB self-logs | Research: general memory rarely beats none; agent-chosen context can hurt |
| D21 ⟲ | **Experiment matrix as targeted experiments E1–E6** | Providers × patterns × backends × variants grid | Combinatorial cost on rate-limited providers |
| D22 | **Cloud = H.E.X backend on Google Cloud (P9)**, details decided then | — | User decision |
| D23 ⟲ | **One planning document (this PRD)** | Plan v1, plan v2, brief, report | Documentation sprawl |
| D24 | **P3 missions take a hand-written plan** (`POST /api/missions` with milestones and features as JSON); the PM scoping chat and plan approval stay in P5 | A minimal PM call generating the plan in P3 | Keeps P3 deterministic and testable; nothing generated from an idea until P5 (decided 2026-11-19) |
| D25 | **MissionRunner is a deterministic custom ADK `BaseAgent`** (the pattern `orchestration/run.py` already uses), not Sequential/Loop agents or ADK 2.x graph workflows. Resolves Q4 | Spike ADK 2.x graph workflows first | Reuses tested code; `SequentialAgent` and `LoopAgent` are already deprecated in favour of `Workflow`, so the runner avoids both. Revisit in a later spike (decided 2026-11-19) |
| D26 | **`.hex/` is applied into the user's project by default, with a Settings toggle.** Resolves Q5 | Never apply `.hex/` | The project keeps its own docs and run contract (decided 2026-11-19) |
| D27 | **A mission owns one `runs` row; features are their own table** (`missions`, `milestones`, `features`, `handoffs`, `checkpoints`, `needs`), not `tasks` extended. Feature preconditions are free text shown to the agent; execution order is plan order | `tasks` extended with mission columns (§12.5 alternative) | Reuses the per-run gap-free event log, telemetry and `llm_calls` unchanged; keeps the P2 Blackboard `tasks` untouched while `RunWorkflow` still uses it (decided 2026-11-19) |
| D28 | **P3 escalation ladder is retry, retry, Needs you.** The escalation-model rung (§8.6 step 2) waits for P4 model assignment and the PM re-plan rung (step 3) for P5; until then attempts 2 and 3 use the persona's current model with the exact findings. Quick checks use the existing `.hexmind/profile.yaml` `test` check; the `.hex/project.json` run contract arrives in P5. Milestone status is `completed` (features done), not `passed`, because validators arrive in P5 | The full four-rung ladder and run contract in P3 | Those rungs need features that do not exist yet; faking them would claim behaviour the system does not have (decided 2026-11-19) |
| D29 | **Apply is explicit, stale-checked and undoable.** It writes the mission's changes (diff against the starting snapshot) into the project only if none of those files changed since, refuses symlinks, and by default commits only those paths on the user's current branch (`commit: false` leaves them uncommitted). Revert restores the files from a snapshot taken just before Apply, and refuses if they were edited since. Discard removes the worktree and branch; restore resets the branch to a feature checkpoint and rewinds the plan, leaving the mission paused | Applying without checks, or committing the whole working tree | The user's files change only on explicit apply (CLAUDE.md hard rule); a commit of only the applied paths never sweeps in the user's own uncommitted work (decided 2026-11-19) |
| D30 | **The Mission Control stream is `GET /ws/missions/{id}?after_seq=N`, authenticated by its first frame, and pushed through Postgres `LISTEN/NOTIFY`.** The client sends `{type: auth, token}` first (a browser WebSocket cannot set headers and a URL token would reach access logs); the server sends a snapshot, then the mission run's events in gap-free `seq` order. `append_event` calls `pg_notify`, so events written by the separate crew process wake streams too; a 5 s safety poll covers a lost connection. Event schema v4 adds `mission_status_changed`, `milestone_status_changed`, `feature_status_changed`, `handoff_recorded`, `checkpoint_created`, `need_raised`, `need_answered` | A WebSocket fed by an in-process publisher (misses the crew process); a token in the URL | Cross-process push without a broker; the token stays out of logs (decided 2026-11-19) |
| D31 | **P4 step 1: connections store keys in the OS keychain (`keyring` approved).** A connection is a provider type (14 presets: OpenRouter, Anthropic, OpenAI, Google, NVIDIA, DeepSeek, GLM, Moonshot, Groq, Mistral, xAI, Ollama, LM Studio, custom) with a base URL and a pool of keys; Postgres holds only a keychain reference, and with no keychain the store fails closed (no plain-text fallback). Adding a connection tests it and lists its models; a key the provider rejects is refused and nothing is saved, while an unreachable provider still creates the connection so it can be fixed. An API key is never sent over plain http to a remote host, URLs and extra headers cannot carry credentials, redirects are never followed, and provider error bodies are never copied into messages. The API's validation errors no longer echo the request body (it can hold a key). Native Anthropic adapter added, no LiteLLM (D11) | Plain-text or encrypted-file key storage | PRD §10.2, §13.3; the user approved `keyring` (decided 2026-11-19) |
| D32 | **P4 step 2: a persona's model calls follow a route, with key pools.** A route is the persona's assigned primary (connection, model) then its fallback chain (`model_assignments`, set by the user until the Auto assigner). Within a connection the key pool is used in order; a 429, exhausted quota or rejected key cools that key down (`Retry-After` if sent, else 30 s / 5 min / 15 min) and the next key takes over (`key_rotated` event, schema v5); a rate limit rotates at once when a spare key exists instead of backing off. With no usable key left, or a provider failure that would repeat on any key, the call falls back to the next target (`provider_fallback`). A persona with no assignment keeps the global provider order. `llm_calls` records the connection and key label, never the key. Provider error text is scrubbed of keys before it is stored | Rotating on every error kind; sleeping through a 429 when a spare key exists | PRD §10.2, §10.6; rate limits are often per account, so a pool is only for keys the user adds on purpose (decided 2026-11-19) |
| D33 | **P4 step 3: the model catalog merges three sources and never guesses.** For each (connection, model) it combines the connection's own live model list (what is reachable), the models.dev catalog (price, context window, capabilities; only the ~11 providers our types map to are cached, ~235 KB, refreshed in the background when over 24 h old, a plain GET that sends no user data, `catalog_auto_refresh` turns it off) and the curated `model_profiles.yaml` (quality tiers 1-5 per capability, edit format, quirks). The profiles are **curated estimates, not measurements**, and say so in the file and the API; the evaluation (§15) is meant to replace them. A model with no source for a field shows it as unknown. The models.dev price is also the cost fallback for models missing from `pricing.yaml`, so routed calls get an `est_cost_usd` (still none for a model nobody prices) | Hand-maintained price table only; assuming a tier for unprofiled models | PRD §10.3; budgets (step 5) need a cost for every model a user connects (decided 2026-11-19) |
| D34 | **P4 step 4: the Auto assigner, and the escalation rung.** Role requirements (`role_requirements.yaml`: minimum tiers, context, focus, critical) are matched against the catalog entries of the user's enabled connections. Presets: Balanced (strongest for critical roles PM and Security, cheapest qualifying elsewhere), Best, Cheapest, Private (local models only). Each persona gets a primary, up to two fallbacks (a different connection first), an escalation model strictly stronger than the primary, and a one-line reason built from known facts only. A model with no profile cannot be shown to meet a requirement, so it is picked only as a last resort and the reason says `unverified`; unknown prices sort after known ones. `POST /api/assignments/auto` previews (`dry_run`) or saves, never overwrites a persona the user set unless asked, and removes stale automatic choices. The runner's **last attempt** (attempt 3) runs on the escalation model through the persona's route, with its normal route as fallback; `llm_calls` and the Handoff record the model actually used. This completes the escalation rung D28 deferred; the PM re-plan rung still waits for P5 | Escalating by default; assuming a tier for unprofiled models | PRD §10.4, §10.5, §8.6 (decided 2026-11-19) |
| D35 | **P4 step 5: budgets, costs and the delegation log use only measured numbers.** The mission budget warns once at 80% (`budget_warning`, schema v6) and stops in Needs you at 100%; a **per-persona budget** (its own `persona_budgets` table, independent of model assignment) does the same for the persona about to work, with options raise / skip / stop. Spending is summed from `llm_calls`, which now records the persona of each call (`CallContext.persona_id`). `GET /missions/{id}/costs` gives totals, tokens, and spend by persona and by model, and counts successful calls whose model has no known price instead of hiding them; per-milestone costs are left out because calls are not attributed to milestones. `GET /missions/{id}/delegation` returns how each persona is set up now (with Auto's reason) plus this mission's `provider_fallback`, `key_rotated`, `escalated`, `budget_warning` and `need_raised` events. The runner records `escalated` when the last attempt moves to the escalation model | Budgets as soft estimates; costs per milestone from time windows | PRD §8.6, §10.6, S8; never display fabricated cost (decided 2026-11-19) |
| D36 | **P4 step 6: Models & Keys, Team and Costs are views next to the IDE, and the UI only ever handles a key on its way in.** A **Models & Keys** view (Connections, Team models) lets you add a connection (the key goes in a password field, straight to the backend, and the form forgets it), manage each connection's key pool by label, test, disable and delete it, run **Auto** with a preset (preview first, then apply; your own choices are kept unless you opt in), set a persona's model yourself, and set per-persona budgets. Mission Control gains real token totals and a **Costs and delegation** panel (spend by persona and model, budget meters that turn to a warning at 80%, unpriced calls counted, who uses which model and why, and the delegation log). `GET /api/personas` is added. As in P3, these are views beside the IDE; making Mission Control the main screen (D2) is still open. Not shown, because the data does not exist: per-key cooldown state, per-milestone cost, quality tiers as anything but curated estimates | Showing key suffixes or a "reveal" button; presenting estimated tiers as measured | PRD S2, S3, S8; keys never go to the renderer (decided 2026-11-19) |
| D37 | **P5 step 1: the run contract (`.hex/project.json`) is the single source of a project's commands, and agents cannot rewrite it.** Checks come from, in order: the contract in the mission worktree, the user's `.hexmind/profile.yaml`, then detection. After every feature the runner runs the contract's `typecheck` then `test` in the sandbox, stopping at the first failure (tests must pass *and* run some), reading the contract fresh each attempt because DevOps may write it mid-mission; a contract with no `test` check cannot pass a feature, and an invalid contract fails the mission with the reason. The handoff lists the commands actually run. `.hex/` is **read-only for agents**: only the DevOps persona may write exactly `.hex/project.json` and `.hex/Dockerfile`, enforced in the path guard the MCP server uses. The MCP server gains `list_checks`. Network modes and building the project image from `.hex/Dockerfile` are the next P5 slice | Trusting whatever an agent writes into the contract or mission files | "Agent claims aren't evidence": a builder that could edit the checks could make its own work pass (decided 2026-11-19) |
| D38 | **P5 step 2: validators gate each milestone, and "could not check" is never a pass.** When a milestone's features are done, its validators run in parallel, read-only: **scrutiny** (`code-reviewer`) runs `test`, `typecheck` and `lint` from the run contract in the sandbox (tests must run some) and has one ADK review per feature on that feature's commit; **security** scans every added line for secrets and secret files with no model (findings name the kind and file:line, never the secret) and adds an ADK security review. Each returns a `ValidatorReport` (§9.5; commands from the sandbox, stored in `validator_reports` and `.hex/mission/validator-reports/`, events `validator_started` / `validator_reported`, schema v7). A validator with no provider or no valid verdict reports `needs_user`. Blocking findings (major or critical) go back to the same persona exactly as reported, as a fresh attempt ladder, then the milestone is checked again, at most 2 rounds; after that the mission stops in Needs you (`milestone_failed`, or `validator_unavailable`) with retry / accept / stop. Milestone statuses gain `passed`, `failed` and `accepted` (you chose to go on). A milestone with no required validators stays `completed`, never `passed`. **Validators this build does not have (QA, next P5 slice) are skipped and the milestone is not marked `passed` by them** | Treating an unavailable reviewer as approval; marking milestones passed without evidence | PRD §8.5, §8.6, §9.5; agent claims are not evidence (decided 2026-11-19) |
| D39 | **P5 step 3: a validation contract, and QA writes acceptance tests from it.** The plan may carry a validation contract (§9.7): criteria `VC-n` with text, how it is checked (unit test, api test, browser, typecheck, security review) and the feature it belongs to; it is stored on the mission and written to `.hex/mission/validation-contract.md`. For a milestone that requires `qa`, before its features are built QA writes acceptance tests for the criteria checked by unit/api tests, from the contract only, into `tests/acceptance/` and the runner commits them (up to 2 tries; any change outside that folder is reset and does not count). **Only QA can write `tests/acceptance/`**: builders and every other agent can read it but not edit it (path guard), and QA's writes are confined to it, so work cannot be made to pass by editing its own tests. The run contract gains an `acceptance` check; the QA validator runs it in the sandbox, names the `VC-` ids found in the output as `contract_ref` findings, and zero tests run is a failure. With no acceptance tests or no `acceptance` check QA reports `needs_user`, never a pass. **Browser-checked criteria are listed as "not checked" until browser testing is built** | Letting builders edit the tests that judge them; counting unchecked criteria as passed | PRD §8.5, §9.7; agent claims are not evidence (decided 2026-11-20) |
| D40 | **P5 step 4: project images and the install network.** A contract that names `.hex/Dockerfile` gets its image built from it, tagged by the file's content hash (an unchanged file is never rebuilt). The Dockerfile is untrusted: every `FROM` must be an allow-listed image (or an earlier stage), the build context holds only the Dockerfile (no `COPY`/`ADD` of local files, no URL `ADD`), there is **no network during the build**, no `# syntax=` directive, no `RUN --mount/--network/--security`, 20 KB and 10 minutes at most. System packages therefore come from the allow-listed base image, or from the `install` check. **Only the `install` check has network, and only through an allowlist**: it runs on a Docker `--internal` network with no route out, whose one other member is an egress proxy container (stock `python:3.11-slim`, read-only, non-root, no capabilities) that tunnels `CONNECT host:443` only for registry hosts (npm, yarn, PyPI, crates, Go proxy; exact or subdomain match) and only to public addresses (an allowed name that resolves to a LAN, loopback or metadata address is refused). Test, typecheck, lint, acceptance and start have no network. The contract's `network.install: none` turns even that off. The runner runs `install` before the quick checks whenever the dependency files (lockfiles, `package.json`, `requirements.txt`, ...) differ from the last successful install. Installed dependencies and caches (`node_modules`, `.venv`, `__pycache__`, ...) stay in the worktree but are never committed, diffed, checkpointed or applied | Letting an untrusted Dockerfile or install script reach arbitrary hosts or the host's files | PRD §9.6, §12.7. The registry list is a constant (`DEFAULT_INSTALL_HOSTS`), not yet a setting (decided 2026-11-20) |
| D41 | **Playwright user testing is future scope, not P5.** QA keeps writing and running acceptance tests (unit/api criteria); criteria checked `[browser]` stay listed as "Not checked (browser testing is not available in this build)" in every QA report and are never counted as passing. The PM scoping chat and plan approval come first, so a mission can be started from the app; browser testing is reconsidered after a live run and the P8 evaluation show whether UI validation is a weak spot. The P5 exit check is read without the browser part | Building Playwright in the sandbox (browser image, start/port/healthcheck, screenshots) now | The heaviest remaining P5 item and the least needed to make the app usable; honest labelling keeps the gap visible (decided 2026-11-20 with the user) |
| D42 | **P5 step 5: the PM scoping chat is a session that becomes a mission.** A scoping session (`scoping_sessions`) holds the conversation, the plan and the PRD, and has its own run from the first message, so the PM's model calls are logged and costed like any other and the same run becomes the mission's run (the trail starts at the idea). Each PM turn is one ADK `LlmAgent` call (purpose `planner`, the PM persona's route) through the ProviderRouter, with a Pydantic output (`message`, `questions`, `plan`, `prd`): the plan is the same `MissionPlan` hand-written plans use, validated by the same rules (known worker and validator personas, unique ids, criteria that point at real features), with one repair attempt; a PM that gives no valid answer or a plan without a PRD leaves the session asking, with the reason and a Try again, and **never invents a plan**. After 3 question turns the PM must propose a plan. The PM is shown the idea, a file listing, the README and the run contract of the project (never `.env*`), and the team. The user edits the PRD, budget and plan JSON, asks the PM for changes, and **Create mission** makes a mission awaiting approval (the PRD goes to `.hex/mission/prd.md`); approving it starts the build, as before. Writing the plan yourself stays available. Not built yet: research subagents during scoping, a cost estimate range and team/model preview on the plan screen, a structured (non-JSON) plan editor | A free-form PM chat with tools, creating the mission before a plan exists | Reuses the validated plan model and the existing approve step; keeps the PM's cost and calls in the same run (decided 2026-11-20) |
| D43 | **P5 step 6: 14 of the 16 MCP tools; the two knowledge tools wait for P6.** Added `delete_file` and `move_file` (both through the write path guard, so `.hex/`, `.env`, escapes and `tests/acceptance/` stay protected; files only, never overwrite), `git_status`, `git_diff` and `git_log` (read-only, this worktree, without `.hex/`, installed dependencies or authors), `list_features` and `get_feature_context` (read from the mission folder; context is the feature spec, its validation-contract criteria and the handoffs of the work *before* it, without model or cost fields). Builders get the delete and move tools; every persona, validators and research included, gets the git and mission tools, and nobody but a worker can change files. `load_skill` needs the skill registry (P6) and `search_standards` needs the standards index; both are built with those | Building `load_skill` and `search_standards` against a registry and index that do not exist yet | Every tool is real and tested, none is a stub (decided 2026-11-20) |
| D44 | **P5 step 7: a ranked repo map in every worker's prompt.** Before each feature attempt the crew service builds a map of the mission worktree: one line per file with the names it defines (JS/TS and Python, found with plain patterns, so no parser dependency and no code or file contents in the map), within about 1k tokens (4000 characters; the rest is summarised as `… and N more files`). Ranking: files the feature names (`target_files`) and files earlier handoffs changed first, then the files those import, then the files the project imports most; tests rank last. It skips secret files, ignored folders, lockfiles and the mission's own `.hex/` files. The map goes after "Work from earlier features" in the feature prompt, so a worker starts oriented and reads a file before changing it | A tree-sitter / PageRank map (a new dependency), or the full file tree in every prompt | Cheap, deterministic and safe on any project; the ranking is the part that can be improved later without changing the interface (decided 2026-11-20) |
| D45 | **P5 is closed; three items move to future scope.** Built: scoping chat and plan approval, run contract and hardened per-project sandbox (image from `.hex/Dockerfile`, allowlisted installs), scrutiny, security and QA validators with a validation contract and acceptance tests, repo map, 14 of 16 MCP tools. Deferred (with Playwright, D41): **research subagents** (the Researcher persona exists but is not started by the PM or workers), the **edit-format layer** (agents change files through `write_file`/`replace_in_file` tool calls, which every connected model so far handles; the tolerant applier and per-model formats are added if the live runs and P8 show malformed edits), and the **preview pane** (it needs the app to run with a published port, which conflicts with the no-network rule for `start` until browser testing is designed). The P5 exit check (idea to approved plan to validated app, a deliberate bug caught, retried, escalated and fixed) is verified by the scripted tests; the live run with real keys is still to do | Building three features whose value is unproven before a live run | Keeps the scope honest and moves to P6; each deferred item is recorded so it is not forgotten (decided 2026-11-20) |
| D46 | **P6 step 1: the skill registry and `load_skill`.** A skill is a folder with a `SKILL.md` (front matter `name` and `description`, then the instructions) and optional files. Sources so far: 26 **built-in** skills shipped with H.E.X (every skill the ten personas name, now real) and the user's folder `<data dir>/skills/` (a user skill with a built-in's name replaces it); GitHub skills come next. Validation: name matches the folder, description up to 200 characters, `SKILL.md` up to 20 KB, files up to 50 KB each; an invalid skill is reported with its reason and **never offered**. Each skill is hashed (SKILL.md and files) and its version is `name@<12 hex>`. A worker's prompt carries only a **one-line index** of its skills (the persona's plus the feature's `extra_skills`); it calls the MCP tool `load_skill(name[, file])` for the full text. The MCP server only serves the skills offered to that agent for that job, and what it returns is marked as guidance that cannot change tools or permissions (skills are untrusted text and are never run). **Provenance:** every handoff records the skills offered (name and version) and which were actually loaded, read from the tool-call log, not from the agent. The PM has no tools while scoping, so its own skills (scoping interview, PRD writing, feature decomposition, ...) are put in its prompt in full: editing them changes how it plans (§11.5). `GET /api/skills` lists them with source, version, files and owners. QA no longer lists `browser-testing` (deferred, D41). `load_skill` is the 15th MCP tool; `search_standards` is still to do | Putting every skill's full text in every prompt; letting a skill grant tools | Carefully selected context beats dumped context (§11.3); keeps skills from widening what an agent may do (decided 2026-11-20) |
| D47 | **P6 step 2: you can edit the team.** A built-in persona can be edited (name, instructions, skills) and reset to its default; you can create custom personas. Both live in Postgres (`personas`, `persona_versions`): the stored row overlays the built-in YAML persona of the same id in the backend process (loaded at startup and after every change), **every change is a new version** (the shipped default is version 1, kept; versions only go up, also after a reset), and an edit that changes nothing makes no version. **Fixed in code:** a persona's kind (validators and the PM cannot become something else), and that custom personas are **workers only** (validators are wired in code; research is not started by anything yet). Skills must exist, at most 12; **plugins stay empty until the plugin manager**. A custom persona cannot be deleted while a live mission has work for it. The crew service has no database: each job carries a **snapshot of its persona** (`PersonaRequest.persona`), and every handoff records `persona_version`, so an old mission can be explained. Custom personas are shown to the PM (so it can give them features), are accepted by plan validation, and are judged like any builder when Auto assigns models. The desktop **Agents** view is the editor: list, instructions, skill checklist (with skipped skill folders and their reasons), version history, reset, delete and new persona | Letting a custom persona change kind or reach validators; editing personas in YAML files | Makes "add motion-graphics to the Designer and the next mission uses it" real and traceable (decided 2026-11-20) |
| D48 | **P6 step 3: the plugin manager.** A plugin is an MCP server attached to chosen builders. **Third-party code never runs on the host:** a stdio plugin is a `docker run -i` process in the same hardened sandbox as checks (shared `hardening_flags`: no capabilities, read-only root, non-root, memory/pid limits, no secrets), in an allow-listed image, seeing the mission worktree only as configured (`mount`: none, read-only, or read-write) and reaching the network only through the allowlist proxy of D40 (`network: allowlist` with `allow_hosts`); a remote plugin is an https URL on a public host, reached without following redirects. **Permission labels are derived from the configuration, never from what the plugin says about itself:** `runs commands` (stdio), `reads files`, `writes files` (the mount), `network` (an allowlist or a remote server); `secrets` is known but not granted, so a plugin that needs a secret is not supported yet. **A plugin needs your explicit approval if it has `network` or `writes files`**; the approval is bound to the hash of the exact configuration, so changing the command, image, mount, hosts or url removes it and turns the plugin off, while renaming it does not. You approve by sending the labels you were shown; if they no longer match, the approval is refused. Only plugins that are **ready** (on, and approved if risky) are ever sent to the crew, which has no database, and started for one job; a plugin that fails to start is logged and skipped, never failing the job. Plugin tools are named `plugin_<id>_<tool>` (the form CrewAI gives the model, so they cannot collide with H.E.X's tools, and two plugin tools that would share a name are told apart by a hash); what they return is marked as untrusted data, truncated, and limited to 40 calls per job; each call is logged as `[plugin-id] ...`. Every handoff records the plugins that were ready (with the configuration hash) and whether any tool was called. Plugins attach to builders (workers) only for now; validators stay read-only. Built-in plugins: the H.E.X workspace server is always on; Playwright (D41) and web fetch are future. The desktop **Plugins** view lists, adds, reviews and approves, turns on and off, attaches to team members, and deletes. Not built: approval at the moment of an action that changes state outside the sandbox (nothing a sandboxed plugin does can), prompt-injection screening of plugin output (guardrails step) | Running plugin processes on the host; trusting a plugin's own description of its permissions; approving once for any later configuration | Plugins are untrusted (CLAUDE.md); the Rule of Two (§13.1) needs the user in the loop when untrusted input meets outside communication or writes (decided 2026-11-20) |
| D49 | **P6 step 4a: privacy modes per project.** Each project has a mode: **any** (every connection), **trusted** (local models plus the connections you list for that project) or **local** (local models only: Ollama, LM Studio; nothing leaves the machine). It is enforced where calls are made, per run, in both routes (the per-persona route executor and the policy chain of providers from `.env`, including an explicitly named provider), and **fails closed**: a connection the mode forbids is skipped with the reason, and if nothing allowed is left the call is **not sent** and fails saying why (logged in `llm_calls`); a mode the code does not recognise is read as `local`. Calls that belong to no run (connection tests, model discovery) carry no project content and are not restricted. In `local` mode **plugins with network access are not started**. Set in Settings for the open project (`GET/PUT /api/projects/{id}/privacy`). Not built, because they need verified facts and are not claims to invent: provider data badges (training, retention, region) and the OpenRouter zero-data-retention filter | Trusting each caller to check the mode; defaulting an unknown mode to open | What leaves the machine is the prompt of each call (§13.5), so the check sits at the one place every call passes (decided 2026-11-20) |
| D50 | **P6 step 4b: input guardrail against prompt injection.** Untrusted text is screened with plain patterns (no model call) before a model sees it: a plugin's output, a file an agent reads, a user's (downloaded) skill when loaded, and the README shown to the PM. Signals: orders to ignore earlier instructions, claims to be the system or a new role, orders to send data out (with a data object, so "email support at ..." is fine), imitation of tool calls, and invisible characters (zero-width space, bidi overrides, Unicode tag characters, a zero-width no-break space inside text; not the joiners of emoji and Persian, direction marks, or a leading byte-order mark). A strong signal, or two weak ones (hiding things from the user, destructive orders), **marks** the text: a `[H.E.X guardrail]` notice saying it is data and why, invisible characters removed, every visible word kept. **Nothing is blocked**, so a false positive costs a label, not a failure; file contents are never changed on disk and `replace_in_file` never sees a label. Every label becomes a `guardrail_triggered` event (`prompt_injection`, `warned`, which tool and signals). H.E.X's own skills, standards and personas are tested to screen clean. Known limits: pattern detection is partial by nature (the PRD relies on capability limits, not detection); only the first 200,000 characters are scanned; the LLM classifier and blocking triggers in Needs you are not built | Blocking on a heuristic; stripping text from files | Detection can be fooled and can misfire; the sandbox, approvals and read-only validators are what limit harm (decided 2026-11-20) |
| D51 | **P6 step 5: skills from GitHub, pinned and previewed.** `POST /api/skills/github/preview` takes a `https://github.com/owner/repo[/tree/<ref>/<folder>]` address (strictly parsed: github.com only, no credentials, port or query), resolves the ref to a **commit SHA**, reads that commit's tree through GitHub's API (public repositories, no token, no redirects followed, nothing but a generic `hexmind` user agent sent), and takes **regular files only** (never symlinks or submodules or `.git*`), with limits (20 files, 20 KB for `SKILL.md`, 50 KB per file, 500 KB, 40 requests). The result is validated with the same rules as any skill and screened for injection (D50), then **shown** to you in full: name, description, pinned commit, files, any warning, the whole text. Nothing is stored. `install` fetches **that same commit** again and refuses unless the content hash equals the one you saw; the skill goes into your skills folder with a record of its origin (`.sources/`, never read as a skill), replacing one of yours only if you say so, and a user skill with a built-in's name overrides it (removing it brings the built-in back). A skill is text: it is never executed, agents get it only as untrusted guidance, and a user skill is screened again each time it is loaded. Removing a skill a team member still uses is refused unless a built-in stands in for it. The desktop **Skills** view lists skills, shows each one's text and origin, and adds from GitHub. Not built: private repositories (they need a token, a secret) and updating to a newer commit (you reinstall) | Cloning repositories; following a branch instead of a commit; installing without showing the text | What you approve is what runs (decided 2026-11-20) |
| D52 | **P6 step 6: prompt and skill variants.** A variant is a named set of changes, per persona, to its **instructions** and/or its **skills** (an empty list turns them off); it cannot change a persona's kind, tools, plugins or model. A mission (and its scoping chat) runs under at most one, chosen when it is started (`variant_id`); it is applied on top of the persona as the user has it now, never stored into it. **The variant id is recorded everywhere it matters for E5:** on the mission, on every handoff, on every `llm_calls` row (PM scoping, builders, acceptance tests and reviewers alike), and as `prompt_variant_selected` events at the start (one per changed role, not repeated on resume). It reaches the crew inside the persona snapshot, and the security validator's instructions too. A variant that missions have run under **cannot have its content changed or be deleted** (its results would stop meaning what they say): copy it to a new id; renaming is allowed. `GET/POST/PUT/DELETE /api/variants`; a selector on the new-mission form. The PM's own skills (scoping interview, PRD writing, feature decomposition) are the orchestration strategy of §11.5 and are part of its prompt, so a variant that edits them changes how it plans. Honest limit: the failure-handling and escalation-policy skills are guidance text for the PM, but retries, escalation and budgets stay fixed in code, so they do not yet drive decisions. Not built: the variant manager and comparison screens (P7 developer mode) | Storing variants into personas; letting a run's variant change afterwards | Experiment E5 compares configurations, so the configuration must be recorded and fixed (decided 2026-11-20) |
| D53 | **P7 step 1: a tamper-evident audit chain, and resume after a restart.** Every event of a run carries `prev_hash` and `hash = sha256(prev_hash + canonical(record))` (record: run, seq, type, agent, task, payload and timestamp; canonical JSON with sorted keys; the first event chains from `sha256("hexmind-genesis:<run id>")`), written in the same transaction that takes the sequence number, so the chain is as gap-free as `seq`. `GET /api/audit/verify` recomputes a run's (or a mission's, or every run's) chain and reports the **first** break and why: content changed, link broken, an event missing in the middle, or events missing at the end. **What it proves and what it does not:** it proves the log is consistent; someone with database access who recomputes every later hash would fool it, so `GET /api/audit/head` gives the **head hash** to keep elsewhere, and `verify?expected_head=` then also catches a rewritten or truncated log (tested, both ways). Events from before the chain existed are counted as `legacy`, not trusted. **Every model call records `request_sha256` and `response_sha256`** (hashes of exactly what was sent and received, on `llm_calls` and in `llm_call_completed`, event schema **v8**): the text itself is never stored, which is what keeps prompts out of the audit trail while still proving what a call was. Tool calls, file writes (the `write_file` calls), guardrail decisions, approvals, apply and revert are already events, so they are chained. **Resume after a restart:** at startup every mission still `running` with no runner in this process is **paused** with the reason `the backend stopped while this mission was running` (never resumed on its own: that would spend money unasked); resuming goes back to the last checkpoint. The desktop Observability view has an **Audit** tab (verify, the head hash, check against a hash you kept). Not built: storing redacted prompt text, and signing or anchoring the head outside the machine automatically | A mutable log; storing prompts to prove what was sent; resuming missions automatically | The chain makes edits visible, hashes prove what was sent without keeping it, and what a chain cannot prove is stated (decided 2026-11-20) |
| D54 | **P7 step 2: traces are kept in Postgres and shown in the app.** A span processor in both processes (the backend and the CrewAI crew service) writes every finished OpenTelemetry span to `trace_spans` from a background thread: tracing never slows an agent down, a span that cannot be written is dropped and counted (never retried forever, never an error for the work it describes), and the queue is bounded. **What is stored is sanitised:** only attributes whose names are allow-listed (`hexmind.`, `agent.`, `gen_ai.`, `tool.`, `a2a.`, `check.`, `sandbox.`) are kept, names that carry content (prompt, completion, content, messages, input, output, arguments, response, result, text, ...) are refused even inside an allowed prefix (usage counters and ids pass), string values are redacted for secrets and cut to 300 characters, and the stored spans of a real mission were tested to contain no prompt text. A run's spans are found by trace id (only some spans carry the run id), returned as a tree with timings and a kind (agent, crew, model, tool, a2a, sandbox). The desktop **Trace** tab draws a waterfall with kind filters and each span's attributes. Optional: `docker compose --profile observability up -d` starts Jaeger and `HEXMIND_OTLP_ENDPOINT` exports to it (not required, nothing depends on it). Not built: spans for every sandbox command (only what ADK and the hub already create), and trace retention limits | Storing ADK's full request/response attributes; requiring a collector to see a trace | Traces must render offline, and prompts stay out of tables (decided 2026-11-20) |
| D55 | **P7 step 3: provenance, from the record and not from the agents.** `GET /api/missions/{id}/provenance[?path=]` traces each changed file to the feature(s) whose commits changed it, in order, and for each: the persona and its **version**, the agent instance (`backend_02` = attempt 2), the model used, the skills offered and loaded, the plugins ready and called (with their configuration hashes), the prompt variant, the sandbox commands and exit codes, the commit, the validators and their verdicts, **the model calls of that attempt** (provider, model, tokens, cost, request and response hashes), the plan and **the user's approval**, each with its place in the audit chain (event seq and hash), plus the chain's own verdict. The changed-file list is git's (measured by the runner); an attempt's calls are those its persona made from the last `in progress` before the accepted handoff, so a rejected attempt's calls are not attributed to the accepted work. `?format=prov` exports W3C **PROV-JSON** (files as entities generated by feature activities, performed by persona agents on the user's behalf, using the approved plan, with the model calls as activities). Mission Control shows it per file and exports it. Limit: feature granularity; which hunk came from which tool call is the PRD's stretch goal and is not built | An agent's own account of what it did; a separate provenance store that could drift from the log | Same data as the rest of the record, so it cannot disagree with it (decided 2026-11-20) |
| D56 | **P7 step 4: a metrics dashboard from stored data, without a charting library.** `GET /api/metrics?project_id=|mission_id=` computes, from `llm_calls`, the event log, features and validator reports only: missions by status and average duration; model calls (count, failed and error rate, tokens, cost, average and p50/p95 latency, and how many answered with **no price known**, such as local models); the same by persona, by model and by prompt variant (missions, completed, cost); features by status, attempts, retried and the **first-try rate**; process counts (escalations, provider fallbacks, key rotations, budget warnings, times it needed you, guardrail triggers by guardrail); and validators (checks, **caught** = found something blocking in the first round, **caught and fixed**, could not check, catch rate). **Anything that cannot be measured is `null` and shown as "not measured", never estimated:** the validators' false-positive rate needs a known-correct answer a mission does not have, and edit-format compliance needs the deferred edit-format layer (D45). The numbers were tested against seeded data (exact totals, percentiles, per-mission separation) and against a real mission's own cost and token totals. The PRD named Recharts and asked for approval; **no new dependency was added**: the dashboard draws plain accessible bars (every value is also text) in a Metrics view with the whole project or one mission selectable | Adding a charting library; filling a missing figure with a guess | CLAUDE.md asks before adding a dependency, and a bar list covers what the data needs (decided 2026-11-20; add a library later only if a chart the data needs cannot be drawn this way) |
| D57 | **P7 step 5: Needs-you notifications.** A hook in the renderer looks at the open project's missions every 8 seconds and shows a desktop notification (the Web Notification API, so the preload keeps its three allow-listed calls) when a mission **starts needing you** (with the open need's own summary as the message), **finishes** or **fails**. It is silent the first time it looks (opening the app never replays old news), says nothing about a mission you are looking at in a focused window, tells you again if a mission needs you a second time, keeps going if the backend is briefly down, and stops when it is turned off. Clicking a notification focuses the app and opens the mission. It is **off by default**; Settings has a switch that asks the system for permission when turned on, remembers the choice, and explains a blocked permission or an unsupported system. Not built: notifying while the app is closed or the backend is down (a notification needs a running app) | Native notifications through a new preload call; notifying on every status change | A small, quiet signal for the three moments that matter (decided 2026-11-20) |
| D58 | **P7 step 6: the messaging coordination backend.** A mission has a `coordination` (`blackboard`, the default, or `messaging`), chosen when it is started (new-mission form, `POST /api/scoping` and `POST /api/missions`), stored on the mission and shown in Mission Control. With **messaging a worker has no mission board**: the `list_features` and `get_feature_context` tools are not offered, the workspace tools refuse to read, list or search `.hex/mission/` (also through `./`, doubled slashes and any letter case), and everything the worker learns about the mission is the request the orchestrator sends: the feature, **its validation criteria** (new request field), the earlier handoffs, and any retry feedback. **Recovery is timeout plus resend with an idempotency key:** a request that gets no answer within `a2a_timeout_s` is sent again, unchanged, up to `messaging_resends` (default 2) times, and the crew service keeps the work of each `exchange_id` (the most recent 64): a repeat joins the work already done or still running instead of doing it twice, and the first caller giving up does not stop it. Only a timeout is resent: a failed crew task goes through the normal escalation ladder. The tests run **the same two-milestone mission on both backends** (both complete with the same files), show that a messaging worker's tools and prompt contain no board tools and carry its criteria, and lose the first reply of a real feature on purpose: the request is sent twice (both `a2a_message` events are in the trail) and the model runs once. **Honest limits:** the *code* in the worktree and its git history are shared in both modes (that is the product, not coordination state); what messaging removes is the board (plan, status, handoffs, contract). The orchestrator still writes the board and the database in both modes (the UI and provenance need it), and the validators already receive their context from the orchestrator in both modes. The dedupe memory lives in the crew service process, so a crew-service restart forgets it. Not built: the developer-mode message-flow view, and the E4 comparison itself (P8) | Hiding the whole worktree; a separate message queue or broker; resending after failures | The point is the information a worker can reach, and the two backends can only be compared if the same mission runs on both (decided 2026-11-20) |
| D59 | **P8: the mission benchmark, the experiment runner, results and safety negatives.** **Benchmark (version `m1`, grown in D61):** three apps (to-do with login, notes with tags, expense tracker with chart data), each a fixed plan (`app.yaml`), hidden `node --test` acceptance tests and a known-good reference per feature; `python -m app.evaluation.missions validate` checks that every hidden test fails on the empty project and passes on the reference. They are plain CommonJS libraries, not browser apps: API/Playwright tests stay deferred with Playwright (D41), and a mission starts from the fixed plan, not a PM chat, so conditions stay comparable. **Trials:** one app built by one mission under one condition, run in-process by the real `MissionRunner` in a fresh project; when it ends the hidden tests grade the worktree in the sandbox and the result goes to `eval_runs` (migration 0019: experiment, condition, repeat, config, benchmark version, mission, status, passed, needs-you, escalations, tokens, error). A trial's numbers come from `llm_calls`, events and needs; the agent's report is never the grade (a team that reports success but builds nothing fails). Needs-you items are counted, not answered, and a trial that errors is stored as `error`, listed in the report and run again, never counted as a pass or a fail. **Runnable now: E4** (blackboard vs messaging) and **E5** (baseline vs the user's prompt/skill variants, at least one required). **Not runnable, and reported as `Not run` with the reason, never as a null result:** E1 and E2 (the other team patterns and parallel builders are not built), E3 (needs per-provider model presets and real keys; no live run yet), E6 (the scikit-learn baseline is not a dependency; adding it needs your approval). **Running:** `POST /api/experiments/{id}/run` (or `python -m app.evaluation.run --experiment E4 --repeats 3`, which calls it) runs a sweep one trial at a time in the background, skips trials that already have a result so it resumes after a rate limit or a stop, and has a stop that cancels the mission in flight; one sweep at a time; a budget cap per trial (default 5 USD). The exact-match response cache for replays is not built. **Results:** `app/evaluation/results.py` computes, from `eval_runs` only, per condition the trials, errors, pass rate with a 95% Wilson interval, pass^k (apps that passed in every repeat), needs-you, retries, escalations, time, cost and tokens (mean, with spread when there is more than one trial; `n/a` for what could not be measured, such as the cost of an unpriced model). Two conditions are called different only when their intervals do not overlap; otherwise the report says they cannot be told apart yet and that this is not evidence of equality. `GET /api/experiments/report` (and the CLI `report`, which writes `docs/results/experiments-<date>.md`) renders the dated table. The LLM-judge quality score and the human spot checks (§15.4) are not built. **Safety negatives:** `app/evaluation/safety.py` sends 15 attacks at the real defenses (path escape by `..`, absolute path, symlink and `.git`; reads, writes, deletes and moves of `.env*`; the mission board under messaging; a sandbox check fetching a public site; an unapproved or changed network plugin) and records each as blocked, got through or not run (no Docker); `GET /api/experiments/safety` and `python -m app.evaluation.safety` run it. **Desktop:** an Experiments view lists E1 to E6 with the reason for any that cannot run, a run form (repeats, budget), the running sweep with Stop, results tables, the dated report and the safety run. **Status:** the machinery is built and test-verified with scripted workers; **no experiment has been run with real models, so there are no results to report yet** (§15.5). |
| D60 | **P8 step 2: the response cache for replays (§15.2).** `HEXMIND_RESPONSE_CACHE` is `off` (default), `readwrite` (use a stored answer, otherwise call the model and store the answer) or `replay_only` (stored answers only; a call that is not stored fails, so a replay can never spend money). It sits in `ProviderRouter._attempt`, so legacy and persona-routed calls both pass through it. The key is sha256 over provider, model and the exact request (the bytes the audit trail hashes); only successful answers are stored, in `response_cache` (migration 0020); the request text is not stored, the answer is (it can contain the user's code, like the other stored events). A replayed call is still a row in `llm_calls` and an `llm_call_completed` event, marked `replayed` (event schema field, column), carrying the tokens, price and latency measured when it was really made, so a replayed run reports the figures of the original; the metrics count `replayed` calls and the Metrics card shows them. A replay still needs the connection and its key to exist (the route is resolved before the cache is read), it only spends nothing. `GET /api/experiments/cache` shows the mode and the number of entries. | The brief asks for reproducible, resumable runs; paying twice for the same answer is the cost of not having it | Decided 2026-11-20 |
| D61 | **P8 step 3: a larger benchmark, team patterns for E1, the variant manager and the message flow.** **Benchmark `m2`:** the feature benchmark has 22 tasks (7 low, 8 medium, 7 high; the PRD asks for 20 to 30) and the mission benchmark 5 apps (adds a habit tracker and an inventory); every hidden test is validated against the empty project and the reference in the sandbox. The version changed because the app set changed: results of different versions do not compare. **E1 is runnable with three of the six patterns:** `single` (one backend agent builds every feature, nothing reviews it), `mission` (the plan as written) and `pipeline` (a `code-reviewer` validator at the end of every milestone); reflection, parallel and adaptive are not built, so E1 does not answer the whole question, and the benchmark plans use only the backend persona, so single and mission differ only by the review the pipeline adds (both stated in the report and the app). E2 (needs parallel builders), E3 (needs keys and model presets) and E6 (needs the scikit-learn dependency, which needs approval) stay blocked. **Variant manager:** a section of the Experiments view lists variants and what they change, creates one (per team member: own instructions, skills kept, none, or only these), copies one into a form, and deletes one nobody ran under (a used variant is kept for the record). **Message flow:** an Observability tab drawing the orchestrator and the crews as a sequence diagram from the recorded A2A messages, including a request sent again after no answer under the same exchange id. | Finishes what P6, P7 and P8 left that needs no model | Decided 2026-11-20 |
| D62 | **Decisions of 2026-11-21 (no code yet).** **(1) Future scope, by choice:** private GitHub skills (they need a GitHub token, a new secret) and the LLM injection classifier (D50 keeps the pattern guardrail; the sandbox and approvals are what limit harm); revisit after the live runs show whether they matter. **(2) Research subagents are un-deferred (reverses that part of D45), as an opt-in "Advanced research" switch** when a mission or scoping chat is started: off means nothing changes and nothing extra is spent; on means read-only Researcher helpers look things up before the PM writes the plan and the PM uses their sourced notes. Researchers never change files. Web access is **option B**: a fetcher run by the backend itself (not agent code) for `https` pages on public hosts only, never the user's machine or network, with size limits and its output marked untrusted and screened (D50), plus a **search service**: **Tavily**, its key kept like a provider key (the free plan is 1,000 credits a month with no card, checked 2026-11-21; Brave's free plan was reported withdrawn, so it was not chosen). A deep-research skill is written for the Researcher; a skill only gives method, the tools give the ability, so the skill is not added before the tools exist. The design, the per-mission network approval and the tests are to be written and approved before building. **(3) Routing labels for E6 are the user's to-do:** at least 150 prompts labeled by a person, at least 30 by two people (`docs/routing-labels.md`); the scikit-learn dependency is approved and added only when the labels exist. A search found no public set that labels prompts this way: the closest are LLM-labeled or labeled by another scheme (an intent set of 60k prompts labeled by a model; a coding-agent intent scheme from JetBrains-derived work; a task-complexity set of programming tasks), so they can inform the label scheme but are not the answer key **Progress on (2), five steps:** 1 page fetcher done (`app/research/web.py`: public https pages only, the name's addresses all checked and the request pinned to the checked address, redirects re-checked, size limits, output marked as untrusted); 2 Tavily search done (`app/research/search.py`, `/api/research/search`: the key is read from the OS key store first, then from `HEXMIND_TAVILY_API_KEY` (also `TAVILY_API_KEY`, `TAVILY_KEY`) in `.env`, and is never returned; queries are cleaned of secrets and short; results are marked untrusted and unreadable addresses dropped; the cost is shown as Tavily's own credit figure or `n/a`; `POST /api/research/search/test` runs one real search; checked live on 2026-11-21 with one real search, which Tavily reported as 1 credit, and the top result read by the page reader); 3 researchers in the scoping chat done (`app/research/agent.py`, migration 0021: `POST /api/scoping` takes `research` and `research_confirmed`; refused with the reason when there is no search key or the project's privacy mode is not `any`; the PM names up to 3 things to look up, each goes one after another to a Researcher on its own model route with only `web_search` and `web_fetch` (3 searches, 4 pages and 12 tool calls at most, then stopped); every search and page is a `tool_called` event; a cited source is kept only if the tools showed that address, and the answer is marked as untrusted; the PM sees the notes in every turn and is told to name sources in the PRD; the notes are stored on the session and returned with it; they are not written into the mission folder, so builders never read them); 4 the app side done: Settings has a Web search panel (`SearchKeyPanel`: set, test and remove the Tavily key; it says where the key lives, keychain or `.env`, and never shows it), the new-mission form has an **Advanced research** switch (off by default) that explains what happens and needs a confirming tick and a search key before **Start scoping** is enabled, and the scoping screen shows the research (answers, the sources really read, what was not found, searches, pages and credits, `n/a` when unknown, failed questions as not answered); 5 the `deep-research` built-in skill is written and given to the Researcher in place of `codebase-exploration`, which needs file tools the web researcher does not have. **Not built:** researchers during a running mission (only in the scoping chat), more than one round of research per session, parallel researchers, and a way to re-run research after the first message. Status: built and test-verified with scripted models and a faked web; the one live check so far is one real Tavily search and one real page read (2026-11-21); no real model has driven a researcher yet. Questions run one after another, not in parallel, to stay inside free-plan rate limits. | Building the search and fetch tools now; labeling with a model (it would grade itself); adding scikit-learn before there is anything to train on | Keeps the new network permission explicit and opt-in, and keeps E6 honest (decided 2026-11-21 with the user) |
| D63 | **One-click team setup after a key works (2026-11-21).** On the Connections screen, when a key has just passed its test, or when you have usable models but no team member has a model yet, a box offers **Set up your team automatically**: it previews what Auto (the Balanced preset) would pick for every team member with the reason, marks models nobody has rated as `unverified`, saves only when you press **Use this setup**, never replaces a model you chose yourself, and can be skipped (**Not now**). Nobody has to know a model name; each member's model can still be chosen by hand on the Team models tab. It is not offered after a key that failed its test or when there are no models. No backend change: it uses `POST /api/assignments/auto` (D34) | Making users pick models after adding a key; saving a setup without showing it | Keeps the non-technical path to two steps: add a key, accept the setup (decided 2026-11-21 with the user) |
| D64 | **First live run of Advanced research, and what it changed (2026-11-21).** One real planning session (Groq `gpt-oss-120b` and Gemini `gemini-3.5-flash`, real Tavily search, a scratch project) ran end to end: the PM named 3 questions, researchers made 9 searches (Tavily counted 9 credits) and read 4 pages, and the PM then asked its questions; 23 model calls, 296 s. **Findings and fixes:** (1) Groq's free plan (8,000 tokens a minute) rejected 3 requests as too large and rate-limited 1; the app fell back to Gemini each time, but Groq's retries took 228 s for 19 calls against 37 s for Gemini's 4. So a call's *purpose* can now have its own provider order (`provider_order_by_purpose`, ahead of the complexity order) and research defaults to Gemini first, Groq second; pages shown to the researcher are cut to 5,000 characters. (2) The scoping cost counted only priced calls without saying so; it now carries `unpriced_calls` (same rule as a mission's costs) and the screen says "not counting N calls with no known price". (3) A cited source proved only that an address was seen, not that it supports the claim (the first finding cited a page about other tools). Researchers now give **claims**, each with its source and a short exact quote (at least 20 characters); the backend looks the quote up (ignoring case and punctuation) in the page text the researcher was shown and marks each claim `verified` (found in a page it read), `snippet` (found only in a search snippet) or `unverified` (no usable quote, or not found); a claim whose source the researcher never saw is dropped and counted; when no claim could be checked the notes say so. The PM sees each claim with its check, and the screen shows the same labels beside a warning that a found quote is not proof the claim is true. **Limits:** a verified quote shows the page says it, not that the page is right or that the claim follows from it; no key use was out of allowance (Groq 991 of 1,000 requests left that day; Tavily reported 1 of 1,000 plan credits used, which lags the 10 the app counted) | Treating a cited address as evidence; waiting through free-plan retries | Agent claims are not evidence, so the check is done in code, and unknown cost is shown as unknown (decided 2026-11-21 with the user) |
| D65 | **First live mission, and the speed and token changes it caused (2026-11-21).** A tiny project (a two-function JavaScript library) ran on real models: the PM planned in one turn, then 2 of 3 features were built and the third failed after 3 attempts, about 27 minutes of work and 197,000 input tokens (priced calls $0.034; Gemini's are unpriced). **What the run showed:** (1) Free-plan limits end a session quickly: Gemini `gemini-3.5-flash` allows **20 requests a day**, Groq `gpt-oss-120b` 200,000 tokens a day and 8,000 a minute; Kimi (`moonshotai/kimi-k3.1-pro`, through the user's NVIDIA key, imported as an NVIDIA connection) took about 140 s a call. (2) Groq rejected every request that offered a no-argument tool (`git_status`, `list_features`: an empty `required` and no `properties`); fixed where requests are built (`_clean_tools`). (3) The plan lost the interface in the idea (the builder and QA invented a `Date`-object API while the idea said date strings and a `today` argument), so the PM is told to copy named functions, signatures and example values word for word. (4) Most of the time was waiting on models: 113 calls, 51 minutes, of which 68 calls produced almost no output (the agent took one tool step per call and re-sent the whole conversation each time: about 50,000 input tokens for one 60-line file). (5) A hung fallback model was asked 3 times at 120 s (a 6-minute stall). (6) The dev backend runs with reload, so changing a file restarts it and pauses a running mission (by design, D53); no file is to be touched during a live run. **Changes made:** a timeout now moves to the next provider at once instead of retrying, and the request ceiling is 240 s; tool definitions are sent without pydantic `title` keywords (-12% on the real tool list); a builder's conversation shortens tool results older than its last 8 messages to 300 characters (-55% of the input on a simulated 25-step loop of 2 KB file reads); a builder's first prompt carries the content of the files it is expected to touch (at most 4 files, 2,500 characters each, 6,000 in all, through the same path guard, redaction and injection marking as `read_file`, never `.env*` or `.hex/`, and not for QA's acceptance tests or validators) and tells it to ask for independent tool calls together; the PM sizes the plan to the task (a small task is one or two milestones, a module and its tests are one feature, `security` only where logins, secrets, user input, files or the network are involved, `code-reviewer` on every milestone). Model assignments (settings, not code): Kimi only for the code reviewer; builders back on the default Groq-then-Gemini order. **Not measured live yet:** the token and time effect of these changes on a real mission (the free quotas were used up); the figures above are from tests and a simulation. **Not done:** retrying an unparsable final report once, parallel builders (E2) | Asking the same hung model again; sending files one tool call at a time; planning a scaffold, separate test feature and security review for a two-function library | Speed and tokens are the cost of free models and of the agent loop; each fix is tested (decided 2026-11-21 with the user) |
| D66 | **The first live mission finished, and two fixes it caused (2026-11-21).** The mission of D65 was retried: the unit-test feature passed on its first new attempt (Groq), and milestone 2's validators then passed, so the mission ended `completed` with every milestone `passed`: 10 of 10 tests in the project, the code reviewer's verdict `pass` (free `deepseek-v4.1-flash:free` through a Token Harbor connection, a custom OpenAI-compatible endpoint at `https://tokenharbor.ai/v1`, answering in about 20 s where Kimi timed out at 240 s), QA's acceptance check 3 of 3 in the sandbox; about 296,000 input tokens and $0.038 for the priced calls. Nothing was applied to the user's project. **Fixes:** (1) a provider's HTTP 402 (the plan or wallet does not cover this model) was read as a bad key because its message names the API key, which benched the whole key for 15 minutes, free models included; a 402 is now `model_unavailable`, so only that model is skipped and the key is not cooled. (2) DevOps wrote a run contract with no `acceptance` check, so QA could not run its tests and the milestone stopped for the user; when a contract leaves it out, QA's tests exist in `tests/acceptance/` and the project's own tests use Node's built-in runner (`node --test`, directly or as the `npm test` script), the check is `node --test 'tests/acceptance/**/*.test.{js,mjs,cjs}'`; any other runner gets no guess and QA still reports the missing check. In this run the line was added to the mission's contract by hand as a commit marked as a manual fix, because an uncommitted edit was put back when the retry started. **Not changed:** the acceptance-testing and run-contract skills already ask for the check | Benching a key for one model's price; guessing an acceptance command for an unknown runner | A plan limit is about a model, not a key; a missing setting the app can work out safely should not stop a mission (decided 2026-11-21 with the user) |
| D67 | **Second live mission (a calculator), and three fixes it caused (2026-11-21).** A tiny Node calculator (`src/calc.js` with add, subtract, multiply, divide; `index.js` for `node index.js 6 * 7`), planned in one PM turn (one milestone, one DevOps feature; validators removed on purpose by the user: no security, no QA, no code review). It ended `completed`: the CLI prints 42, 2.5, -3 and 5 for the sample inputs and divide by zero throws `Cannot divide by zero`; the builder's 6 tests pass. The successful attempt took 53 s, 7 model calls (6 to free `deepseek-v4.1-flash:free`, 1 refused by Groq) and about 19,000 input tokens, with 12 tool calls from 6 replies (the batching of D65 working); D65's first mission spent about 50,000 input tokens on one 60-line file. Whole run, with the failures below: about 154,000 input tokens, $0.012 for priced calls. **What failed first, and the fixes:** (1) CrewAI sends tools in strict mode, listing every property as required, defaults included, and Groq refused the model's `load_skill` call without the optional `file` 3 times (HTTP 400); `_clean_tools` now leaves a property with a default out of `required` and drops the `strict` flag. (2) Gemini answered HTTP 503 (high demand) after up to 315 s, and Groq's free plan ran out of tokens for the day (200,000), so the builders now have a per-persona chain set in the app (settings, not code): Groq `openai/gpt-oss-120b`, then `deepseek-v4.1-flash:free` and `deepseek-v4-flash:free` on the user's Token Harbor connection; the Groq key was imported from `.env` as a connection for that. (3) Free DeepSeek wrote its final report in the shape of the JSON schema it was shown (`{"title": ..., "type": "array", "items": [...]}`), so 3 attempts with passing tests failed on the report alone; builders are now shown a filled-in example report instead of the schema, and the report reader takes the answer out of `items` (or `value`) when a model still echoes the schema shape; anything else still fails. **Seen, fixed in D68:** the first attempt's DevOps wrote a test command that only printed `test passed` (a check that cannot fail); the later attempt wrote real tests | Asking for the user's attention on a report whose content is fine; sending strict schemas that make optional arguments required | Free models are the target, so the app must accept their small format slips without trusting their claims (decided 2026-11-21 with the user) |
| D68 | **A test check that cannot fail no longer counts (2026-11-21).** In the calculator run (D67) a builder set the test command to `echo "test passed"`: it exits 0, so the feature would have counted as tested. The earlier rule only refused a run that reported zero tests. A passing `test` (and `acceptance`) check now counts only when its output also shows at least one test running: node's TAP and spec reporters (`# tests 3`, `ℹ tests 6`), `N passed` (pytest, Jest, Vitest, Cargo), `N passing` (Mocha), `Ran N tests` (unittest), `N examples, 0 failures` (RSpec), `OK (N tests` (PHPUnit), Go's `ok  pkg  0.01s` (not `[no test files]`). Otherwise the builder is told the check exited 0 but showed no tests running and must run a real test runner on real tests; the run-contract skill says the same. **Limits:** it reads the runner's output, so a command that prints a fake count would still pass, and a runner whose summary matches none of these is refused until it is added; no extra sandbox run is made | Running the tests a second time with the code broken (slow, and needs to know what to break); a list of forbidden commands (easy to get around) | Agent claims are not evidence, and an exit code alone is not evidence that tests ran (decided 2026-11-21 with the user) |
| D69 | **Auto and the model list use what the account can actually call (2026-11-21).** After a Token Harbor key was added, Auto gave `claude-fable-5` to most of the team: it has the strongest profile, its price is unknown and it had never been called, but the key has no paid plan, so every call would have been refused (HTTP 402). **Changes:** each model in the catalog now carries `free` (a `:free` model id, a local model, or a known price of zero) and `access`, read from this account's own call log: `works` (its latest call answered), `refused` (HTTP 401, 402 or 403: no key, a bad key, or no plan) or `unknown` (never called, or only other failures such as timeouts or rate limits). Auto never picks a refused model; a model with no known price that has never answered here comes after every model that is free, priced or known to work, even when only it is profiled to qualify (the reason then says the stronger ones are not yet used on the account); a free model counts as costing nothing; a pick that may still need a paid plan says so. The Team models list shows each model's price and access in brackets (`free`; `paid · $x in / $y out per Mtok`; `price unknown`; `works on your account`; `refused: needs a plan or key`) and sorts free, worked, paid, unknown, refused; refused ones are shown but cannot be chosen. Auto was re-run (Balanced, keeping the user's own choices): PM, QA, security, code reviewer, researcher, designer and data now use `z-ai/glm-5.3-flash` on NVIDIA (price 0 in the public catalog) with the two free DeepSeek models as fallbacks. **Not done:** probing a model with a test call before picking it (every model call goes through the router, and a probe per model would spend free-plan limits); access is learned from real calls only | Probing every listed model; trusting a profile without knowing the account can call the model | Free models are the target, and a choice the account cannot use is worse than a weaker one it can (decided 2026-11-21 with the user) |
| D70 | **Skills up to 50 KB, with their size shown (2026-11-21).** The `SKILL.md` limit (D46) goes from 20 KB to 50 KB, the limit a skill's other files already had: popular Claude Code and Codex skills are larger than 20 KB (`unslop` is 32 KB) and were refused. The GitHub preview now says roughly how many tokens loading the skill adds to an agent's request (4 characters a token) and calls a skill over 5,000 tokens big, because models with small free-plan limits (Groq: 8,000 tokens a minute) may not handle it and every step costs more. Claude plugin extras (`.claude-plugin`, slash commands, marketplaces) are not used: only the skill folder, which is the same open Agent Skills format | Keeping 20 KB; giving agents only the start of a big skill | The user chose this (2026-11-21) |
| D71 | **Planned, not built: a running app with a link in chat, the PM answering the chat, and model allocation that respects free-plan limits (proposed 2026-11-21, awaiting the user's approval).** **(1) Run it and get a link.** After a mission (or when asked in chat, or with a Run button) the app starts the project in the sandbox with the run contract's `start` command and `port`, publishes that port on `127.0.0.1` only (a free port on the user's machine, never the network), waits for the `healthcheck`, and the chat shows `http://localhost:<port>`, which opens in the browser. **Internet while running is allowed** (the user's choice, like apps built with Claude); installs still go through the allowlisted proxy, keys are never passed into the container, and only one app per project runs at a time. The app restarts after an Apply or an agent's change and can be stopped from the chat or the Run panel; its output is viewable. This replaces the deferred preview pane (D45). **(2) Updates in chat.** While a mission runs, the chat gets short updates written from the event log, not by a model (feature started, tests passed or failed with the count, needs you, done) and at the end a summary with the link; nothing in them is invented. **(3) Who answers the chat: the PM.** The chat uses the PM's model chain (Models & Keys) instead of the global fallback order; the PM sees the plan, mission status and recent events; questions about status, cost or what changed are answered from stored data (no model call); edit requests become a quick edit or a mission, as now. **(4) Model allocation for non-technical users.** Each model in Models & Keys shows, in plain words, what the account has measured: context size, tokens per minute and per day (from the provider's rate-limit headers, e.g. Groq's `x-ratelimit-limit-tokens`), median speed and success rate (from `llm_calls`), free or paid, refused. Each role gets a measured load: its typical and largest request (from `llm_calls`, e.g. builders about 3,000 tokens and up to 5,800, the researcher up to 11,000, as of 2026-11-21). Auto does not give a model a role whose typical minute of work exceeds the model's per-minute limit (Groq free: 8,000 tokens a minute, so it goes to the chat, short routing and review jobs, or stays a fallback), spreads roles across connections so one free limit is not shared by the whole team, and explains each choice in one plain sentence. Manual choice stays possible | Running the app with no network (the user chose internet); a separate chat model; letting the user pick models without the measurements | Decided with the user 2026-11-21; built only after approval |
| D72 | **Projects get a layout a person can run (2026-11-21).** The user found built projects with no folder structure, no README and no virtual-environment setup: the PM kept the scaffold "to the minimum the checks need". The PM's first DevOps feature now also creates `src/` and `tests/`, a dependency file (`requirements.txt` or `package.json`), a `.gitignore` (`.venv/`, `node_modules/`, `.env` and the usual build output) and a README with copyable local setup commands (Python: `python3 -m venv .venv`, activate, `pip install -r requirements.txt`). A new built-in skill, `project-layout`, gives DevOps the details. The virtual environment itself is never created in the repository or committed; inside H.E.X the sandbox image plays that part. Guidance, not enforced in code | Committing a `.venv`; checking the layout in code | The user's report (2026-11-21) |
| D73 | **D71 step 1: the PM answers the chat, and the chat sees the question (2026-11-21).** The chat's answer call now uses the PM's model chain from Models & Keys (recorded as persona `pm`); with no PM model it keeps the global order; the router call stays on the global order (short, cheap). **Bug found on the way, present before D71:** the chat's prompt carried the project, files and earlier messages but not the current message (it is left out of the history to avoid a duplicate and was never added back), so the router and the answer never saw the question and answered things like "I don't see your message"; the message is now added at the end as "The user's latest message". A second bug dropped the PM's route when the task's complexity was set. Both are covered by tests that fail without the fix. Live check: "What functions does src/calc.js export?" answered correctly in 8.1 s on `deepseek-v4.1-flash:free`. The PM's chain was reordered (setting, not code) to put free DeepSeek first and GLM on NVIDIA last, because GLM hung until the 240 s timeout on this check | A separate chat model | Decided with the user (D71) |
| D74 | **D71 step 2: run the app and get a link (2026-11-21).** `POST /api/projects/{id}/app` (optionally a mission's unapplied files, and a chat to post in), `GET` (status, link, output) and `DELETE` (stop); in the chat, the whole message "run it" / "start the app" / "open it" or "stop the app" is handled without a model call, and the chat header has a **Run app** button. The app runs from the run contract (`install && start`, `port`, `healthcheck`) in a container with the sandbox hardening (no capabilities, non-root, read-only root, 1 GB memory, 256 processes, a 1 GB `/tmp`), the folder mounted at `/work`, the internet allowed (bridge network; the user's choice), `PORT` and `HOST=0.0.0.0` set and no secrets; its port is published on `127.0.0.1` only (the contract's port when free on this computer, otherwise another). The link is given only after the app answers; an app that exits or never answers gets the reason and the end of its output instead. One app per project; starting again replaces it; an Apply restarts an app running from the project folder; the backend stops every app when it stops (so the development backend's reload also stops them). Links in chat open in the browser: the desktop opens `https://` and `http://localhost|127.0.0.1:<port>` links externally, nothing else, and never navigates its own window. The run-contract skill tells DevOps how to make an app openable (listen on `0.0.0.0`, Streamlit's exact `start`). **Checked:** unit tests with a fake Docker, two real Docker tests (a Node server's link fetched and posted in the chat; "run it" then "stop the app" in chat with no model call), and live: a Streamlit calculator started from the chat in 63 s (mostly `pip install`), its link answered 200. **Not covered by a test:** the restart after Apply | Running with no network; a preview pane inside the app | Decided with the user (D71) |
| D75 | **D71 step 3: a mission's progress in the chat (2026-11-21).** Each mission gets its own conversation, "Mission: <title>", created at its first update; the user can ask the PM questions there too. Updates are written from the mission's own state changes, never by a model: the mission running, paused, completed, failed, stopped or applied; each feature building (and each retry with its attempt number), done ("its tests passed in the sandbox", which a done feature requires), failed (with the attempts) or skipped; every "needs you" with its choices. When a mission completes and its run contract has `start` and `port`, the app is started from the mission's own files (before any Apply) and the link is posted there ("Try it before you Apply"); a library or command-line tool is left alone (`app_autorun_after_mission`, on by default). The chat panel checks for new messages and conversations every 4 s while nothing is being sent. Checked by tests with scripted missions in the real sandbox (progress, a failed feature and its need, the app started from the mission's folder with its link posted) | Writing updates with a model; one shared conversation for every mission | Decided with the user (D71) |
| D76 | **D71 step 4: model allocation from what the account measured (2026-11-21).** Each model in the catalog now carries, from this account's own call log (the latest 3,000 calls, matched by provider type and model so calls through the `.env` providers count too): calls, answered calls, median answer time, and the per-minute and per-day token limits the provider stated in its refusals (Groq: `(TPM): Limit 8000`, `(TPD): Limit 200000`). Each role has a load, its median and largest request (measured once it has 3 calls, otherwise a default from the first live missions: builders about 3,000 tokens and up to 6,000, the researcher up to 11,000). **Auto:** a model is a poor first choice for a role when its per-minute limit cannot hold two of the role's largest requests, it answered under half of at least 3 calls, or its median answer takes over 60 s; a model that works well on the account (reachable, D69, and not poor) wins over one that is not, even a better-rated one, and those passed over stay as later fallbacks; among equally good and equally priced models (two free ones) the team is spread over connections; models made for another job (names with guard, safety, embed, whisper, tts, rerank, moderation, clip, translate) are never given a role; each reason says, in plain words, the measured speed, the limit and whether it fits, and failures. The model list shows the same in brackets (`answers in ~4 s`, `limit 8,000 tokens/min`, `200,000 tokens/day`, `answered only 2 of 7 calls`). **Live, 2026-11-21:** Groq `gpt-oss-120b` 147 calls, 121 answered, ~9 s, 8,000 tokens a minute (too small for builders); free DeepSeek 33 of 33 in ~4 s; GLM on NVIDIA 2 of 7 in ~212 s; Kimi 18 of 27 in ~77 s. Auto (Balanced, saved over the earlier hand-made choices) now gives every role `deepseek-v4-flash:free` on Token Harbor with Groq's smaller models as fallbacks: one provider for everything, because no other free model on these keys works well; a second free provider key would let it spread. **Not done:** reading limits from rate-limit headers (only refusals are stored), a test call to measure a model before it is used | Probing every model; trusting ratings over measurements | Decided with the user (D71) |
| D77 | **A live Streamlit mission from idea to link, and the fixes it needed (2026-11-21).** Idea: a Streamlit calculator with `src/calc.py` and pytest tests. The PM (free DeepSeek) planned one milestone with three features (setup, arithmetic module, Streamlit screen) although the idea asked for one; reviewers were removed by hand for this check. After the fixes below it ended `completed`: the setup feature passed on its first new attempt, then the module and the screen each on their first, about 6 minutes in all; the mission's own conversation shows each feature building and done ("its tests passed in the sandbox") and the completion; the app was started from the mission's files and its link posted, and `http://localhost:8501` answered 200. Every model call went to free DeepSeek on Token Harbor ($0 priced cost). **Fixes, each with a test that fails without it:** (1) a check that timed out crashed while reading its partial output (subprocess gives bytes on a timeout even in text mode; joining str and bytes raised), so an install that ran long reported a crash instead of a timeout; (2) installs now get 600 s (other checks keep `sandbox_timeout_s`, 120 s): a Streamlit install took 143 s; (3) when the framework asked for a final text answer with no tools offered, free DeepSeek answered with tool calls and the attempt was lost; the app now asks once more, plainly, for the text (`FINAL_ANSWER_NOW`) and never hands a list on; (4) `load_skill(name, "SKILL.md")` (or `README.md`) returns the skill instead of an error; (5) **design flaw:** QA writes the milestone's acceptance tests before its features exist, and a plain `pytest` or `node --test` in an early feature also ran them and could never pass; the `test` check now runs with an empty folder covering `tests/acceptance` (QA's `acceptance` check still runs them); (6) a run with no tests now says so whatever its exit code (pytest: "no tests ran", exit 5) and tells the agent to add a test, where it said only "FAILED (exit 5)"; (7) the setup feature always includes one small passing test (PM rule and `project-layout`), and dependency files pin with `==` and never carry hashes (a model wrote made-up `--hash` lines and `pip` refused them) | Leaving QA's tests in every feature's test run; giving every check 600 s | Found by the live check the user asked for (2026-11-21) |
| D78 | **Starting any project from the chat, web or command line (2026-11-21).** "Run it" failed on projects without `.hex/project.json` (made before the run contract, or opened from elsewhere) with a message naming the missing file. (1) When there is no run contract, or one without a port, H.E.X works out how to start the project from its own files (`app/preview/guess.py`): Streamlit, FastAPI, Flask, a Node web server (express and similar, or code that calls `listen`), Vite, Next.js, or a plain `index.html` (served with Python's `http.server`). (2) A project that is none of these is a command-line program: "run it" runs it in the sandbox and the chat shows its output, and "run <arguments>" (for example `run 2 + 3`) passes them (`app/preview/cli_runner.py`). Arguments are quoted one by one so the shell reads none of them; the program gets no input and 60 s; the network is off, except that a project with dependencies installs them first through the usual allow-list proxy (600 s). No model is called. Checked live on the user's `live_calc_project`: `run 12 / 4` printed 3 | Asking the PM to write a run contract first; an interactive terminal (needs node-pty, not approved) | Asked by the user (2026-11-21) |
| D79 | **Open a terminal in the project's sandbox (2026-11-21).** The user wants to run built programs by hand, interactively. A chat button (and the words "open terminal") opens the computer's own terminal (Terminal on macOS, cmd on Windows, the desktop terminal on Linux) running a shell inside a sandbox container: the same hardening as the app runner (no capabilities, non-root, read-only root, limits), only the project folder mounted at /work, internet allowed for installs (as D71), no key or secret. It prints what to try first (for example `node index.js <arguments>`). No model is called. Checked live: "open terminal" on `live_calc_project` opened Terminal with the sandbox shell running | Running the program directly on the computer (generated code is untrusted); a terminal built into H.E.X (needs node-pty, not approved) | Asked by the user (2026-11-21) |
| D80 | **Ship-ready shell: logo, command palette, status bar, toasts, shortcuts, welcome (2026-11-21).** A logo (design/logo: a hexagon holding an H whose crossbar is a small hexagon; chosen over a honeycomb, a node network and a prompt mark because it alone reads at 16 px and in one colour) replaces the "HX" badge and is the app icon. ⌘K / Ctrl+K and ⌘⇧P open a command palette (views, project actions such as run app, open terminal, new mission, recent projects); ⌘1–9, ⌘O, ⌘J, ⌘L and ⌘, are shortcuts; a status bar shows the backend, the project and a running app's link; toasts confirm actions that happen out of sight; the welcome screen has three getting-started steps that tick themselves. The Team models table had grown wider than the screen (the model picker sized itself to its longest option) and now uses fixed columns. No new dependency | A VS Code-style menu bar; a theming system | Asked by the user (2026-11-21) |
| D81 | **Install on any computer (2026-11-21).** `npm run setup` (Node script, macOS/Windows/Linux) checks Node 20.12+, Git, uv and Docker, creates `.env` from `.env.example` with a random access token and database password (never printed, never overwrites an existing .env), installs both apps, starts the database, migrates, pulls the sandbox images and writes a per-user connection file (port and token only, no provider key) for the installed app; `npm start` runs backend and app together, `npm run backend` only the backend. `npm run package` builds an installer with electron-builder 26.18.1 (dev dependency, approved by the user): dmg, NSIS exe, AppImage, unsigned. The installed app serves its screens from `app://hexmind` (a privileged scheme, path-guarded to the renderer folder) so its requests carry an origin the backend allows by name; the backend always allows it, never the `null` origin that file:// pages send. Checked: the macOS dmg built, and the packaged app loaded and called the backend (all CORS preflights 200). License: MIT (user's choice). The installer holds the desktop app only; bundling the Python backend is left for P9 | Allowing the `null` origin; bundling Python (PyInstaller) now; signing (needs paid certificates) | Asked by the user (2026-11-21) |
| D82 | **Where H.E.X stands against 17 tools (2026-11-21).** research_notes/Agent coding tools gap analysis.md: H.E.X leads on a fixed role team with a model per role from any provider (measured Auto), QA acceptance tests and separate security review as the gate, apply-on-approval with sandboxed code, and per-call cost tracing; it trails on getting to a live URL. Gaps ranked for a non-technical user: publish to a URL (P9), live preview pane, bundled database and sign-in, browser tests with screenshots, image input, undo to a milestone, click-to-edit, templates, stuck-mission detection. None is built in this step; README lists them under Status | - | Research the user asked for (2026-11-21) |
| D83 | **Ideas, live team view, cleanup, New Folder (2026-11-22).** (1) A scoping session is saved the moment Start scoping is clicked but the screen dropped it when left, so a mission looked lost ("No missions yet"). The missions list now has a "Being planned" group (states: PM is planning, waiting for your answers, plan ready, stopped), reopened with a click, polled while the PM works. (2) The mission screen gets a team roster (one card per persona: state, a "now doing" sentence, elapsed clock, a "last activity N s ago" beat) and a drawer with that persona's steps, tokens and changed files; the live output is readable steps by default with the raw log one click away. Every line is derived from recorded events only (`features/missions/team.ts`); nothing is estimated (never-fabricate rule). The Observability page opens on an Overview (roster plus activity), hides the six developer tabs behind a "Developer details" switch and the Blackboard tab when the run has no board tasks (missions coordinate through the plan, not the board). (3) After Apply the mission's worktree and branch are removed (the work is a commit in the user's project; review reads that commit, Revert uses the apply record, re-applying after a revert rebuilds from the apply commit); a startup sweep clears copies left by older versions, only inside the app's own worktrees folder. (4) Apply no longer writes the team's working notes (`.hex/mission/`) into the user's project (`apply_mission_files` now false); the run contract `.hex/project.json` is always applied. (5) The folder picker offers New Folder (macOS `createDirectory`) and typing a new name (Windows `promptToCreate`) | Keeping every worktree forever; a separate page per agent | Asked by the user (2026-11-22) |
| D84 | **Hand a built project to the user (2026-11-22).** Research: `research_notes/Live agent progress UX.md`. On the user's click only, H.E.X (a) adds what a normal repository has and the agents do not always write: `.env.example` (names read from the code, no values), a GitHub Actions workflow built from the run contract's commands (Python or Node), Dependabot, `.streamlit/config.toml`, `.gitignore` entries for secrets and installs, README Developing and Deploy sections; never overwrites a file, one commit; (b) publishes with `gh repo create --source --push` using the user's own `gh auth login`, so H.E.X never sees a GitHub token. Publishing is refused when a tracked file looks like a secrets file or holds a provider key, when a file is over GitHub's 100 MB limit, when an `origin` remote exists, or when `gh` is missing or signed out (each with the plain fix); the repository is private by default and a public one needs the same explicit confirmation. Wording stays honest: the sandbox ran the commands, GitHub has not run CI yet. Deploy targets by stack are advice in the README and panel (Streamlit Community Cloud; Netlify, Vercel or Cloudflare Pages; Render or Cloud Run), not buttons: calling host APIs belongs to P9 | Pushing without asking; storing a GitHub token; deploy buttons now | Asked by the user (2026-11-22) |
| D85 | **Routing labels written by Claude (2026-11-22).** `docs/routing-labels.md` required labels from people, because a model labeling its own routing test would grade itself. The project owner asked for the labels to be written and labeled by Claude instead. 150 prompts (a developer's phrasing about to-do style apps; 40 question, 45 code_edit, 35 new_workflow, 30 clarification; 55 low, 56 medium, 39 high) were written to `data/labels-claude.csv` and imported as labeler `claude` (118 train, 32 test by the text-hash split). They follow the file's definitions, and ties go to the higher complexity as it says. Because no person labeled them, E6 results are reported as agreement with a model's labels, and the owner can add a human check by labeling at least 30 prompts under their own name and running `agreement claude <name>`. The scikit-learn baseline is still not built: it needs the owner's approval of the dependency (D62) | Public LLM-labeled datasets (other label schemes); the owner labeling all 150 | Asked by the user (2026-11-22) |
| D86 | **Final draft for the presentation: everything unbuilt moves to future scope (2026-11-22).** The owner closed the scope: no new features before the presentation. The README now has a "Status and future scope" section listing what is not built (cloud P9, publishing apps to a URL, live preview and image input, browser tests, built-in database and sign-in, plan approval and milestone undo, one run view for observability, bundled backend and signed installers, automatic Git setup and a direct-folder mode, the scikit-learn baseline and E2, E3, E6) with the reason and the research behind each; the same items are the deferred list in CLAUDE.md. Known limits are stated there too: the installer holds the desktop app only, only the macOS installer was tried, builds are unsigned, and the E6 labels were written by the assistant (D85) | Building more before the presentation | Asked by the user (2026-11-22) |

**Carried over (still valid):**
- Every model call goes through `ProviderRouter`.
- Agent claims aren't evidence: empty changes, zero-test checks and approval without accepted tasks are rejected.
- Worktree snapshots include uncommitted and untracked files.
- Native tool calling, with text-JSON tool-call recovery limited to offered tools.
- Lease heartbeats; a worker that loses its lease stops.
- The Router proposes; deterministic policy decides.
- The scikit-learn baseline, when built (D62), is for comparison only.

---

## 22. Open questions

| # | Question | Needed by |
|---|---|---|
| Q1 | Cloud deployment details (region, auth, cost limits, which services) | Start of P9 |
| Q2 | Which built-in skills to write vs import (for example a specific security-audit or UI/UX skill repo), and their licences | P6 |
| Q3 | First external agent to support via ACP (OpenCode, Claude Code, Gemini CLI) once grading is done | After P8 |
| Q4 | ~~ADK workflow agents or 2.x graph workflows for the MissionRunner~~ Resolved: D25 | — |
| Q5 | ~~Apply `.hex/` into users' projects by default?~~ Resolved: D26 | — |

---

## 23. Team and working rules

### 23.1 Ownership
H.E.X Mind is **Shrey Tiwari's project**; he owns every component and decision.

### 23.2 Working rules (for Claude Code and any contributor)
1. Read this PRD and inspect the repo before changing anything. Work **one phase at a time** (§18.1). Each phase ends in a working vertical slice.
2. Spike unfamiliar framework APIs before building on them. Re-run `spikes/adk_a2a/` after upgrading ADK, CrewAI or a2a-sdk.
3. Run all relevant tests, type checks and builds. **Report only verified results**, including failures.
4. Never run two pytest sessions at once.
5. Ask before adding significant dependencies or changing a decision in §21. Record changes in §21.
6. Don't commit or push without the user's go-ahead.
7. Don't create new planning `.md` files; update this PRD.
8. Never fabricate agent activity, metrics or results.

---

## 24. References

**Research behind this PRD (kept in the repo):** `research_notes/Multi agent coding project comparison/`
- `coding_agents.md`: edit formats, context, sandboxing, checkpoints, cheap-model strategies, benchmarks.
- `multi_agent_frameworks.md`: MetaGPT, ChatDev 2.0, AgentCoder, Agentless, MAST, ADK 2.x and CrewAI capabilities.
- `reliability_eval_safety.md`: execution-grounded repair, evaluation design, Rule of Two, routing and budgets, memory evidence.
- `observability.md`: OTel GenAI conventions, platform views, quick wins.
- `a2a_adk_ecosystem.md`: A2A 1.0 vs 0.3, ADK 2.0, Inspector comparison.
- `Multi agent coding project comparison.md`: the synthesis report and prioritized adoption list.

**Products and sources discussed:**
- T3 Code: <https://t3.codes/>, <https://github.com/pingdotgg/t3code>
- Orchestrator.inc agent-orchestrator: <https://github.com/OrchestratorInc/agent-orchestrator>
- Factory Droid Missions (talk slides reviewed in the design conversation): mission composition, serial vs parallel, structured handoffs, Mission Control, skills-driven orchestration.
- OpenCode (open-source coding agent; uses the models.dev catalog); models.dev: <https://models.dev>
- OpenRouter: <https://openrouter.ai>; NVIDIA API catalog: <https://build.nvidia.com>
- Agent Skills (`SKILL.md`) format; Model Context Protocol; Agent Client Protocol (ACP); A2A protocol: <https://a2a-protocol.org>
- MAST failure taxonomy: <https://arxiv.org/abs/2503.13657>; AgentCoder: <https://arxiv.org/abs/2312.13010>; Agentless: <https://arxiv.org/abs/2407.01489>; SWE-ContextBench: <https://arxiv.org/abs/2602.08316>
- Aider edit formats and leaderboards: <https://aider.chat/docs/more/edit-formats.html>
- Meta's Agents Rule of Two (via Simon Willison): <https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/>
