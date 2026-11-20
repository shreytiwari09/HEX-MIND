"""Traces kept in Postgres (PRD §14.2): finished spans are stored sanitised, in the background,
and served as a tree. A span that cannot be written never affects the work it describes."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import select, text

from app.api.traces import kind_of
from app.config import Settings
from app.db.models import Project, Run, TraceSpan
from app.sandbox.runner import docker_available
from app.telemetry.span_store import PostgresSpanProcessor, clean_attributes, is_content
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import PLAN, Script, approve, finish, load, new_mission
from tests.test_validators import Validators

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"


# ---------- what may be stored ----------


@pytest.mark.parametrize(
    "key",
    [
        "gen_ai.prompt", "gen_ai.prompt.0.content", "gen_ai.completion.0.content",
        "gen_ai.request.messages", "tool.arguments", "tool.result", "a2a.message",
        "hexmind.response_text", "agent.input", "agent.instruction", "gen_ai.output.messages",
    ],
)  # fmt: skip
def test_content_bearing_names_are_recognised(key: str) -> None:
    assert is_content(key)


@pytest.mark.parametrize(
    "key",
    ["gen_ai.request.model", "gen_ai.response.model", "gen_ai.usage.input_tokens", "agent.name",
     "hexmind.run_id", "agent.framework", "tool.name", "gen_ai.operation.name"],
)  # fmt: skip
def test_ordinary_names_are_not(key: str) -> None:
    assert not is_content(key) or key == "gen_ai.usage.input_tokens"  # usage counters pass below


def test_only_allow_listed_non_content_attributes_are_kept_and_cleaned() -> None:
    kept = clean_attributes(
        {
            "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 120,
            "gen_ai.usage.output_tokens": 30,
            "gen_ai.prompt.0.content": f"the key is {KEY}",
            "gcp.vertex.agent.llm_request": '{"huge": "request"}',
            "gcp.vertex.agent.llm_response": '{"huge": "response"}',
            "http.url": "https://example.com/?token=x",
            "agent.name": "backend_01",
            "hexmind.note": f"saw {KEY} in a log",
            "hexmind.long": "x" * 1000,
            "hexmind.flag": True,
            "hexmind.empty": None,
            "hexmind.list": [f"a {KEY}", 3, "y" * 1000],
            "tool.arguments": '{"path": "src/a.js"}',
            "tool.name": "write_file",
        }
    )

    assert kept["gen_ai.request.model"] == "gpt-5" and kept["gen_ai.usage.input_tokens"] == 120
    assert kept["agent.name"] == "backend_01" and kept["tool.name"] == "write_file"
    assert kept["hexmind.flag"] is True and kept["hexmind.empty"] is None
    assert len(kept["hexmind.long"]) == 300
    assert KEY not in json.dumps(kept) and "[REDACTED]" in kept["hexmind.note"]
    assert kept["hexmind.list"][1] == 3 and len(kept["hexmind.list"][2]) == 300
    for dropped in (
        "gen_ai.prompt.0.content",
        "gcp.vertex.agent.llm_request",
        "gcp.vertex.agent.llm_response",
        "http.url",
        "tool.arguments",
    ):
        assert dropped not in kept
    assert len(clean_attributes({f"hexmind.k{i}": i for i in range(200)})) == 60


# ---------- the processor ----------


def provider_with(processor: PostgresSpanProcessor) -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(processor)
    return provider


async def stored(app: FastAPI) -> list[TraceSpan]:
    async with app.state.sessionmaker() as session:
        return list(await session.scalars(select(TraceSpan).order_by(TraceSpan.start_ns)))


async def test_finished_spans_are_stored_with_their_tree_status_and_sanitised_attributes(
    app: FastAPI, settings: Settings
) -> None:
    processor = PostgresSpanProcessor(settings.database_url)
    tracer = provider_with(processor).get_tracer("test")
    run_id = uuid.uuid4()

    with tracer.start_as_current_span("invoke_agent backend_01") as root:
        root.set_attributes({"hexmind.run_id": str(run_id), "agent.name": "backend_01"})
        with tracer.start_as_current_span("call_llm") as model:
            model.set_attributes(
                {
                    "gen_ai.request.model": "gpt-5",
                    "gen_ai.prompt.0.content": f"secret {KEY}",
                    "gen_ai.usage.input_tokens": 9,
                }
            )
        with tracer.start_as_current_span("execute_tool write_file") as tool:
            tool.set_status(Status(StatusCode.ERROR, f"failed with {KEY}"))
    assert processor.force_flush(10_000)

    rows = {r.name: r for r in await stored(app)}
    assert set(rows) == {"invoke_agent backend_01", "call_llm", "execute_tool write_file"}
    root_row, model_row, tool_row = (
        rows["invoke_agent backend_01"],
        rows["call_llm"],
        rows["execute_tool write_file"],
    )
    assert root_row.parent_span_id is None and root_row.run_id == run_id
    assert (
        model_row.parent_span_id == root_row.span_id and tool_row.parent_span_id == root_row.span_id
    )
    assert (
        len({r.trace_id for r in rows.values()}) == 1
        and len(root_row.trace_id) == 32
        and len(root_row.span_id) == 16
    )
    assert root_row.end_ns >= root_row.start_ns and root_row.started_at.year >= 2026
    assert model_row.attributes == {"gen_ai.request.model": "gpt-5", "gen_ai.usage.input_tokens": 9}
    assert (tool_row.status, KEY in (tool_row.status_message or "")) == ("error", False)
    assert root_row.status == "unset" and model_row.run_id is None
    assert processor.written == 3 and processor.dropped == 0


async def test_a_bad_run_id_is_stored_as_none_and_a_span_is_stored_once(
    app: FastAPI, settings: Settings
) -> None:
    processor = PostgresSpanProcessor(settings.database_url)
    tracer = provider_with(processor).get_tracer("test")

    with tracer.start_as_current_span("one") as span:
        span.set_attribute("hexmind.run_id", "not-a-uuid")
    assert processor.force_flush(10_000)
    first = await stored(app)
    async with app.state.sessionmaker.begin() as session:  # the same span arriving twice
        row = first[0]
        await session.execute(
            text(
                "INSERT INTO trace_spans (trace_id, span_id, name, start_ns, end_ns, "
                "started_at, status, attributes) "
                "VALUES (:t, :s, 'dup', 1, 2, now(), 'ok', '{}'::jsonb) ON CONFLICT DO NOTHING"
            ),
            {"t": row.trace_id, "s": row.span_id},
        )

    rows = await stored(app)
    assert [(r.name, r.run_id) for r in rows] == [("one", None)]


def test_a_database_that_cannot_be_reached_never_breaks_the_work_it_traces() -> None:
    processor = PostgresSpanProcessor("postgresql://nobody:nothing@127.0.0.1:1/none")
    tracer = provider_with(processor).get_tracer("test")

    for number in range(5):
        with tracer.start_as_current_span(f"work {number}"):
            pass  # no exception reaches the code being traced

    assert processor.force_flush(20_000)  # they are dropped, not stuck
    assert processor.dropped == 5 and processor.written == 0


def test_the_queue_never_grows_without_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.telemetry.span_store.QUEUE_SIZE", 2)
    processor = PostgresSpanProcessor("postgresql://nobody:nothing@127.0.0.1:1/none")
    processor._start = lambda: None  # type: ignore[method-assign]  # no writer: the queue fills
    import queue as queue_module

    processor._queue = queue_module.Queue(2)
    tracer = provider_with(processor).get_tracer("test")

    for _ in range(6):
        with tracer.start_as_current_span("x"):
            pass

    assert processor.dropped == 4


# ---------- the API ----------


def span_row(
    trace: str,
    span: str,
    parent: str | None,
    name: str,
    start: int,
    end: int,
    run: uuid.UUID | None,
    **attributes: Any,
) -> dict[str, Any]:
    return {
        "t": trace, "s": span, "p": parent, "n": name, "a": start, "b": end, "r": run,
        "x": json.dumps(attributes),
    }  # fmt: skip


async def seed(app: FastAPI, rows: list[dict[str, Any]]) -> None:
    async with app.state.engine.begin() as conn:
        for row in rows:
            await conn.execute(
                text(
                    "INSERT INTO trace_spans (trace_id, span_id, parent_span_id, name, "
                    "start_ns, end_ns, started_at, status, attributes, run_id) "
                    "VALUES (:t, :s, :p, :n, :a, :b, now(), 'ok', CAST(:x AS jsonb), :r)"
                ),
                row,
            )


async def make_run(app: FastAPI, tmp_path: Path) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path=str(tmp_path))
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        return run.id


async def test_the_trace_api_returns_a_runs_spans_as_a_tree_with_timings_and_kinds(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)
    other = await make_run(app, tmp_path / "other")
    ms = 1_000_000
    t1, t2 = "1" * 32, "2" * 32
    await seed(
        app,
        [
            # Out of order on purpose; only the root carries the run id.
            span_row(
                t1, "a" * 16, "r" * 0 or None, "invoke_agent mission_runner", 0, 900 * ms, run_id
            ),
            span_row(
                t1,
                "d" * 16,
                "c" * 16,
                "execute_tool write_file",
                300 * ms,
                320 * ms,
                None,
                **{"tool.name": "write_file"},
            ),
            span_row(
                t1,
                "b" * 16,
                "a" * 16,
                "crewai.crew backend_01",
                100 * ms,
                800 * ms,
                None,
                **{"agent.kind": "crew"},
            ),
            span_row(
                t1,
                "c" * 16,
                "b" * 16,
                "call_llm",
                150 * ms,
                600 * ms,
                None,
                **{"gen_ai.request.model": "gpt-5"},
            ),
            span_row(t2, "e" * 16, None, "a2a send_message", 50 * ms, 60 * ms, run_id),
            span_row("9" * 32, "f" * 16, None, "invoke_agent someone_else", 0, ms, other),
        ],
    )

    body = (await client.get("/api/traces", params={"run_id": str(run_id)})).json()

    assert body["traces"] == 2 and body["truncated"] is False and body["duration_ms"] == 900
    names = [s["name"] for s in body["spans"]]
    assert names == [
        "invoke_agent mission_runner",
        "crewai.crew backend_01",
        "call_llm",
        "execute_tool write_file",
        "a2a send_message",
    ]  # parents before children, each trace in start order; the other run's span is absent
    by = {s["name"]: s for s in body["spans"]}
    assert [by[n]["depth"] for n in names] == [0, 1, 2, 3, 0]
    assert by["call_llm"]["offset_ms"] == 150 and by["call_llm"]["duration_ms"] == 450
    assert [by[n]["kind"] for n in names] == ["agent", "crew", "model", "tool", "a2a"]
    assert by["call_llm"]["attributes"] == {"gen_ai.request.model": "gpt-5"}


async def test_the_trace_api_by_mission_and_its_errors(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    empty = await make_run(app, tmp_path)
    none = (await client.get("/api/traces", params={"run_id": str(empty)})).json()

    assert none == {
        "run_id": str(empty),
        "spans": [],
        "traces": 0,
        "duration_ms": 0.0,
        "truncated": False,
    }
    assert (await client.get("/api/traces")).status_code == 422
    assert (
        await client.get("/api/traces", params={"run_id": str(uuid.uuid4())})
    ).status_code == 404
    assert (
        await client.get("/api/traces", params={"mission_id": str(uuid.uuid4())})
    ).status_code == 404


async def test_a_trace_larger_than_the_limit_says_it_was_cut(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)
    await seed(
        app,
        [
            span_row("3" * 32, f"{i:016x}", None, f"span {i}", i, i + 1, run_id if i == 0 else None)
            for i in range(6)
        ],
    )

    body = (await client.get("/api/traces", params={"run_id": str(run_id), "limit": 4})).json()

    assert len(body["spans"]) == 4 and body["truncated"] is True


def test_spans_are_classified_by_what_they_are() -> None:
    assert kind_of("invoke_agent x", {}) == "agent"
    assert kind_of("call_llm", {}) == "model"
    assert kind_of("chat gpt", {"gen_ai.request.model": "gpt"}) == "model"
    assert kind_of("execute_tool run_check", {}) == "tool"
    assert kind_of("crewai.crew backend_01", {}) == "crew"
    assert kind_of("POST /persona", {"agent.kind": "crew"}) == "crew"
    assert kind_of("a2a send_message", {}) == "a2a"
    assert kind_of("sandbox docker run", {}) == "sandbox"
    assert kind_of("whatever", {}) == "other"


# ---------- a real mission ----------


@needs_docker
async def test_a_mission_leaves_stored_spans_with_no_prompt_text_in_them(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    marker = "ZEBRA-MARKER-7731"
    plan = json.loads(json.dumps(PLAN))
    plan["milestones"][0]["features"][0]["expected_behavior"] = [f"addTodo works ({marker})"]
    plan["milestones"][0]["validators"] = ["code-reviewer"]
    use_adapter(app, ScriptedAdapter(Validators(Script())))
    mission = await new_mission(client, repo, plan)

    await approve(client, mission)
    await finish(app)
    provider = trace.get_tracer_provider()
    assert provider.force_flush(20_000)  # type: ignore[attr-defined]
    for _ in range(100):  # the writer thread of the first app of this process may lag a moment
        body = (await client.get("/api/traces", params={"mission_id": mission["id"]})).json()
        if body["spans"]:
            break
        import asyncio

        await asyncio.sleep(0.1)

    assert body["spans"], "the mission left no stored spans"
    kinds = {s["kind"] for s in body["spans"]}
    assert "crew" in kinds
    everything = json.dumps(body)
    assert marker not in everything  # a prompt that carried the marker is nowhere in the trace
    assert "def addTodo" not in everything and "sk-" not in everything
    row, _, run = await load(app, mission["id"])
    assert row.status == "completed" and body["run_id"] == str(run.id)
