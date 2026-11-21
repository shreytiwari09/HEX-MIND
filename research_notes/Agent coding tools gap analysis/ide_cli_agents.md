# IDE- and terminal-based coding agents (Claude Code, Aider, Cline, Roo Code, Kiro) vs H.E.X Mind

Researched 2026-11-21 from official docs. "Not confirmed" means the fetched official page did not cover it.

## UX features that make these tools feel professional (command palette, diff review, checkpoints, plan mode, inline edits, terminal, shortcuts, notifications, cost display)

### Takeaway
The common baseline is now: a read-only plan mode, visual diff review with a way to comment or reject, checkpoints that roll back files and/or conversation, a built-in terminal, an in-app browser preview of the running app, OS notifications when a task finishes, and keyboard-first navigation. H.E.X has none of checkpoints, plan-mode toggle, in-app terminal, in-app preview or command palette.

### Cited Findings
**Claude Code (CLI, VS Code, JetBrains, Desktop, Web, mobile)**
- Runs on terminal, IDE extensions (VS Code/Cursor, JetBrains), a desktop app and the web; the VS Code extension gives "inline diffs, @-mentions, plan review, and conversation history" — [Overview](https://code.claude.com/docs/en/overview)
- Permission modes: Manual, Accept edits, Plan ("explores and proposes a plan without editing source code"), Auto (a background classifier checks actions before they run), Bypass permissions; switched with Shift+Tab in CLI or a mode selector in Desktop — [Desktop](https://code.claude.com/docs/en/desktop.md); [Permission modes](https://code.claude.com/docs/en/permission-modes.md)
- Desktop diff review: per-line comments (click + beside a line number), submit all with Cmd/Ctrl+Enter and Claude produces a new diff; in Manual mode "you see a diff and can accept or reject each change". No per-hunk accept control is documented in the diff view — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Desktop Browser pane: Claude starts the dev server (config in `.claude/launch.json` with command and port) and opens it in an in-app Browser pane; auto-verify takes screenshots, inspects the DOM and fixes issues — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Desktop integrated terminal (Ctrl+`), opens in the session's working directory with the same environment as Claude; built-in file editor with autosave — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Desktop sends an OS notification when a session finishes and you are not viewing it — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Keyboard shortcuts in Desktop: Cmd+/ lists them; Cmd+Shift+D diff pane, Cmd+Shift+B browser pane, Cmd+N new session, Ctrl+Tab switch, Option-click for split view; CLI keybindings are customizable via a config file — [Desktop](https://code.claude.com/docs/en/desktop.md); [Keybindings](https://code.claude.com/docs/en/keybindings.md)
- Checkpoints: every prompt creates a checkpoint (last 100 kept, persists across resume); `/rewind` or Esc Esc offers Restore code and conversation / conversation only / code only / Summarize from here / up to here. Limits: Bash-only file changes and most subagent edits are not restored; "not a replacement for version control" — [Checkpointing](https://code.claude.com/docs/en/checkpointing.md)
- Cost/usage: Desktop shows context-window % and a plan-usage ring, not dollar cost; CLI has a customizable status line for context usage, costs and git status, and a costs guide with team spend limits — [Desktop](https://code.claude.com/docs/en/desktop.md); [Status line](https://code.claude.com/docs/en/statusline.md); [Costs](https://code.claude.com/docs/en/costs.md)
- PR monitoring in Desktop: "Auto-fix" failing checks/review comments and "Merge when ready" (needs `gh`) — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Parallel sessions with optional git worktree isolation (off by default in Desktop; `.worktreeinclude` copies gitignored files like `.env`) — [Desktop](https://code.claude.com/docs/en/desktop.md); [Worktrees](https://code.claude.com/docs/en/worktrees.md)
- Chrome integration to test web apps, read console logs, automate forms — [Chrome](https://code.claude.com/docs/en/chrome.md)

**Cline (VS Code extension, CLI, Desktop, Kanban)**
- Plan & Act: Plan "lets you explore and strategize without changing files"; Act executes; option "Use different models for Plan and Act"; `/deep-planning` command explores the codebase and asks clarifying questions — [Plan & Act](https://docs.cline.bot/core-workflows/plan-and-act.md)
- Checkpoints via a shadow git repo committed after each tool use (captures untracked files); Restore Files / Restore Task Only / Restore Files & Task; Compare opens the editor's diff viewer — [Checkpoints](https://docs.cline.bot/core-workflows/checkpoints.md)
- Every action requires approval by default; auto-approve is configurable; browser use; CLI with headless mode for CI; ACP for Neovim; Desktop app with parallel sessions and scheduled tasks; Kanban board running many agents in per-card worktrees with auto-commit and dependency chains — [Docs home](https://docs.cline.bot/); [Auto-approve](https://docs.cline.bot/features/auto-approve.md); [Kanban](https://docs.cline.bot/usage/kanban.md)
- Enterprise: SSO, RBAC, remote config, observability integrations — [Docs home](https://docs.cline.bot/)

**Aider (terminal, optional browser UI)**
- Auto-commits every edit with an LLM-written Conventional Commit message (weak model); `/undo` discards the last change, `/diff` shows changes since last message, `/commit`; dirty files are committed separately first; commits marked "(aider)" in author/committer — [Git](https://aider.chat/docs/git.html)
- Watch mode responds to "AI comments" written in any IDE; voice-to-code; images and web pages in chat; auto lint/test-and-fix loop; browser UI — [Docs](https://aider.chat/docs/)
- Latest numbered release v0.86.1 (GPT-5 reasoning-effort); main branch adds newer Claude/Gemini/GPT-5.x models and a `/ok` approve shortcut; the history page gives no dates — [History](https://aider.chat/HISTORY.html)

**Kiro (IDE, CLI, Web)**
- Checkpoints: "Undo agent changes or fork a conversation"; Permissions page controls agent access; CLI with headless mode and CI; Web agent for multi-repo tasks that opens PRs — [Kiro docs](https://kiro.dev/docs/)
- Spec review UI: a floating Review button lets you comment on exact passages of a spec ("Markdown Review") and send comments to Kiro — [Specs](https://kiro.dev/docs/specs/)
- Autopilot vs Supervised mode (supervised presents changes for approval) is described in third-party write-ups, not in the official pages fetched — [AWS re:Post article](https://repost.aws/articles/AROjWKtr5RTjy6T2HbFJD_Mw); [AWS Builder Center](https://builder.aws.com/content/3DWagLjqsjIIIJ9evVne8P4ZbD6/kiro-specs-stop-improvising-and-start-planning-features-with-ai)

**Roo Code**
- **Shut down**: "The Roo Code Extension was shut down on May 15th" (docs last updated 2026-05-15); points users to the ZooCode community fork and Cline — [Roo Code docs](https://roocodeinc.github.io/Roo-Code/)
- Had customizable Modes (Architect, Code, etc.), Orchestrator ("Boomerang") mode that coordinates work across modes, auto-approve, MCP, many providers — [Roo Code docs](https://roocodeinc.github.io/Roo-Code/) (historical)

### Inferences
- "Professional feel" in 2026 = (1) safe undo (checkpoints with file/conversation granularity), (2) explicit plan step before edits, (3) reviewable diffs with comments, (4) app preview and terminal inside the window, (5) notifications plus a shortcut sheet. H.E.X's apply-on-approval from a worktree is a coarser version of (1)+(3).
- Cost display is uneven: Claude Code Desktop shows plan usage, not dollars; H.E.X's per-call tokens/cost/latency traces are more detailed than any of these show by default (no source shows equivalent per-persona cost dashboards in these tools).

### Gaps
- Not confirmed whether Claude Code Desktop, Cline or Kiro offer a VS Code-style command palette of their own (Cline/Roo inherit VS Code's; Kiro is a VS Code fork per third-party sources, not confirmed on fetched pages).
- Cline per-hunk diff acceptance and cost-per-task display not confirmed on fetched pages (older Cline versions showed per-task cost; not reverified).
- Kiro diff review UI details and pricing not fetched.

## Agent architecture: subagents, modes, hooks, spec documents, memory files

### Takeaway
All tools have converged on: persistent instruction files (CLAUDE.md / AGENTS.md / steering / rules), skills (packaged instructions), MCP, lifecycle hooks, and subagents for parallel or context-isolated work. Kiro is unique in making requirements/design/tasks documents first-class and executing tasks in dependency waves. None uses a fixed team of role personas with per-role models the way H.E.X does; Cline's per-mode model and Roo's modes were the closest.

### Cited Findings
**Claude Code**
- Five parallel styles: subagents (own context, return a summary), agent view (`claude agents`, background sessions, research preview), agent teams (lead + teammates with shared task list and messaging; "Experimental and disabled by default"; teammates are not worktree-isolated), projects (long-running cloud threads, public beta), dynamic workflows (a script runs many subagents and cross-checks results). "In every approach the workers are Claude sessions" — [Run agents in parallel](https://code.claude.com/docs/en/agents.md)
- `/batch` skill splits a large change into 5 to 30 worktree-isolated subagents; cross-session messaging between sessions — [Run agents in parallel](https://code.claude.com/docs/en/agents.md)
- Custom subagents are defined as files with restricted tools — [Subagents](https://code.claude.com/docs/en/sub-agents.md)
- Memory: CLAUDE.md read every session, reads AGENTS.md instead if present, plus auto memory that saves learnings across sessions — [Overview](https://code.claude.com/docs/en/overview); [Memory](https://code.claude.com/docs/en/memory.md)
- Hooks run shell commands on events (edit files, finish task, need input); skills package workflows as slash commands; plugins bundle these and install from marketplaces (`marketplace.json`) — [Hooks guide](https://code.claude.com/docs/en/hooks-guide.md); [Skills](https://code.claude.com/docs/en/skills.md); [Plugins](https://code.claude.com/docs/en/plugins/overview.md); [Marketplaces](https://code.claude.com/docs/en/plugins/anthropic-marketplaces.md)
- Sandboxed Bash tool (restrict files and network hosts); options include dev containers, Docker, VMs — [Sandboxing](https://code.claude.com/docs/en/sandboxing.md); [Sandbox environments](https://code.claude.com/docs/en/sandbox-environments.md)
- Scheduled tasks in the cloud (cron, API, GitHub events), desktop scheduled tasks, `/loop`; Agent SDK for custom agents; GitHub Actions/GitLab CI; Slack — [Overview](https://code.claude.com/docs/en/overview); [Routines](https://code.claude.com/docs/en/routines.md)
- Third-party providers supported on CLI, VS Code, JetBrains (Bedrock/Vertex etc.), but models are Claude — [Overview](https://code.claude.com/docs/en/overview)

**Kiro**
- Specs: requirements.md (user stories + acceptance criteria) or bugfix.md, design.md (architecture, sequence diagrams, error handling, testing strategy), tasks.md (discrete trackable tasks). Feature specs come in Requirements-First and Design-First variants; Quick Spec runs "without approval gates"; "Run all tasks" builds a dependency graph and runs independent tasks concurrently in waves — [Specs](https://kiro.dev/docs/specs/)
- EARS ("WHEN ... SHALL") notation for acceptance criteria, files under `.kiro/specs/` — [AWS re:Post](https://repost.aws/articles/AROjWKtr5RTjy6T2HbFJD_Mw) (third-party)
- Steering: `.kiro/steering/` with product.md, tech.md, structure.md included by default; global `~/.kiro/steering/`; inclusion modes always / fileMatch / manual (`#filename`) / auto (by description); AGENTS.md always included — [Steering](https://kiro.dev/docs/steering/)
- Hooks: 17 triggers — Prompt Submit, Agent Stop, Session Start, Agent Spawn, Session End, Pre/Post Compaction, Pre Tool Use, Permission Request, Post Tool Use, File Create, File Save, File Delete, Pre/Post Task Execution, Manual, Legacy Manual — [Hook types](https://kiro.dev/docs/hooks/types/)
- Hook actions: shell command (JSON on stdin, 60 s default timeout) or agent prompt injected into the conversation; PreToolUse can block tool calls — [Hooks](https://kiro.dev/docs/hooks/)
- Also: Powers (tools with built-in knowledge that activate on demand), skills, custom agents, subagents for parallel tasks, MCP, model selection — [Kiro docs](https://kiro.dev/docs/)

**Cline**
- Rules (`.clinerules`-style coding standards), skills, slash-command workflows, subagents ("parallel research agents ... without filling the main agent's context window"), hooks via SDK plugins, Memory Bank (structured docs to keep context across sessions), MCP — [Rules](https://docs.cline.bot/customization/cline-rules.md); [Skills](https://docs.cline.bot/customization/skills.md); [Subagents](https://docs.cline.bot/features/subagents.md); [Hooks](https://docs.cline.bot/customization/hooks.md); [Memory Bank](https://docs.cline.bot/best-practices/memory-bank.md)
- BYOK or Cline credits/ClinePass; SDK exposes the agent core — [Docs home](https://docs.cline.bot/)

**Aider**
- Chat modes code / architect / ask / help (architect = planning model + editor model); repo map for context; multiple edit formats; conventions file; connects to most LLMs — [Docs](https://aider.chat/docs/); [Modes](https://aider.chat/docs/usage/modes.html)
- No subagents, hooks, MCP or skills found in fetched docs.

### Inferences
- H.E.X is architecturally ahead on role specialisation: persona teams (PM, researcher, backend, frontend, designer, QA, security, reviewer, DevOps) with per-persona models from any provider and an Auto assigner that measures speed/limits/failures. Claude Code's workers are all Claude; Cline only splits models between Plan and Act; Aider splits architect/editor.
- Kiro's spec trio maps directly onto H.E.X missions/milestones/features; Kiro adds reviewable spec documents with inline comments and approval gates, and wave-parallel task execution. H.E.X could expose its PM plan as editable requirements/design/tasks docs.
- Lifecycle hooks (pre/post tool use, file save, agent stop) are standard in Claude Code and Kiro; H.E.X has no user-defined hooks (inferred from the brief).
- Steering-style inclusion modes (always/fileMatch/manual/auto) are a richer version of H.E.X's per-persona skills; H.E.X's per-persona skill scoping is something none of these tools offer as directly.

### Gaps
- Claude Code hook event list not fetched in full (see [Hooks reference](https://code.claude.com/docs/en/hooks.md)).
- Whether Kiro subagents/custom agents can use different models per agent not confirmed.
- Roo Code's full built-in mode list (Ask, Debug) not confirmed on the current (post-shutdown) page.

## What they have that H.E.X lacks, and where H.E.X is ahead

### Takeaway
H.E.X lacks checkpoints/rewind, a plan-mode toggle, inline diff comments/hunk review, an in-app terminal and app preview, notifications, a command palette/shortcut sheet, inline completions, image input, browser automation, user hooks, and CI/headless/scheduled runs. H.E.X leads on multi-provider per-persona teams with a measuring model assigner, Docker sandboxing of generated code by default, full per-call observability, and an Ask/Edit/Auto request router.

### Cited Findings
- Checkpoints with file + conversation restore exist in Claude Code ([Checkpointing](https://code.claude.com/docs/en/checkpointing.md)), Cline ([Checkpoints](https://docs.cline.bot/core-workflows/checkpoints.md)), Kiro ([Kiro docs](https://kiro.dev/docs/)); Aider uses git `/undo` ([Git](https://aider.chat/docs/git.html)).
- In-app preview with auto-verify via screenshots/DOM, and integrated terminal: Claude Code Desktop — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Browser automation: Cline browser use ([Docs home](https://docs.cline.bot/)); Claude Code Chrome ([Chrome](https://code.claude.com/docs/en/chrome.md))
- Image input: Aider ([Images & web pages](https://aider.chat/docs/usage/images-urls.html))
- Headless/CI: Claude Code GitHub Actions, GitLab CI, `-p` piping ([Overview](https://code.claude.com/docs/en/overview)); Cline CLI headless ([Docs home](https://docs.cline.bot/)); Kiro CLI headless ([Kiro docs](https://kiro.dev/docs/))
- Scheduled/background runs: Claude Code routines and desktop scheduled tasks ([Routines](https://code.claude.com/docs/en/routines.md)); Cline Desktop scheduled tasks ([Desktop](https://docs.cline.bot/usage/cline-desktop.md))
- Classifier-based permission: Claude Code's Auto mode uses "a background classifier [that] checks actions before they run" — a safety classifier, distinct from H.E.X's request-routing classifier — [Desktop](https://code.claude.com/docs/en/desktop.md)
- Sandboxing in Claude Code is a configurable Bash sandbox, with Docker/VM as options rather than default — [Sandbox environments](https://code.claude.com/docs/en/sandbox-environments.md)
- Worktree isolation is opt-in in Claude Code Desktop ("By default, Worktree is off") — [Desktop](https://code.claude.com/docs/en/desktop.md); H.E.X always uses worktrees with apply-on-approval (per the brief).

### Inferences
- Highest-value gaps for H.E.X (cheap to add, large perceived polish): checkpoints per mission step (H.E.X already has worktrees + git, so rewind could be git-based like Cline's shadow repo), a Plan toggle that stops before edits, per-line diff comments routed back to the persona, OS notifications on mission completion, and an in-app terminal/preview pane (preview pane is already deferred per D41/D45).
- H.E.X's differentiators to emphasise: heterogeneous multi-provider persona team, measured Auto model assignment, sandbox-by-default for generated code, and observable per-persona tokens/cost/latency. No fetched source shows any of the five tools offering per-agent cost/latency traces at that level.

### Gaps
- No head-to-head benchmarks found comparing these tools' output quality.
- Inline completions: none of the fetched pages for these five tools document tab completions (they are agentic chat tools); not verified for Kiro.

## Deployment of generated apps

### Takeaway
None of the five tools deploys generated apps to hosting as a built-in feature; they stop at running locally (Claude Code Desktop preview), opening PRs, and merging. Deployment is done through MCP servers, skills (e.g. a user-written `/deploy-staging`), or CI.

### Cited Findings
- Claude Code: skills such as "`/review-pr` or `/deploy-staging`" are user-authored; PR creation, Auto-fix CI and "Merge when ready" are built in — [Overview](https://code.claude.com/docs/en/overview); [Desktop](https://code.claude.com/docs/en/desktop.md)
- Claude Code Desktop runs the dev server and previews it in-app; also opens iOS apps in a Simulator pane — [Desktop](https://code.claude.com/docs/en/desktop.md); [iOS simulator](https://code.claude.com/docs/en/desktop-ios-simulator.md)
- Kiro Web "plans, implements, and opens PRs"; enterprise deployment page covers deploying Kiro itself, not user apps — [Kiro docs](https://kiro.dev/docs/)
- Cline Kanban workflow ends at "reviewing changes, and shipping" with auto-commit — [Kanban core workflow](https://docs.cline.bot/kanban/core-workflow.md)

### Inferences
- H.E.X's "run the app with a localhost link in chat" is at parity with the best local story (Claude Code Desktop preview) except that it lacks an in-app preview and auto-verification by screenshot. Planned P9 cloud deployment would be a differentiator versus these tools, which leave hosting to the user.

### Gaps
- Not checked whether Kiro Powers or Cline marketplace include first-party deploy integrations (e.g. AWS/Vercel); Kiro being an AWS product suggests AWS deployment Powers may exist, but no source fetched confirms it.
