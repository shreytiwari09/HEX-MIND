"""TelemetryHub: every LangGraph callback type and the CrewAI hooks become run events and spans."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select

from app.db.models import AgentEvent, Project, Run
from app.providers.base import Completion, LLMRequest, ToolCall
from app.providers.router import CallContext
from app.telemetry.hub import TelemetryHub, describe_step
from app.telemetry.tracing import add_span_processor
from tests.conftest import ScriptedAdapter, use_adapter


def lookup(key: str) -> dict:
    """Look up a value."""
    return {"value": key.upper()}


def explode(key: str) -> dict:
    """Always fails."""
    raise RuntimeError("tool broke")


@pytest.fixture
def spans() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


async def _run(app: FastAPI) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path="/tmp/p")
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        return run.id


async def _events(app: FastAPI, run_id: uuid.UUID) -> list[AgentEvent]:
    async with app.state.sessionmaker() as session:
        return list(
            await session.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )


async def test_crew_callbacks_record_from_a_worker_thread(
    app: FastAPI, spans: InMemorySpanExporter
) -> None:
    import asyncio

    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)
    callbacks = hub.crew_callbacks("worker-1", parent="coder")

    def crew_thread() -> None:  # CrewAI calls these on its worker thread
        callbacks.before_kickoff({})
        callbacks.step_callback(SimpleNamespace(tool="write_file"))
        callbacks.task_callback(SimpleNamespace(raw="done"))
        callbacks.after_kickoff("output")

    with callbacks.span():
        await asyncio.to_thread(crew_thread)

    events = await _events(app, run_id)
    assert [(e.type, e.payload.get("hook")) for e in events] == [
        ("agent_started", None),
        ("callback_fired", "step_callback"),
        ("callback_fired", "task_callback"),
        ("agent_finished", None),
    ]
    assert all(e.payload["framework"] == "crewai" and e.agent_id == "worker-1" for e in events)
    assert events[0].payload["kind"] == "crew" and events[0].payload["parent"] == "coder"
    assert events[1].payload["detail"] == "SimpleNamespace: write_file"
    crew_spans = [s for s in spans.get_finished_spans() if s.name == "crewai.crew worker-1"]
    assert crew_spans and crew_spans[0].attributes["agent.framework"] == "crewai"


def test_describe_step() -> None:
    assert describe_step(SimpleNamespace(tool="read_file")) == "SimpleNamespace: read_file"
    assert describe_step(SimpleNamespace(output="final")) == "SimpleNamespace: final"
    assert describe_step(object()) == "object"


# ---------- LangGraph ----------


def _lg_graph(app: FastAPI, run_id: uuid.UUID):
    """thinker (an LLM node asking for two tools) -> tools (a ToolNode; one tool fails)."""
    from typing import Annotated, TypedDict

    from langchain_core.tools import tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode

    from app.agents.chat_model import HexChatModel

    @tool
    def lookup_tool(key: str) -> dict:
        """Look up a value."""
        return lookup(key)

    @tool
    def explode_tool(key: str) -> dict:
        """Always fails."""
        return explode(key)

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    model = HexChatModel(
        router=app.state.services.providers, ctx=CallContext(run_id=run_id), purpose="coder"
    ).bind_tools([lookup_tool, explode_tool])

    async def thinker(state: State) -> dict:
        return {"messages": [await model.ainvoke(state["messages"])]}

    graph = StateGraph(State)
    graph.add_node("thinker", thinker, metadata={"hex_kind": "llm"})
    graph.add_node(
        "tools",
        ToolNode([lookup_tool, explode_tool], handle_tool_errors=True),
        metadata={"hex_kind": "tools"},
    )
    graph.add_edge(START, "thinker")
    graph.add_edge("thinker", "tools")
    graph.add_edge("tools", END)
    return graph.compile(name="demo_graph")


def _tool_calling_adapter() -> ScriptedAdapter:
    def handler(request: LLMRequest) -> Completion:
        return Completion(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="lookup_tool", arguments={"key": "a"}),
                ToolCall(id="c2", name="explode_tool", arguments={"key": "b"}),
            ],
            input_tokens=12,
            output_tokens=4,
        )

    return ScriptedAdapter(handler)


async def test_every_langgraph_callback_type_is_recorded(app: FastAPI) -> None:
    from langchain_core.messages import HumanMessage

    from app.orchestration.graph import run_graph

    use_adapter(app, _tool_calling_adapter())
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)

    await run_graph(
        _lg_graph(app, run_id), {"messages": [HumanMessage("go")]}, telemetry=hub, parent="execute"
    )

    events = await _events(app, run_id)
    started = {e.payload["agent"]: e.payload for e in events if e.type == "agent_started"}
    assert set(started) >= {"demo_graph", "thinker", "tools"}
    assert started["demo_graph"]["parent"] == "execute"
    assert started["thinker"]["parent"] == "demo_graph" and started["thinker"]["kind"] == "llm"
    assert {p["framework"] for p in started.values()} == {"langgraph"}
    finished = [e.payload for e in events if e.type == "agent_finished"]
    assert {p["agent"] for p in finished} >= {"demo_graph", "thinker", "tools"}
    assert all(p["ok"] for p in finished)
    hooks = {e.payload["hook"] for e in events if e.type == "callback_fired"}
    assert hooks >= {"model_start", "model_end", "tool_start", "tool_end", "tool_error"}
    (model_end,) = [e.payload for e in events if e.payload.get("hook") == "model_end"]
    assert model_end["agent"] == "thinker" and "12→4 tokens" in model_end["detail"]


async def test_handler_survives_record_failure(app: FastAPI, monkeypatch) -> None:
    from langchain_core.messages import HumanMessage

    from app.orchestration.graph import run_graph

    use_adapter(app, _tool_calling_adapter())
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)

    async def broken(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(hub, "record", broken)
    state = await run_graph(
        _lg_graph(app, run_id), {"messages": [HumanMessage("go")]}, telemetry=hub
    )

    assert len(state["messages"]) == 4  # human, AI with 2 tool calls, 2 tool results


async def test_abort_open_closes_graph_agents_once(app: FastAPI) -> None:
    """A failed run or task (lease lost, cancelled) can leave graph agents without an end callback;
    abort_open records them as failed, and a late end callback does not record them twice."""
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)
    handler = hub.handler(parent="execute")
    root, node = uuid.uuid4(), uuid.uuid4()

    await handler.on_chain_start({}, {}, run_id=root, name="reflection_loop", metadata={})
    await handler.on_chain_start(
        {}, {}, run_id=node, parent_run_id=root, name="coder", metadata={"langgraph_node": "coder"}
    )
    await hub.abort_open(error="run failed")
    await handler.on_chain_end({}, run_id=node)

    events = await _events(app, run_id)
    finished = [(e.payload["agent"], e.payload["ok"], e.payload["framework"])
                for e in events if e.type == "agent_finished"]  # fmt: skip
    assert sorted(finished) == [
        ("coder", False, "langgraph"),
        ("reflection_loop", False, "langgraph"),
    ]


async def test_langgraph_agents_model_and_tool_calls_become_nested_spans(
    app: FastAPI, spans: InMemorySpanExporter
) -> None:
    """The Traces view reads these spans (agent, model and tool kinds)."""
    from langchain_core.messages import HumanMessage

    from app.api.traces import kind_of
    from app.orchestration.graph import run_graph

    use_adapter(app, _tool_calling_adapter())
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)

    await run_graph(_lg_graph(app, run_id), {"messages": [HumanMessage("go")]}, telemetry=hub)

    mine = [
        s for s in spans.get_finished_spans() if s.attributes.get("hexmind.run_id") == str(run_id)
    ]
    by_name = {s.name: s for s in mine}
    assert {"invoke_agent demo_graph", "invoke_agent thinker", "call_llm",
            "execute_tool lookup_tool", "execute_tool explode_tool"} <= set(by_name)  # fmt: skip
    graph, thinker, model = (
        by_name["invoke_agent demo_graph"],
        by_name["invoke_agent thinker"],
        by_name["call_llm"],
    )
    assert thinker.parent.span_id == graph.context.span_id
    assert model.parent.span_id == thinker.context.span_id
    assert model.attributes["llm.provider"] == "scripted"
    assert model.attributes["llm.input_tokens"] == 12
    assert thinker.attributes["agent.framework"] == "langgraph"
    assert by_name["execute_tool lookup_tool"].attributes["tool.name"] == "lookup_tool"
    assert not by_name["execute_tool explode_tool"].status.is_ok
    assert [kind_of(s.name, dict(s.attributes)) for s in (thinker, model)] == ["agent", "model"]
