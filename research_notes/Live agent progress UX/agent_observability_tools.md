# Agent observability and tracing tools: how they show multi-agent runs (as of Nov 2026)

Scope: LangSmith, Langfuse, Arize Phoenix/AX, AgentOps, CrewAI AMP, Google ADK web, OpenAI Agents SDK traces, Microsoft Agent Framework DevUI, W&B Weave, Datadog; plus OpenSearch Agent Traces as a clear reference for linked views. Docs found by search and fetched 2026-11-22. Where a page did not say something, that is in Gaps. Many vendor docs describe the UI only roughly; treat third-party sources (marked) as weaker.

## Q1. Which 3 to 5 views do the tools share, and how are they laid out?

### Takeaway
The tools share five views: (1) a **run list** (sessions, threads or conversations), (2) a **span tree** with a **details panel** for the selected span, (3) a **timeline or waterfall** (Gantt-style), (4) an **agent graph**, and (5) a **summary of tokens, cost and time**, both for the whole run and per step. The usual layout is a list, then a run-detail page with a left/right split: tree or waterfall on the left, details of the selected step on the right. Tree, Timeline and Graph sit on that page as switchable tabs or toggles, not as top-level pages. The tools split pages by *unit of analysis* (session, then trace, then span) and never by *data source* (callbacks, A2A, schema checks).

