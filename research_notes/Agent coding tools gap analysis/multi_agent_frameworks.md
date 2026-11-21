# Role-based multi-agent software-development frameworks (state as of 2026-11-21)

Scope: MetaGPT (and MGX, now Atoms), ChatDev (1.0 and 2.0 "DevAll"), GPT-Pilot / Pythagora, Microsoft AutoGen and Magentic-One (and Microsoft Agent Framework), CrewAI (crews and Flows for software work). Compared against H.E.X Mind as described in the assignment. GitHub numbers come from the GitHub API, queried 2026-11-21 (`gh api repos/<repo>`). Items marked [older] predate 2026.

## Q1. Orchestration patterns and how each one verifies work

### Takeaway
Three families exist. The first is fixed SOP or waterfall pipelines where roles exchange documents (MetaGPT, ChatDev 1.0, GPT-Pilot). The second is an orchestrator-worker setup with a dynamic ledger and replanning (Magentic-One, now the "Magentic" pattern in Microsoft Agent Framework). The third is general-purpose graph or flow engines with no built-in software team (ChatDev 2.0, Agent Framework workflows, CrewAI Flows). Checking the work is weak everywhere. MetaGPT runs unit tests with at most 3 retries. ChatDev relies on reviewer and tester dialogue. GPT-Pilot has a per-step Reviewer plus Troubleshooter and Debugger loops with a human tester. Magentic-One checks for stalls through its progress ledger. None has acceptance-test gating per feature together with separate security and review validators, as H.E.X has.

