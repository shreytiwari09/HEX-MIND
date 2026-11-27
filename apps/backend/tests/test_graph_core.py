"""LangGraph core: the chat model over ProviderRouter and the structured-output guard."""

import uuid

from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.chat_model import HexChatModel
from app.db.models import AgentEvent, LLMCall, Project, Run
from app.orchestration.graph import structured_call
from app.providers.base import Completion, LLMRequest, ProviderError, ToolCall
from app.providers.router import CallContext
from app.telemetry.hub import TelemetryHub
from tests.conftest import ScriptedAdapter, use_adapter


class Verdict(BaseModel):
    ok: bool


def _no(errors: list[str]) -> Verdict:
    return Verdict(ok=False)


async def _run(app: FastAPI) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path="/tmp/p")
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        return run.id


def _model(app: FastAPI, run_id: uuid.UUID) -> HexChatModel:
    return HexChatModel(
        router=app.state.services.providers, ctx=CallContext(run_id=run_id), purpose="reviewer"
    )


def _replies(*outputs: str) -> ScriptedAdapter:
    queue = list(outputs)

    def handler(request: LLMRequest) -> Completion:
        return Completion(content=queue.pop(0), input_tokens=10, output_tokens=5)

    return ScriptedAdapter(handler)


async def test_structured_call_valid(app: FastAPI) -> None:
    adapter = _replies('```json\n{"ok": true}\n```')
    use_adapter(app, adapter)
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)

    result = await structured_call(
        _model(app, run_id),
        Verdict,
        "Judge.",
        agent="judge",
        fallback=_no,
        telemetry=hub,
        user_message="Review it",
    )

    assert result.status == "valid" and result.value == Verdict(ok=True) and result.errors == []
    request = adapter.requests[0]
    assert [m.role for m in request.messages] == ["system", "user"]
    assert request.messages[0].content == "Judge." and request.messages[1].content == "Review it"
    assert request.json_schema == Verdict.model_json_schema()
    async with app.state.sessionmaker() as session:
        events = list(await session.scalars(select(AgentEvent).where(AgentEvent.run_id == run_id)))
    (check,) = [e.payload for e in events if e.type == "schema_validated"]
    assert check["agent"] == "judge" and check["schema_name"] == "Verdict"
    assert check["status"] == "valid"


async def test_structured_call_repairs_once(app: FastAPI) -> None:
    adapter = _replies("not json", '{"ok": true}')
    use_adapter(app, adapter)
    run_id = await _run(app)

    result = await structured_call(
        _model(app, run_id), Verdict, "Judge.", agent="judge", fallback=_no, telemetry=None
    )

    assert result.status == "repaired" and result.value == Verdict(ok=True)
    assert len(result.errors) == 1
    assert len(adapter.requests) == 2
    assert "That answer was invalid" in (adapter.requests[1].messages[-1].content or "")
    async with app.state.sessionmaker() as session:
        calls = list(await session.scalars(select(LLMCall).where(LLMCall.run_id == run_id)))
    assert len(calls) == 2


async def test_structured_call_falls_back(app: FastAPI) -> None:
    use_adapter(app, _replies("nope", "still nope"))
    run_id = await _run(app)

    result = await structured_call(
        _model(app, run_id), Verdict, "Judge.", agent="judge", fallback=_no, telemetry=None
    )

    assert result.status == "fallback" and result.value == Verdict(ok=False)
    assert len(result.errors) == 2


async def test_structured_call_provider_outage(app: FastAPI) -> None:
    def handler(request: LLMRequest) -> Completion:
        raise ProviderError("quota", retryable=False)

    use_adapter(app, ScriptedAdapter(handler))
    run_id = await _run(app)

    result = await structured_call(
        _model(app, run_id), Verdict, "Judge.", agent="judge", fallback=_no, telemetry=None
    )

    assert result.status == "fallback" and result.value == Verdict(ok=False)
    assert result.errors[0].startswith("provider error") and "quota" in result.errors[0]


def lookup(key: str) -> dict:
    """Look up a value."""
    return {"value": key.upper()}


async def test_chat_model_tool_calls_round_trip(app: FastAPI) -> None:
    def handler(request: LLMRequest) -> Completion:
        return Completion(
            content="",
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={"key": "a"})],
            input_tokens=7,
            output_tokens=3,
        )

    adapter = ScriptedAdapter(handler)
    use_adapter(app, adapter)
    run_id = await _run(app)
    model = _model(app, run_id)

    reply = await model.bind_tools([lookup]).ainvoke(
        [SystemMessage("Use tools."), HumanMessage("Find a")]
    )

    assert isinstance(reply, AIMessage)
    assert reply.tool_calls[0]["name"] == "lookup" and reply.tool_calls[0]["args"] == {"key": "a"}
    (tool,) = adapter.requests[0].tools or []
    assert tool["function"]["name"] == "lookup"
    assert model.last_result is not None and model.last_result.input_tokens == 7


async def test_run_agent_records_one_agent_with_its_model_calls(app: FastAPI) -> None:
    from app.orchestration.graph import run_agent

    use_adapter(app, _replies('{"ok": true}'))
    run_id = await _run(app)
    hub = TelemetryHub(app.state.services, run_id)
    model = _model(app, run_id)

    result = await run_agent(
        "judge",
        lambda: structured_call(
            model, Verdict, "Judge.", agent="judge", fallback=_no, telemetry=hub
        ),
        telemetry=hub,
        parent="scoping",
    )

    assert result.value == Verdict(ok=True)
    async with app.state.sessionmaker() as session:
        events = list(await session.scalars(select(AgentEvent).where(AgentEvent.run_id == run_id)))
    started = [e.payload for e in events if e.type == "agent_started"]
    assert [(p["agent"], p["parent"], p["kind"]) for p in started] == [("judge", "scoping", "llm")]
    hooks = [(e.payload["hook"], e.payload["agent"]) for e in events if e.type == "callback_fired"]
    assert hooks == [("model_start", "judge"), ("model_end", "judge")]
    finished = [e.payload for e in events if e.type == "agent_finished"]
    assert [(p["agent"], p["ok"]) for p in finished] == [("judge", True)]
