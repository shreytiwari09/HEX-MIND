# ADK / A2A / CrewAI version check (2026-11-01)

Re-run these whenever `google-adk`, `a2a-sdk` or `crewai` is upgraded. Results are recorded in
`PRD.md` §17 (pinned versions and spike findings).

```sh
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe "google-adk[a2a]==2.13.0" "crewai[a2a]==1.15.28" "a2a-sdk[http-server]~=0.3.10" mcp
.venv/Scripts/python.exe spike_adk.py        # custom BaseLlm, Loop/Sequential agents, output_schema, callbacks
.venv/Scripts/python.exe spike_a2a.py        # CrewAI crew served over A2A, called by ADK RemoteA2aAgent, traceparent
.venv/Scripts/python.exe spike_mcp_otel.py   # ADK McpToolset over stdio + OpenTelemetry span tree
```