### Cited Findings
**MetaGPT** [older paper; repo still public]
- Philosophy "Code = SOP(Team)". Roles: product manager, architect, project manager, engineer — [GitHub MetaGPT](https://github.com/FoundationAgents/MetaGPT)
- The paper adds a QA Engineer. Roles talk through a **shared message pool with publish/subscribe** and exchange structured documents (PRD with user stories, competitive analysis and requirement pool; system design with file lists, data structures and interfaces; sequence diagrams; task lists), not free chat — [arXiv 2308.00352v7](https://arxiv.org/html/2308.00352v7)
- Verification ("executable feedback"): after writing code, the Engineer writes and runs unit tests, debugs, and retries up to 3 times — [arXiv 2308.00352v7](https://arxiv.org/html/2308.00352v7)
- The paper describes the SOP as an "assembly line paradigm" that lets agents verify intermediate results — [arXiv abstract](https://arxiv.org/abs/2308.00352)
- Related research from the same group: AFlow (automated workflow generation, ICLR 2025 oral), SPO and AOT (Feb 2025), and the Data Interpreter agent — [GitHub MetaGPT](https://github.com/FoundationAgents/MetaGPT)

**MGX → Atoms (the commercial version of MetaGPT, by DeepWisdom)**
- MGX launched in February 2025 and was #1 Product of the Day and of the Week on Product Hunt in March 2025 — [GitHub MetaGPT](https://github.com/FoundationAgents/MetaGPT)
- Rebranded as **Atoms on 2026-01-13**. It is positioned for "production-ready apps" and "vibe business" (market research, payments, deployment) — [KrASIA](https://kr-asia.com/from-metagpt-to-atoms-deepwisdom-leads-chinas-push-into-vibe-coding); [DataLearner](https://www.datalearner.com/en/blog/metagpt-rebrands-atoms-ai-business-building)
- Atoms says it is "built on MetaGPT, refined by MGX" — [atoms.dev/metagpt](https://atoms.dev/metagpt)
- Eight named agents: Mike (team lead), Iris (deep researcher), Emma (PM), Bob (architect), Alex (engineer), Sarah (SEO), David (data analyst), Adrian (ads). Mike passes outputs between specialists, sequences the work and "pauses at approval points" — [Atoms team leader page](https://atoms.dev/ai-agents/team-leader-agent); [Atoms agents](https://atoms.dev/nl/ai-agents)
- **Race Mode**: best-of-N parallel attempts across models, and the user picks the winner. Vendor claim: about 45% higher quality at a fixed budget, or up to 80% lower cost at a fixed quality, on its own RealDevWorld benchmark (194 projects) — [Atoms blog](https://atoms.dev/blog/introduce-race-mode)

**ChatDev 1.0** [older] and **ChatDev 2.0**
- 1.0 is a "virtual software company" (CEO, CTO, Programmer, reviewer, tester) that moves through phases (design → coding → testing) along a **chat chain**. "Communicative dehallucination" makes agents ask for details before answering. The paper was accepted at ACL 2024 — [arXiv 2307.07924](https://arxiv.org/abs/2307.07924)
- Additions to 1.0 during 2023-2024: Human-Agent-Interaction mode where a human acts as reviewer (Sep 2023), Git mode (Sep 2023), Docker support for safe execution (Oct 2023), **incremental development on existing code** (Nov 2023), Experiential Co-Learning and Iterative Experience Refinement (2024), MacNet graph networks of agents (Jun 2024), "Puppeteer" learned orchestrator (NeurIPS 2025) — [ChatDev README](https://raw.githubusercontent.com/OpenBMB/ChatDev/HEAD/README.md)
- **ChatDev 2.0 "DevAll" released 2026-01-07**: a zero-code, general multi-agent platform, "no longer limited to software development". Workflows are written in YAML or built on a drag-and-drop Vue canvas; custom Python tools; Python SDK (`chatdev` on PyPI); human feedback from the Launch tab. The 1.0 software company was moved to the `chatdev1.0` branch, and MacNet and Puppeteer each live on their own branch — [ChatDev README](https://raw.githubusercontent.com/OpenBMB/ChatDev/HEAD/README.md); [x-cmd blog](https://x-cmd.com/blog/260110)

**GPT-Pilot / Pythagora**
- Roles: Product Owner, Specification Writer (asks clarifying questions), Architect (picks and installs technologies), Tech Lead (writes the tasks), Developer (describes each task), Code Monkey (implements it), **Reviewer** (checks each step and sends faulty work back), **Troubleshooter** (helps the user give useful bug feedback), **Debugger**, Technical Writer — [GitHub gpt-pilot](https://github.com/Pythagora-io/gpt-pilot)
- Pattern: code is built **task by task with review loops**, not all at once. The human acts as tester and can step in to fix code. The CLI can resume from the latest step or from a specific step (later progress is deleted) — [GitHub gpt-pilot](https://github.com/Pythagora-io/gpt-pilot)

**AutoGen / Magentic-One / Microsoft Agent Framework (MAF)**
- Magentic-One agents: **Orchestrator**, WebSurfer, FileSurfer, Coder, ComputerTerminal — [arXiv 2411.04468](https://arxiv.org/html/2411.04468)
- **Task ledger** (outer loop) holds facts (given, to look up, to derive), educated guesses and a plan. **Progress ledger** (inner loop) asks each turn whether the task is done, whether the team is looping, whether progress is being made, who acts next and with what instruction. A **stall counter** (threshold ≤2 in the experiments) sends control back to the outer loop to replan, and agents' contexts are reset — [arXiv 2411.04468](https://arxiv.org/html/2411.04468)
- Agents can be added or removed without further prompt tuning — [arXiv abstract](https://arxiv.org/abs/2411.04468)
- MAF 1.0 GA was announced **2026-04-03** for .NET and Python. Stable orchestrations: sequential, concurrent, handoff, group chat, Magentic-One. All support streaming, **checkpointing**, **human-in-the-loop approvals** and pause/resume. Other features: middleware hooks, MCP, A2A (A2A 1.0 "coming soon" at GA), memory backends (Foundry, Mem0, Redis, Neo4j), declarative YAML agents and workflows, DevUI debugger (preview), OpenTelemetry through Foundry (preview), an Agent Harness with shell and filesystem access (preview) — [MAF 1.0 blog](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/)
- In MAF's Magentic pattern a manager plans, assigns work to specialists and replans when progress stalls; `max_*` settings act as guardrails. A blog post dated 2026-07-08 says the orchestration patterns reached 1.0 in both SDKs (Python package `agent-framework-orchestrations` 1.0.0) — [MAF orchestrations 1.0](https://devblogs.microsoft.com/agent-framework/agent-frameworks-orchestration-patterns-reach-1-0)

**CrewAI (the framework H.E.X uses)**
- There is **no official software-development crew template**. The `crewai-examples` repo is archived (GitHub API, 2026-04-20). The Flows docs list examples such as Email Auto Responder, Lead Score, Write a Book and Meeting Assistant, none of them for coding — [CrewAI Flows docs](https://docs.crewai.com/en/concepts/flows)
- Software-development crews in the wild are community tutorials, usually a sequential engineer → QA-review chain — [Medium tutorial](https://medium.com/algomart/automating-workflows-and-code-generation-with-crewai-in-python-dbcfdff844b0); [WorkOS blog](https://workos.com/blog/how-to-build-a-game-building-agent-system-with-crewai)
- Flows: `@start`, `@listen`, `@router`, `or_`/`and_`; structured Pydantic state; `@persist` (SQLite by default) with resume by id and fork via `restore_from_state_id`; **`@human_feedback`** (CrewAI ≥1.8), where an LLM maps free-text feedback to routed outcomes; async feedback through Slack or webhooks — [CrewAI Flows docs](https://docs.crewai.com/en/concepts/flows)
- Agent options: `max_iter` (default 20), `max_rpm`, `max_execution_time`, `respect_context_window` (summarizes when the context is full), `reasoning` (plans before acting), `allow_delegation`, `multimodal`, `guardrail` — [CrewAI Agents docs](https://docs.crewai.com/en/concepts/agents)

### Inferences
- H.E.X's mission → milestone → feature structure with QA acceptance tests is closest to GPT-Pilot's task-by-task loop and MetaGPT's SOP documents. Its validator agents (reviewer, security) add something neither has: a separate security role.
- The ledger ideas in Magentic-One (stall counter, "are we looping?" check, replanning) are the clearest pattern H.E.X could borrow for recovering a mission that has stalled.

### Gaps
- I did not find a published MetaGPT, ChatDev 2.0 or CrewAI benchmark that verifies its software end to end with acceptance tests comparable to H.E.X's.
- The MAF Magentic docs page itself was not read; checkpoint and approval behavior is taken from the blog posts.

## Q2. What they have that H.E.X lacks, and where H.E.X is ahead

### Takeaway
Ideas worth borrowing: incremental development on an existing codebase (ChatDev, GPT-Pilot), a human as tester inside the debugging loop and resume from any step (GPT-Pilot), stall detection and replanning (Magentic-One), best-of-N parallel attempts across models (Atoms Race Mode), experience reuse across runs (ChatDev co-learning), checkpointing with pause/resume and approval gates as framework primitives (MAF, CrewAI Flows), and visual or YAML workflow editing (ChatDev 2.0, MAF). H.E.X looks ahead on: one router for all providers with per-persona models and a measured Auto assigner; a git worktree with changes applied only on approval; a Docker sandbox for acceptance checks; security and reviewer validators; traces with tokens, cost and latency; and a built-in evaluation harness. None of the open-source frameworks offers all of these together for software building.

### Cited Findings
- ChatDev 1.0 had **incremental development**, a **human-as-reviewer** mode, **Git mode** and **Docker** execution in 2023 [older] — [ChatDev README](https://raw.githubusercontent.com/OpenBMB/ChatDev/HEAD/README.md)
- ChatDev Experiential Co-Learning and Iterative Experience Refinement carry shortcuts learned in past runs into new runs [older] — [ChatDev README](https://raw.githubusercontent.com/OpenBMB/ChatDev/HEAD/README.md)
- GPT-Pilot: a Troubleshooter helps the human report bugs, a Debugger handles failures, and the user can resume from a chosen step. The README notes that large tasks give buggy code and very narrow tasks fit poorly into existing code — [GitHub gpt-pilot](https://github.com/Pythagora-io/gpt-pilot)
- Magentic-One: stall counter and replanning. The authors recommend "least privilege and maximum oversight", pausing for human input before costly or irreversible actions, and using humans in the loop to cut cost by reducing stuck iterations — [arXiv 2411.04468](https://arxiv.org/html/2411.04468)
- Atoms: best-of-N Race Mode across models; Mike pauses at approval points — [Atoms blog](https://atoms.dev/blog/introduce-race-mode); [Atoms team leader page](https://atoms.dev/ai-agents/team-leader-agent)
- MAF: checkpointing and hydration, HITL approvals, pause/resume, middleware for safety and logging, DevUI live view of message flows and tool calls — [MAF 1.0 blog](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/)
- CrewAI: `@persist` resume and fork, `@human_feedback` routing, per-agent `max_rpm`, `max_iter` and `max_execution_time` limits — [CrewAI Flows docs](https://docs.crewai.com/en/concepts/flows); [CrewAI Agents docs](https://docs.crewai.com/en/concepts/agents)
- **CrewAI deprecated built-in code execution.** `allow_code_execution` and `code_execution_mode` are deprecated, `CodeInterpreterTool` was removed from `crewai-tools`, and the docs point to E2B or Modal sandboxes — [CrewAI Agents docs](https://docs.crewai.com/en/concepts/agents)
- MetaGPT says its own limits are UI and front-end work (no UI agents or multimodal tools) and complex real-world requirements — [arXiv 2308.00352v7](https://arxiv.org/html/2308.00352v7)
- The MAF 1.0 post describes no code-execution sandbox; the Agent Harness gives shell and filesystem access (preview) with no mention of a sandbox — [MAF 1.0 blog](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/)

### Inferences
- H.E.X's own Docker sandbox fits where CrewAI is heading (outside sandboxes). Its git worktree with apply on approval is stronger than ChatDev's Git mode and GPT-Pilot, which write straight into the project.
- Cost: Magentic-One reports "several US dollars, and tens of minutes per task", and none of the profiled frameworks documents a hard per-run budget limit. If H.E.X adds a per-mission cost cap on top of its cost traces, that would set it apart. (I did not check whether H.E.X already has one.)
- Clear gaps to consider for H.E.X: (1) stall and loop detection with automatic replanning; (2) best-of-N per feature using the multi-provider router; (3) resume or fork a mission from any checkpoint; (4) memory of past missions carried into new ones; (5) a Troubleshooter-style flow that turns the user's bug reports into structured feedback.

### Gaps
- I could not verify whether Atoms exposes cost limits, traces or a sandbox; only marketing pages were found.
- I found no source on hard per-run cost caps in MetaGPT or ChatDev 2.0. MetaGPT has historically had an `investment` budget setting, but I did not confirm it in current docs.

## Q3. Benchmarks reported and known weaknesses

### Takeaway
None of these frameworks reports a SWE-bench result in its primary sources. MetaGPT reports HumanEval and MBPP plus its own SoftwareDev set. Magentic-One reports GAIA, AssistantBench and WebArena (general agent tasks, not software building). Atoms cites its own RealDevWorld benchmark. ChatDev 2.0, GPT-Pilot and CrewAI report no software benchmarks.

### Cited Findings
- MetaGPT: **HumanEval Pass@1 85.9%, MBPP 87.7%**. Executable feedback adds +4.2 and +5.4 points. SoftwareDev: executability 3.75 vs ChatDev 2.25 (on a 4-point scale), 0.83 vs 2.5 human revisions, 31,255 vs 19,292 tokens. The paper gives two different running times for MetaGPT (503 s and 541 s) [older, paper v7 Nov 2024] — [arXiv 2308.00352v7](https://arxiv.org/html/2308.00352v7)
- Magentic-One (GPT-4o + o1): **GAIA 38%** test, **AssistantBench 27.7%** accuracy, **WebArena 32.8%** (GPT-4o). These are "statistically competitive" with the state of the art at the time [older, Nov 2024]. Cost is about several US dollars and tens of minutes per task — [arXiv 2411.04468](https://arxiv.org/html/2411.04468)
- Observed Magentic-One risks: repeated login attempts until an account was suspended, followed by a password-reset attempt; accepting terms of service on its own; trying to recruit humans (social posts, emailing authors); trying to reach the real Reddit — [arXiv 2411.04468](https://arxiv.org/html/2411.04468)
- Atoms RealDevWorld (194 projects) is a vendor benchmark, not independently verified — [Atoms blog](https://atoms.dev/blog/introduce-race-mode)
- A third-party review gives Atoms about 7/10 and says the agents "drift on edge cases"; Race Mode, code export and custom domains are paid-only (pricing as of May 2026) — [Sonary review](https://sonary.com/b/atoms/atoms-ai-agent+ai-tools/)
- ChatDev 2.0 README reports no benchmark results — [ChatDev README](https://raw.githubusercontent.com/OpenBMB/ChatDev/HEAD/README.md)

### Inferences
- HumanEval and MBPP are function-level and close to saturated. They do not test multi-file app building, which is what H.E.X does. H.E.X's E1-E6 harness (mission-level, with acceptance tests from the sandbox) measures something these frameworks largely do not publish.
- The risk list from Magentic-One supports H.E.X's path guard, permissions, sandbox and apply-on-approval design.

### Gaps
- I found no SWE-bench (Verified or Lite) result for MetaGPT, ChatDev, GPT-Pilot, AutoGen, MAF or CrewAI in primary sources.
- I found no independent 2026 evaluation of ChatDev 2.0 or of MAF's Magentic pattern on coding tasks.

## Q4. Status as of November 2026: maintained, archived or commercialized?

### Takeaway
MetaGPT's open-source repo has been quiet since January 2026 while the company focuses on the commercial Atoms. ChatDev is active, but it is now a general platform and the software company is a legacy branch. GPT-Pilot is unmaintained, and its repo had a credential-stealing worm in it from August 2025 to June 2026; pythagora.ai now redirects to an unrelated business-builder product (Pazi). AutoGen is archived and Microsoft Agent Framework 1.0 replaces it. CrewAI is very active (release 1.15.44 on 2026-11-19), but its examples repo is archived and it has no official software-development template.

### Cited Findings
- **MetaGPT**: 71.4k stars; last commit 2026-01-21; last GitHub release v0.8.1 (2024-04-22); not archived — GitHub API (`repos/FoundationAgents/MetaGPT`), queried 2026-11-21; [GitHub MetaGPT](https://github.com/FoundationAgents/MetaGPT)
- **MGX → Atoms**: commercial, rebranded 2026-01-13 — [KrASIA](https://kr-asia.com/from-metagpt-to-atoms-deepwisdom-leads-chinas-push-into-vibe-coding)
- **ChatDev**: 34.8k stars; last commit 2026-10-30; latest release v2.2.0 (2026-03-23); 2.0 released 2026-01-07; there was a SaaS version in Nov 2023 [older] — GitHub API (`repos/OpenBMB/ChatDev`); [ChatDev README](https://raw.githubusercontent.com/OpenBMB/ChatDev/HEAD/README.md)
- **GPT-Pilot**: README says "This repo is not being maintained anymore". **Security notice: malicious credential-stealing code sat in `core/telemetry/` from August 2025 until 11 June 2026**, and users who ran it from source should rotate their credentials. 33.6k stars; last commit 2026-06-12; no releases — [GitHub gpt-pilot](https://github.com/Pythagora-io/gpt-pilot); GitHub API (`repos/Pythagora-io/gpt-pilot`)
- **Pythagora**: `pythagora.ai` returns 301 → `pazi.ai`, an AI business-builder ("Make the thing. Sell the thing.") whose site does not mention Pythagora or coding agents — [pythagora.ai](https://www.pythagora.ai/) → [pazi.ai](https://pazi.ai/) (fetched 2026-11-21)
- **AutoGen**: maintenance mode announced 2025-10-02 — [AutoGen discussion #7066](https://github.com/microsoft/autogen/discussions/7066)
- **AutoGen is now archived**: `archived=true` in the GitHub API, and the README says "Project archived and no longer maintained… not providing bug fixes, security fixes, new features, or support", advises against production use, and points to MAF and the [migration guide](https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/). 62.0k stars; last release python-v0.7.5 (2025-09-30) — GitHub API and README of `microsoft/autogen`, 2026-11-21
- **Microsoft Agent Framework**: GA 1.0 on 2026-04-03; orchestration patterns 1.0 by 2026-07-08. A Go SDK repo (`microsoft/agent-framework-go`) was pushed 2026-11-20 — [MAF 1.0 blog](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/); [MAF orchestrations 1.0](https://devblogs.microsoft.com/agent-framework/agent-frameworks-orchestration-patterns-reach-1-0); GitHub API search
- **CrewAI**: 61.1k stars; latest release 1.15.44 (2026-11-19); last commit 2026-11-21. `crewAIInc/crewAI-examples` is archived (last push 2026-04-20) — GitHub API (`repos/crewAIInc/crewAI`, `repos/crewAIInc/crewAI-examples`)

### Inferences
- H.E.X pins `crewai 1.15.28`, and upstream is at 1.15.44. Given that code execution was deprecated, check that H.E.X does not depend on `allow_code_execution` or `CodeInterpreterTool`. (H.E.X uses its own Docker sandbox, so it probably does not, but this was not verified here.)
- H.E.X uses Google ADK, not AutoGen, so AutoGen being archived does not affect it directly. MAF is now the main Microsoft alternative and shares A2A and MCP with H.E.X's stack.
- The pattern across these projects: the original open-source "AI software company" projects have either gone commercial (MetaGPT → Atoms), become general platforms (ChatDev 2.0), or been abandoned (GPT-Pilot). That leaves room for an open, local-first desktop tool with real verification, which is H.E.X's position.

### Gaps
- `gh api repos/microsoft/agent-framework` returned 404 on 2026-11-21, even though Microsoft's posts and the AutoGen README link to that URL. It may be renamed, moved or an API glitch; unresolved. Its stars and commit activity were not retrieved.
- I found no official Pythagora shutdown or pivot announcement. The Pazi link rests only on the redirect.
- I did not retrieve Atoms usage numbers or pricing for 2026 from a primary source.
