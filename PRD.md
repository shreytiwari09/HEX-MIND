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
| Workspace (7) | ✅ `list_files`, ✅ `read_file`, ✅ `search_code`, ✅ `write_file`, ✅ `replace_in_file`, `delete_file`, `move_file` |
| Git (3) | `git_status`, `git_diff`, `git_log` (worktree-scoped, read-only) |
| Checks (2) | ✅ `run_check` (run-contract commands by name), `list_checks` |
| Mission (2) | `get_feature_context` (feature, contracts, earlier handoffs), `list_features` |
| Knowledge (2) | `load_skill`, `search_standards` (ChromaDB coding standards and verified lessons) |

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
- **Kept as is:** path guard, worktrees and snapshots, the sandbox runner, the MCP server and bridge, the Blackboard (claims, leases, reaper), the event log with gap-free `seq`, TelemetryHub (ADK + CrewAI callbacks), the A2A server and client with traceparent, the A2A explorer, `ProviderRouter` (retry, fallback, cooldown, `llm_calls`, pricing), `HexAdkLlm` / `HexLLM`, Groq pseudo-tool-call salvage, the context manager, redaction, the Router + policy + scikit-learn baseline, the 14-task benchmark, and the Electron security setup.
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
| 1 | State sharing: Blackboard vs messaging | Two coordination backends for missions (§9.8), compared in E4 | Blackboard ✅; messaging planned | P7, P8 |
| 2 | Tools via MCP (16 tools) | H.E.X MCP server, 16 tools (§12.6), plus user plugins as MCP servers | 6/16 ✅ | P5–P6 |
| 3 | Structured output (Pydantic) | Router decision, MissionPlan, Handoff, ValidatorReport, guardrail verdicts, Persona, catalog, events, API models; one repair retry | ✅ (extended each phase) | all |
| 4 | Agentic design patterns, compared | Six patterns incl. P-mission and P-parallel (E1, E2) | 2 built ✅ (sequential, reflection) | P3, P8 |
| 5 | Monitoring via callbacks | All 8 ADK + CrewAI callbacks → TelemetryHub → live views | ✅ (CrewAI event bus to finish) | P3–P7 |
| 6 | A2A between ADK and CrewAI | ADK MissionRunner ↔ CrewAI persona crew service; traceparent; A2A explorer; reverse direction for the QA → Reviewer hand-off | ✅ one direction | P3, P5 |
| 7 | Only CrewAI + ADK | §12.2; external CLIs future and off in the graded build | ✅ | — |
| 8 | Guardrails + prompt variants | Layered guardrails (§13.2); persona instruction and orchestration skill variants with ids on every call (E5) | Partly ✅ | P5–P6 |
| 9 | Observability: tracing, audit, provenance | OTel spans across A2A, hash-chained audit, feature-level provenance, delegation log, views | Event log ✅ | P7 |
| 10 | End-to-end evaluation (cost, time, prompt variance) | Runner, benchmarks, E1–E6, dashboard (§15) | 14-task benchmark ✅ | P8 |
| 11 | Cloud deployment | **H.E.X backend on Google Cloud** (§18.2, P9); details decided with the user at that phase | Planned | P9 |
| + | Original brief: scikit-learn baseline, ≥40 runs across providers, PEAS metrics | E6, E3, §15.4 | Baseline ✅ | P8 |

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
| **P5 Planning & validation** | Mission discipline | PM scoping chat; PRD, contracts, validation contract; **plan review + approval**; run contract + per-project hardened sandbox; scrutiny, security and QA validators (acceptance tests + Playwright user testing); research subagents; preview pane; edit-format layer; repo map; MCP tools to 16 | 2, 6, 8 | A builder goes from idea to approved plan to validated app; a deliberate bug is caught by a validator, retried, escalated and fixed |
| **P6 Skills & plugins** | User-built engineers | Skill registry (built-in, folder, GitHub); `load_skill`; persona panel with skill and plugin dropdowns; custom personas; plugin manager with permissions + approvals; orchestration-strategy skills; prompt/skill variant registry; input guardrails; privacy modes | 2, 8 | Adding "motion-graphics" to the Designer changes its output in the next mission; a risky plugin is blocked until approved |
| **P7 Observability & state sharing** | Prove and explain | Messaging backend; OTel export; trace explorer; hash-chained audit + verify; feature-level provenance; metrics dashboard; Needs-you notifications; resume after restart | 1, 5, 9 | The same mission runs on both backends; the audit chain verifies; any changed file traces back to persona, model, skill and approval |
| **P8 Evaluation** | Measured results | Mission benchmark; runner; E1–E6; report and experiment dashboard | 10, 1, 4, 8 | Reproducible, dated report browsable in the app |
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

**Carried over (still valid):**
- Every model call goes through `ProviderRouter`.
- Agent claims aren't evidence: empty changes, zero-test checks and approval without accepted tasks are rejected.
- Worktree snapshots include uncommitted and untracked files.
- Native tool calling, with text-JSON tool-call recovery limited to offered tools.
- Lease heartbeats; a worker that loses its lease stops.
- The Router proposes; deterministic policy decides.
- The scikit-learn baseline is kept for comparison only.

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