### Cited Findings
- **Langfuse**: the trace detail page has **Tree, Timeline and Graph** tabs side by side — [Langfuse agent graphs](https://langfuse.com/docs/observability/features/agent-graphs). The graph is built automatically from observation timing and nesting once a trace contains agentic observation types — [same](https://langfuse.com/docs/observability/features/agent-graphs). July 2026: a rebuilt graph with an **Aggregated** mode (one node per step name, with a counter such as `retrieve_docs (3/3)`; loops show as cycles; "shows an agent's overall shape") and an **Expanded** mode (one node per call, unrolled in execution order, "closer to the trace tree", for following one run). The layout is deterministic and the feature is in beta — [Langfuse changelog 2026-07-13](https://langfuse.com/changelog/2026-07-13-graph-view-modes). Original graph view shipped Feb 2025 — [changelog 2025-02-14](https://langfuse.com/changelog/2025-02-14-trace-graph-view).
- **LangSmith**: rows in the Threads, Traces and Runs tabs open a **side panel** with three views: **Trajectory** (`T`, conversation-style blocks), **Turns**, and **Details** (`D`, the default: inputs, outputs, timing, tokens, errors, metadata) — [LangSmith view traces](https://docs.langchain.com/langsmith/view-traces). Traces can also be shown as a **waterfall** to examine latency and to see parallel versus sequential execution (changelog, undated) — [LangSmith changelog](https://changelog.langchain.com/announcements/ann_t0pJcFOimB0OD). Sept 2026 blog introduces **Trajectories** for viewing threads and scoring them — [LangChain blog](https://www.langchain.com/blog/langsmith-trajectories-tracing).
- **CrewAI AMP** (enterprise): the Traces tab lists runs by date. A run page has four sections: **Execution Summary** (total, prompt and completion tokens, requests, execution time, estimated cost), **Tasks & Agents** (each task's agent, LLM, status completed/failed, and time), **Execution Timeline** ("when each task started and ended… bottlenecks or parallel execution"), and **Final Output**. Clicking a task opens a detail view: status (completed/running/failed), agent, LLM, start, end, duration, description, expected output, input from earlier tasks, and output — [CrewAI AMP traces](https://docs-platform.crewai.com/platform/en/features/traces). This is a single scrolling page of panels, not tabs.
- **AgentOps**: a **Session Drawer** of past sessions; a **Session Summary** with total time, SDK/framework version, LLM calls as "a familiar chat history view", and charts of event types and durations; a **Session Waterfall** with "a time visualization of all your LLM calls, Action events, Tool calls, and Errors" on the **left** and details of the selected event (exact prompt and completion) on the **right**; and a **Session Overview** across all sessions — [AgentOps dashboard](https://docs.agentops.ai/v2/usage/dashboard-info).
- **W&B Weave** (Agents view, public preview): tabs **Dashboard / Agents / Conversations / Spans / Signals**. Agents is a card grid; each card shows conversations, spans, cost, average latency and error rate. A Conversations row opens a detail panel with **Turns** and **Events** sub-panels. Selecting a Spans row opens a **waterfall**. "Show trace tree" shows the hierarchy — [Weave view agent activity](https://docs.coreweave.com/weave/guides/tracking/view-agent-activity). The classic trace tree can switch between **default, code composition, flame graph and graph** views from the top right — [Weave trace tree](https://docs.wandb.ai/weave/guides/tracking/trace-tree).
- **Arize AX / Phoenix**: an **Agent Graph** plus an **Agent Path** ("animated walkthrough") built from the `graph.node.id` and `graph.node.parent_id` span attributes, or inferred from nesting. It shows "which agents call which, where loops happen, and which paths lead to failures" — [Arize agent trajectory](https://arize.com/docs/ax/observe/tracing-concepts/agent-graphs); [Arize agents](https://arize.com/docs/ax/observe/tracing/agents). Phoenix OSS: a trace tree with the selected span's input and output, and **Sessions** that "group related traces into conversations" — [Phoenix tracing](https://arize.com/docs/phoenix/tracing/llm-traces).
- **Datadog**: an interactive **execution graph** mapping each agent's "inputs, tool invocations, calls to other agents and outputs". Clicking an agent shows "which tools an agent used, execution time, and any errors or retries". Datadog argues that span lists become hard to read for dynamic multi-agent runs (deep nesting, unclear paths) — [Datadog blog: monitor AI agents](https://datadoghq.com/blog/monitor-ai-agents). Flame graphs for span hierarchy — [Datadog LangGraph monitoring](https://datadoghq.com/blog/langgraph-agent-monitoring). Docs: "visualize agent decisions, such as tools used or agent a task was handed off to" — [Datadog agent monitoring](https://docs.datadoghq.com/llm_observability/monitoring/agent_monitoring).
- **OpenAI Agents SDK**: traces are made of typed spans (`agent_span`, `generation_span`, `function_span`, `guardrail_span`, **`handoff_span`**, plus optional task and turn spans). `group_id` links traces of one conversation — [OpenAI Agents tracing](https://openai.github.io/openai-agents-python/tracing/). That docs page does not describe the dashboard layout.
- **Google ADK web** (`adk web`): a chat interface, session management, state inspection and editing, event history, and a Visual Builder (Python). The Go docs mention "Traces and agent structure panels" and "the agent structure graph view" — [ADK web interface](https://adk.dev/runtime/web-interface/). Third-party: chat on the right, the left pane holds invocation logs with timing bars (`invoke_agent`, `execute_tool`) — [KodeKloud notes (secondary)](https://notes.kodekloud.com/docs/Google-ADK/Introduction/ADK-Web-Interface/page).
- **Microsoft Agent Framework DevUI**: a dev-only sample app. It does not create spans; it shows the framework's OpenTelemetry spans in a **debug panel** next to chat. The trace timeline shows hierarchy and timing; workflow traces show "the execution path through executors" — [MS DevUI tracing](https://learn.microsoft.com/en-us/agent-framework/devui/tracing). A Microsoft announcement describes a preview "Agent Inspector" with a navigable tree and pause/replay (not confirmed in docs) — [Microsoft release comms](https://www.microsoft.com/releasecommunications/api/v2/azure/563551).
- **OpenSearch Agent Traces** (reference design): three views, **Agent Graph** (Dagre DAG; each node shows a category badge, name, duration bar, and an ERR badge), **Trace tree** (badge, name, tokens, latency per row; collapsible), and **Timeline** (Gantt, indented by depth). "**All three views share the same selection state**". Color by operation: agent blue, LLM orange, tool purple, retrieval red, other gray, used the same way in graph, minimap and timeline — [OpenSearch agent graph](https://observability.opensearch.org/docs/ai-observability/agent-tracing/graph/).

### Inferences
- The tools converge on this model: **one run page with a selection shared across tree, timeline and graph, plus a details drawer**. H.E.X Mind's tabs Callbacks, Schema checks, A2A, Messages and Trace are slices of the same events by source. In the converged model they would be filters or span types inside one run view, not separate tabs.
- The two-mode graph (Aggregated for structure, Expanded for one run) fits H.E.X Mind's static Topology tab: Topology is the Aggregated view. The Expanded view of the current mission is what is missing.
- CrewAI AMP's single-page summary (tasks and agents table, timeline, final output, cost header) is the closest match to a mission page a non-expert could read.

### Gaps
- No fetched official docs describe LangSmith's or OpenAI's dashboard layout in detail (only span types and side-panel views).
- ADK web's tab names (Events, Trace, State, Artifacts, Sessions, Eval) and whether clicking an event highlights the graph node are not documented on adk.dev. Running `adk web` or reading google/adk-web would confirm it.

## Q2. How do they show a live run?

### Takeaway
Live display is the least documented part. Most of these tools are **after-the-fact trace viewers**. Live behavior shows up mainly in dev UIs that pair chat with traces: ADK web streams tokens next to the event log, and DevUI shows a debug panel beside chat. In trace products it is limited to a per-task "running" status (CrewAI). None of the fetched docs describe the graph highlighting the active agent. The live patterns that *are* documented: a chat or transcript on one side with a growing event or timing list on the other, status badges (running/completed/failed), and error badges on nodes.

### Cited Findings
- CrewAI AMP task status includes "completed, running, or failed". No auto-refresh or live view is described — [CrewAI AMP traces](https://docs-platform.crewai.com/platform/en/features/traces).
- ADK web: "send messages to agents and view responses in real time", plus a token streaming toggle — [ADK web interface](https://adk.dev/runtime/web-interface/); [KodeKloud (secondary)](https://notes.kodekloud.com/docs/Google-ADK/Introduction/ADK-Web-Interface/page).
- DevUI shows spans in a debug panel during dev runs. Without an OTLP endpoint, traces stay local — [MS DevUI tracing](https://learn.microsoft.com/en-us/agent-framework/devui/tracing).
- Langfuse's graph docs say nothing about live updates for running traces — [Langfuse agent graphs](https://langfuse.com/docs/observability/features/agent-graphs).
- Arize "Agent Path" is an **animated walkthrough** of a finished path, i.e. replay rather than live — [Arize agents](https://arize.com/docs/ax/observe/tracing/agents).
- MS preview "Agent Inspector" lists **pause and replay** of runs (announcement only) — [Microsoft release comms](https://www.microsoft.com/releasecommunications/api/v2/azure/563551).
- Error visibility on the node itself: OpenSearch "ERR" badge — [OpenSearch](https://observability.opensearch.org/docs/ai-observability/agent-tracing/graph/); Weave inline **ERROR** badge on failed tool calls, with failed events in red in the Events strip — [Weave](https://docs.coreweave.com/weave/guides/tracking/view-agent-activity).

### Inferences
- For a non-expert watching live, the tools give no ready-made "active agent glows" pattern to copy. Building one would be H.E.X Mind's own design, driven by real events: the node lights only on a real start event and settles on a real end or error event, never on a simulated timer.
- Replay of a finished run (Arize Agent Path; MS pause/replay) is a good after-the-fact tool and could reuse the same graph component.

### Gaps
- I found no official, fetched source for live node highlighting in LangGraph Studio, ADK web or any trace product. LangGraph Studio is widely believed to highlight the running node, but I did not verify it in this pass.

## Q3. How do they handle many events?

### Takeaway
Six techniques recur: **hierarchy with collapse**, **grouping of repeated or parallel calls**, **aggregation of repeated steps into one counted node**, **color by span or event type**, **filter and search** (by name, agent, model, error, attributes), and **turn or conversation grouping** above the raw spans.

### Cited Findings
- LangSmith: repeated or parallel tool calls "collapse into one grouped row" that you can expand. Thought blocks are collapsed by default. Turn cards have a chevron. Subagents open as nested views with a way back to the parent. Search on the table; selecting text gives Add filter / Exclude / Replace all filters. "Find in loaded content" warns when a query matches more than 1,000 times. `ls_agent_type` marks root versus subagent runs — [LangSmith view traces](https://docs.langchain.com/langsmith/view-traces).
- Langfuse Aggregated mode merges same-named steps into one node with a count — [Langfuse changelog](https://langfuse.com/changelog/2026-07-13-graph-view-modes).
- Weave: turns numbered with counts of intermediate responses and tool calls and the duration; tool calls expand to Args and Result; long responses collapse automatically. Filter by agent, model, error status and custom attributes; column filters; time windows of 1m to 30d; sort agents by most errors and similar. Events colored: user purple, assistant green, tool blue, error red — [Weave](https://docs.coreweave.com/weave/guides/tracking/view-agent-activity). Trace tree has "Filter by op name" — [Weave trace tree](https://docs.wandb.ai/weave/guides/tracking/trace-tree).
- OpenAI: `include_task_and_turn_spans=False` drops wrapper spans to cut noise — [OpenAI Agents tracing](https://openai.github.io/openai-agents-python/tracing/).
- Arize: tag only the components you want as graph nodes; the rest stays out of the graph — [Arize agent graphs](https://arize.com/docs/ax/observe/tracing-concepts/agent-graphs).
- OpenSearch: one category color scheme shared by graph, minimap and timeline; collapsible tree — [OpenSearch](https://observability.opensearch.org/docs/ai-observability/agent-tracing/graph/).
- AgentOps: charts summarizing event types and durations per session — [AgentOps](https://docs.agentops.ai/v2/usage/dashboard-info).

### Inferences
- For H.E.X Mind: group events by mission, then persona (agent), then step, collapsed by default. Offer filter chips for event type (model call, tool, handoff, A2A, schema check, callback) and an "errors only" toggle. These would replace several current tabs.

### Gaps
- No source gives span-count limits or performance numbers for graph views on very large runs (Datadog and OpenSearch pages are silent).

## Q4. What is hidden from end users versus shown to developers?

### Takeaway
The tools separate audiences in two ways. **Dev-only tools** (ADK web, MS DevUI) are labeled as not for production. **Trace products** offer a simplified **conversation or trajectory view** (blocks of user, agent and tool turns, with per-call tokens and cost) beside a raw **Details** view. Sensitive payloads are opt-out at capture. Summary metrics (cost, tokens, duration, status) are shown everywhere. Raw prompts, wrapper spans and metadata sit one click deeper.

### Cited Findings
- MS DevUI is "for visually debugging agents and workflows during development" and not meant for production — [MS DevUI](https://learn.microsoft.com/en-us/agent-framework/devui/tracing).
- LangSmith Trajectory view = "simplified conversation history between user and agent", with tokens, cost and model per block, and a link to Details for the raw run. `LS_MESSAGE_VIEW_EXCLUDE` removes a run from Trajectory only — [LangSmith view traces](https://docs.langchain.com/langsmith/view-traces).
- AgentOps shows LLM calls as "a familiar chat history view" in the summary; exact prompts and completions are in the waterfall details pane — [AgentOps](https://docs.agentops.ai/v2/usage/dashboard-info).
- OpenAI: `trace_include_sensitive_data` (default True). When False, model and function spans omit inputs and outputs, and rejected tool calls record only "Tool execution rejected" — [OpenAI Agents tracing](https://openai.github.io/openai-agents-python/tracing/).
- CrewAI AMP asks for upload consent on first run. If you decline or don't answer, the trace buffer is discarded — [CrewAI tracing (search summary of docs)](https://docs.crewai.com/en/observability/tracing/index.html).
- Weave Dashboard tab gives project-level cards, charts and top-N lists; per-step token breakdown (cache hit rate, reasoning ratio) is deeper in the conversation Meta summary — [Weave](https://docs.coreweave.com/weave/guides/tracking/view-agent-activity).
- Datadog positions the graph as the readable layer over span lists, with spans or flame graphs for depth — [Datadog blog](https://datadoghq.com/blog/monitor-ai-agents).
- Arize calls the graph a high-level "logical flow map" rather than a detailed trace view — [Arize agents](https://arize.com/docs/ax/observe/tracing/agents).

### Inferences
- Pattern for H.E.X Mind: a default **"Mission" view** for anyone: an agent graph or lanes with real status, a timeline of persona tasks, handoffs as edges, a cost/token/time header, and a readable transcript. A **"Developer" view** behind a toggle: raw event stream, callbacks, schema checks, A2A payloads, audit, span tree. The Blackboard tab should be hidden or merged when it's empty for mission-runner missions, rather than shown blank.
- Handoffs: only OpenAI (handoff_span) and Datadog ("agent a task was handed off to"), plus Arize (automatic handoff tracking via OpenInference for OpenAI Agents), name handoffs as first-class objects. In graphs they appear as edges between agent nodes.

### Gaps
- No tool documents a dedicated "shared state / blackboard" view. The closest is ADK web's session **state inspection and editing** — [ADK web interface](https://adk.dev/runtime/web-interface/). Weave, LangSmith, Langfuse and others expose state only as span inputs and outputs or metadata (inferred from the absence of such a view in their docs).
- No source gives explicit UX guidance ("hide X from end users") beyond the dev-only labeling and simplified-view patterns above.
