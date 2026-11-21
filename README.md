<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="design/logo/lockup-dark.png">
  <img src="design/logo/lockup-light.png" alt="H.E.X Mind" width="340">
</picture>

### Your AI software team, on your own computer.

Describe an idea. A PM plans it, engineers build it, QA and security check it in a sandbox,<br>
and you review the result before a single file of yours changes.

![License: MIT](https://img.shields.io/badge/license-MIT-6d73f2)
![Platforms](https://img.shields.io/badge/runs%20on-macOS%20·%20Windows%20·%20Linux-3a4256)
![Google ADK](https://img.shields.io/badge/orchestration-Google%20ADK-4285F4)
![CrewAI](https://img.shields.io/badge/agents-CrewAI-FF5A50)
![A2A](https://img.shields.io/badge/agents%20talk%20via-A2A-1F7A70)
![MCP](https://img.shields.io/badge/tools-MCP-2B3A67)

[What it does](#what-it-does) · [Install](#install) · [First mission](#your-first-mission) · [How it runs](#where-does-the-code-run) · [Architecture](#architecture) · [Agents](#the-agent-team) · [Scope and safety](#agentic-scope-and-safety) · [Compared](#how-it-compares) · [Status](#status-and-roadmap)

<br>

<img src="docs/images/project.webp" alt="H.E.X Mind with a project open: file explorer, Monaco editor and the agent chat, where the user ran a calculator in the sandbox" width="900">

</div>

---

## What it does

Most AI coding tools are one agent doing everything: planning, writing, and grading its own work. H.E.X Mind is a **team**. Each member has one job, its own model, its own skills, and nobody marks their own homework.

| You say | What happens |
|---|---|
| *"Build a Streamlit calculator with tests."* | The **PM** asks what it needs, then splits the idea into milestones and features with a contract for each. |
| | **Engineers** (backend, frontend, data, designer, DevOps) build each feature in an isolated copy of your project. |
| | **QA** writes acceptance tests from the contract *before* the code exists; **Reviewer** and **Security** check the diff. |
| | Every check (install, tests, acceptance) runs in a **Docker sandbox**. Results come from the sandbox and git, never from what an agent claims. |
| *"run it"* | H.E.X starts the app in the sandbox and posts a **localhost link** in the chat. A command-line program runs right in the chat: *"run 2 + 3"*. |
| *Apply* | Only now do your files change, in one commit you can revert. |

**Highlights**

- 🧠 **Any model, per team member.** OpenAI, Anthropic, Gemini, Groq, DeepSeek, Mistral, xAI, NVIDIA, OpenRouter, Ollama (local) or any OpenAI-compatible endpoint. **Auto** picks a model for each role from what *your* account can call, measured: free first, refused never, speed and rate limits shown.
- 🛡️ **Safe by default.** Agents work in a git worktree; generated code only runs in a hardened container; API keys never reach the sandbox, the UI, logs or git.
- 🔭 **Full observability.** A live team view (who is working on what, right now, from real events), agent topology (ADK → A2A → CrewAI), every model call with tokens, cost and latency, and a trace per run.
- 🧩 **Skills and plugins.** 28 built-in skills (SKILL.md), install more from GitHub (Claude and Codex skills work), and attach MCP servers per team member.
- ⌨️ **Feels like an IDE.** Monaco editor, file explorer, command palette (<kbd>⌘K</kbd> / <kbd>Ctrl+K</kbd>), keyboard shortcuts, status bar, a terminal into the project's sandbox.
- 📏 **Measured, not claimed.** A built-in evaluation harness (benchmark missions with hidden tests) to compare models and setups.

<table>
<tr>
<td width="50%"><img src="docs/images/next-steps.webp" alt="A finished mission: applied changes, Next steps to prepare the project for GitHub, publish it and deploy it, and the team cards"><br><sub><b>Mission screen.</b> Review, apply or revert; then Next steps: prepare the repository, publish to GitHub, deploy.</sub></td>
<td width="50%"><img src="docs/images/overview.webp" alt="Observability overview: every step of the run as a plain sentence with who did it"><br><sub><b>Live team view.</b> Who did what and when, from recorded events only. Developer tabs are one switch away.</sub></td>
</tr>
<tr>
<td><img src="docs/images/team.webp" alt="Team models: each persona with its model, chosen by Auto with the measured reason"><br><sub><b>Team models.</b> Auto explains each choice with what it measured on your account.</sub></td>
<td><img src="docs/images/topology.webp" alt="Observability topology: Google ADK orchestration reaching CrewAI crews over A2A"><br><sub><b>Topology.</b> Which framework did what: ADK orchestrates, CrewAI crews work, over A2A.</sub></td>
</tr>
<tr>
<td><img src="docs/images/agents.webp" alt="Agent editor: instructions and skills of the PM persona"><br><sub><b>Agents and skills.</b> Every team member's instructions, skills, plugins and model are editable.</sub></td>
<td><img src="docs/images/palette.webp" alt="Command palette listing views and actions with shortcuts"><br><sub><b>Command palette.</b> Every view, action and recent project, one keystroke away.</sub></td>
</tr>
</table>

---

## Install

H.E.X Mind runs on **macOS, Windows and Linux**. You need four free tools first:

| Tool | Why | Get it |
|---|---|---|
| **Node.js 20.12+** | the desktop app | [nodejs.org](https://nodejs.org) |
| **Git** | agents work in a git copy of your project | [git-scm.com](https://git-scm.com/downloads) |
| **uv** | runs the Python backend | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **Docker Desktop** (running) | the database and the sandbox | [docker.com](https://www.docker.com/products/docker-desktop/) |

Then:

```bash
git clone https://github.com/shreytiwari09/HEX-MIND.git
cd HEX-MIND
npm run setup     # checks the tools, creates .env with fresh secrets, installs, starts the database
npm start         # starts the backend and opens the app
```

`npm run setup` is safe to run again. It never overwrites your `.env` and never prints a secret.

**Prefer a normal app icon?** `npm run package` builds an installer for the computer you run it on (`.dmg` on macOS, `.exe` on Windows, `AppImage` on Linux) in `apps/desktop/release/`. The installer holds the desktop app; start the backend with `npm run backend` before opening it. Builds are not code-signed, so macOS asks you to confirm the first launch (right-click → Open).

**Add a model.** In the app: **Models & Keys → Connections**. Free keys from [Groq](https://console.groq.com) or [Google AI Studio](https://aistudio.google.com) are enough to start; [Ollama](https://ollama.com) runs models fully offline. Then **Team models → Auto → Apply**. Keys are stored in your operating system's key store, never in the repository.

## Your first mission

1. **Open a folder** (<kbd>⌘O</kbd>): an empty one for a new app, or an existing project.
2. **Missions → New mission.** Describe the idea in a few sentences. The PM may ask a question or two.
3. **Watch.** Progress appears in the mission screen and in its own chat conversation.
4. **Try it before you keep it.** When the mission ends, a web app starts automatically and its link appears in chat. Say *"run it"* any time, *"run 12 / 4"* for a command-line program, or *"open terminal"* for a shell in the sandbox.
5. **Review changes → Apply** (or Discard). Applied work is one commit; **Revert** undoes it. The team's working copy is deleted once you apply.
6. **Next steps** (on the mission screen): **Prepare for GitHub** adds `.env.example`, a CI workflow that runs your tests on every push, Dependabot and deploy notes; **Publish** creates a private GitHub repository with your own `gh` login (H.E.X never sees a GitHub token) and pushes it.

---

## Where does the code run?

**Everything runs on your computer.** There is no H.E.X server and no account.

```mermaid
flowchart LR
    subgraph PC["Your computer"]
        APP["H.E.X desktop app"] --> API["Backend<br/>(Python, localhost only)"]
        API --> DB[("Database<br/>PostgreSQL in Docker")]
        API --> SB["Sandbox<br/>Docker containers"]
        SB --> COPY["Copy of your project<br/>(git worktree)"]
        COPY -. "only when you click Apply" .-> YOURS["Your project folder"]
    end
    API -- "prompts + your key, HTTPS" --> LLM["Model providers<br/>(OpenAI, Groq, Gemini…)<br/>or Ollama on your machine"]
```

- **Your code** stays on your disk. The agents edit a *copy*; your folder changes only when you apply.
- **What leaves your computer** is only what a model needs to answer: the prompt (task, contracts, relevant file excerpts) sent to the provider *you* chose, with *your* key. With Ollama, nothing leaves at all. Per-project privacy settings can block hosted models entirely.
- **Generated code** runs only inside Docker containers: no root, no capabilities, read-only system, memory and process limits, only the project folder mounted, and no API keys. Tests run with no network; installs reach package registries only; apps you start can use the internet (like any app you run).
- **Apps it builds** open at `http://localhost:<port>`: reachable from your browser, not from your network.

### And "deploying to the cloud"?

Deploying means running those same parts on rented computers instead of yours, so you can use H.E.X from anywhere and leave missions running with your laptop closed. On **Google Cloud (GCP)** that would look like this (planned as phase P9; **not built yet**):

| Part | On your computer today | On Google Cloud |
|---|---|---|
| Backend | Python process on localhost | **Cloud Run** (a container Google starts on demand) |
| Database | PostgreSQL in Docker | **Cloud SQL** for PostgreSQL |
| Sandbox | Docker on your machine | Isolated **Cloud Run jobs / GKE** containers, one per check |
| Your projects | folders on your disk | a **Cloud Storage** bucket or git repository |
| Keys | OS key store | **Secret Manager** |
| Screen | the desktop app | the same app pointed at the cloud backend, or a web version |

The trade-offs: it costs money every month (database and compute), you need sign-in so only you can reach it, and your code then lives on Google's servers. Apps H.E.X builds could also be published to a public URL from there (with an explicit *Publish* step). Until then, H.E.X is local-first by design.

---

## Architecture

```mermaid
flowchart TB
    subgraph Desktop["Desktop app (Electron)"]
        UI["Editor · Explorer · Chat · Missions"]
        OBS["Observability · Metrics · Experiments"]
    end

    subgraph Backend["Backend (FastAPI, localhost)"]
        CHAT["Chat service<br/>Ask / Edit / Auto router · PM answers"]
        ADK["Google ADK workflow<br/>mission runner · scoping · handoffs"]
        PR["ProviderRouter<br/>every model call · keys · fallbacks · cost"]
        AUTO["Auto assigner<br/>measured speed · limits · failures"]
        APPS["App runner · CLI runner · terminal"]
        TEL["Telemetry<br/>events · spans · llm_calls"]
    end

    subgraph Crew["CrewAI crew service"]
        P["Personas: PM · engineers · QA · reviewer · security · researcher"]
    end

    MCP["MCP workspace tools<br/>path guard · skills · plugins"]
    WT["Git worktree<br/>(copy of the project)"]
    SB["Docker sandbox<br/>install · test · acceptance · run"]
    DB[("PostgreSQL<br/>missions · runs · events · calls")]
    LLM["Model providers<br/>or local Ollama"]

    UI -- "REST + token" --> CHAT
    UI --> ADK
    ADK -- "A2A (JSON-RPC)" --> P
    P --> MCP --> WT
    MCP -- "checks by name" --> SB --> WT
    CHAT --> PR
    P --> PR
    ADK --> PR
    AUTO --> PR
    PR --> LLM
    ADK --> TEL --> DB
    OBS --> TEL
    APPS --> SB
```

- **Two agent frameworks, one protocol.** Google ADK owns the mission workflow (deterministic steps and LLM agents); each persona is a CrewAI crew in a separate service, reached over **A2A**. Neither framework calls a model directly: every call goes through `ProviderRouter`, which picks the connection, applies fallbacks and rate-limit cooldowns, and records tokens, cost and latency.
- **MCP is the agents' only way to touch files.** Reads and writes are path-guarded to the worktree; checks run by *name* (`install`, `test`, `acceptance`) from the project's run contract, so an agent cannot run arbitrary commands on your machine.
- **Evidence over claims.** A feature is done when its checks pass in the sandbox; the changed files come from `git diff`, not from the agent's report.

### How a mission runs

```mermaid
sequenceDiagram
    autonumber
    actor You
    participant PM as PM (ADK + CrewAI)
    participant QA
    participant Eng as Engineer
    participant SB as Sandbox
    participant Val as Reviewer + Security

    You->>PM: idea
    PM-->>You: questions (if any)
    PM->>PM: milestones · features · contracts · run contract
    loop each milestone
        PM->>QA: validation contract
        QA->>SB: acceptance tests written first
        loop each feature
            PM->>Eng: feature + contract (+ skills)
            Eng->>SB: install · test (in the worktree)
            SB-->>PM: pass / fail with output
            PM->>Eng: retry with feedback, reassign or escalate
        end
        PM->>SB: acceptance check
        Val->>PM: findings on the milestone diff
    end
    PM-->>You: done · app link in chat · Review → Apply
```

---

## The agent team

| Member | Role | Skills it starts with | Writes code? |
|---|---|---|---|
| **PM / Tech Lead** | orchestrator | scoping interview, PRD writing, feature decomposition, API contracts, failure handling, escalation | plans and contracts only |
| **Researcher** | research | deep research, docs research (optional web search) | no |
| **Backend engineer** | worker | REST APIs, auth basics, backend testing | yes |
| **Frontend engineer** | worker | React UI, state and data fetching, frontend testing | yes |
| **Data engineer** | worker | relational schema design, migrations | yes |
| **Designer** | worker | UI/UX, accessibility, design tokens | yes (UI) |
| **DevOps (local)** | worker | run contract, Dockerfiles, project layout | yes (setup) |
| **QA engineer** | validator | acceptance testing | tests only |
| **Code reviewer** | validator | code review, contract conformance | no |
| **Security reviewer** | validator | security audit, secrets hygiene | no |

Every member is editable in **Agents**: instructions, skills, plugins (MCP servers), model and a per-mission budget. You can add your own personas.

## Agentic scope and safety

**What the agents can do**

- Read and write files **inside the mission's worktree** (a git copy of your project).
- Run the project's named checks (`install`, `test`, `acceptance`, `typecheck`, `lint`) **in the sandbox**.
- Load skills and call the MCP plugins you attached to them.
- Search the web, only the Researcher and only when you turn on *Advanced research*.

**What they cannot do**

- Touch your project folder (that takes your *Apply*), or any path outside the worktree.
- Run arbitrary shell commands on your computer, see your API keys, or reach the network from tests.
- Mark their own work done: completion is decided by sandbox results and validators.

**Where you stay in charge**

- Answering the PM's scoping questions, and approving its plan before the team builds.
- *Needs* the team raises (a missing key, a decision) wait for you.
- Review → Apply / Discard / Revert. Budgets per persona and per mission stop spending.

Third-party skills and plugins are treated as untrusted: they are scanned, shown before install, and run with the same limits.

---

## How it compares

A November 2026 survey of 17 tools ([full report with sources](research_notes/Agent%20coding%20tools%20gap%20analysis.md)):

| | H.E.X Mind | App builders (Lovable, Bolt, Replit, v0) | Cloud agents (Devin, Copilot agent, Cursor, OpenHands) | IDE / CLI agents (Claude Code, Cline, Aider, Kiro) |
|---|---|---|---|---|
| Fixed team of roles, model per role from any provider | ✅ | ❌ | ❌ | partly (subagents) |
| QA writes acceptance tests first; separate security review | ✅ | ❌ | ❌ | ❌ |
| Your files change only on approval; code runs in a sandbox | ✅ | hosted copy | branch / PR | varies |
| Per-call tokens, cost and latency | ✅ | credits | partly | partly |
| Runs locally, no account | ✅ | ❌ | ❌ | ✅ |
| Live preview pane, visual edits | ❌ (localhost link) | ✅ | partly | partly |
| One-click publish to a public URL | ❌ (planned, P9) | ✅ | Cursor only | ❌ |
| Built-in database, sign-in, payments | ❌ | ✅ | ❌ | ❌ |

## Status and future scope

**Built and tested:** 1,029 backend tests and 301 desktop tests pass; phases P1 to P8 of the [PRD](PRD.md) (missions, team models with Auto, skills and plugins, observability, metrics, the evaluation harness), plus a live team view, a terminal into the project's sandbox, running web apps and command-line programs from chat, and one-click preparation and publishing to GitHub. Real missions have run end to end on free models. The macOS installer has been built and opened; the Windows and Linux installers use the same configuration but have not been tried on those systems.

**Known limits today:** the installer holds the desktop app only (start the backend with `npm run backend`); missions need Git, which H.E.X offers to set up; builds are unsigned; the routing experiment (E6) uses 150 labels written by the assistant, not by people ([D85](PRD.md)).

### Future scope

Everything below is deliberately **not built yet**. Each item has a reason in the [PRD](PRD.md) and the research in [`research_notes/`](research_notes/).

| Area | Planned | Why it matters |
|---|---|---|
| **Cloud (phase P9)** | Run the backend, database and sandbox on Google Cloud (Cloud Run, Cloud SQL, Secret Manager) with sign-in, a spending cap and a domain; missions that keep running with the laptop closed | Use H.E.X from anywhere; needs billing and sign-in decisions first |
| **Publishing apps** | One-click deploy to a public URL (Streamlit Community Cloud, Vercel, Netlify, Cloud Run) after an explicit Publish step | Today H.E.X pushes to GitHub and explains deploying; the five app builders in the [comparison](research_notes/Agent%20coding%20tools%20gap%20analysis.md) all host the app |
| **Preview** | A live preview pane inside the app and click-to-change on it; image, screenshot and Figma input for the designer | The biggest visible gap for non-technical users |
| **Verification** | Browser tests by QA with screenshots as proof (Playwright); stuck-run detection with automatic replanning | Stronger proof that the app works |
| **Batteries included** | A database and sign-in that work without setting up accounts; payments; vetted starter templates | Today the user wires these up |
| **Workflow** | Plan approval as an editable spec; undo to a milestone; best-of-N attempts per feature; resume or fork a run from a checkpoint; later missions as pull requests | Finer control and safer iteration |
| **Observability** | One run view with tree, timeline and graph sharing a selection; a graph that lights the active agent from recorded events; a built-in terminal | See [Live agent progress UX](research_notes/Live%20agent%20progress%20UX.md) |
| **Install** | Bundle the Python backend into the installer; code signing for macOS and Windows; auto-update; automatic Git setup; an opt-in "work directly in my folder" mode with the sandbox kept for running code | One download that just runs |
| **Evaluation** | The scikit-learn baseline and experiment E6 (needs approval of the dependency and, ideally, a human check of the labels); experiments E2 and E3; an LLM judge | Measured, reproducible results |

---

## Development

```bash
npm start                 # backend + desktop app (from source)
npm run dev:backend       # backend only (FastAPI on 127.0.0.1:$HEXMIND_PORT)
npm run dev               # desktop app only
npm test                  # desktop + backend tests
npm run typecheck && npm run lint:backend
npm run package           # installer for this OS
```

```
apps/desktop/    Electron main (window, app:// protocol), preload (3 calls), React renderer
apps/backend/    FastAPI: orchestration (ADK), agents (CrewAI), a2a, providers, router,
                 mcp_server, sandbox, workspace, missions, catalog, telemetry, evaluation
design/logo/     logo, app icon and lockups (SVG + PNG)
docs/standards/  coding standards the agents load at runtime
PRD.md           product requirements and every decision (§21)
```

Hard rules for contributors are in [CLAUDE.md](CLAUDE.md): CrewAI and Google ADK only, every model call through `ProviderRouter`, keys never leave the backend, generated code is untrusted.

## License

[MIT](LICENSE) © 2026 Shrey Tiwari
