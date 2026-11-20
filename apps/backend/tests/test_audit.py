"""The audit trail (PRD §14.2): a hash chain over each run's events that notices any change, a
verify endpoint, hashes of what every model call sent and received, and recovery after a restart.
The tamper tests edit the database directly, the way someone with access would."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text

from app.db.models import AgentEvent, LLMCall, Mission, Project, Run
from app.events import chain
from app.events.log import EventType, append_event, list_events
from app.missions.recovery import REASON, pause_interrupted_missions
from app.providers.base import ChatMessage, Completion, LLMRequest
from app.providers.router import CallContext, digests
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import PLAN, Script, approve, finish, load, new_mission

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


async def make_run(app: FastAPI, tmp_path: Path) -> uuid.UUID:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path=str(tmp_path))
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        return run.id


async def fill(app: FastAPI, run_id: uuid.UUID, count: int = 6) -> None:
    for number in range(count):
        async with app.state.sessionmaker.begin() as session:
            await append_event(
                session,
                run_id,
                EventType.TOOL_CALLED,
                agent_id=f"agent_{number % 2}",
                payload={"tool": "write_file", "ok": True, "summary": f"src/f{number}.js: created"},
            )


async def audit(app: FastAPI, run_id: uuid.UUID, head: str | None = None) -> chain.RunAudit:
    async with app.state.sessionmaker() as session:
        return await chain.verify_run(session, run_id, expected_head=head)


async def sql(app: FastAPI, statement: str, **params: Any) -> None:
    async with app.state.engine.begin() as conn:
        await conn.execute(text(statement), params)


# ---------- the chain ----------


def test_the_hash_is_over_the_previous_hash_and_a_canonical_record() -> None:
    run_id = uuid.uuid4()
    first = genesis = chain.genesis(run_id)

    assert genesis == hashlib.sha256(f"hexmind-genesis:{run_id}".encode()).hexdigest()
    assert chain.genesis(uuid.uuid4()) != genesis
    assert chain.canonical({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == '{"a":[1,{"c":3,"d":2}],"b":1}'
    assert chain.canonical({"é": "ü"}) == '{"é":"ü"}'  # no ascii escaping: one spelling
    from datetime import UTC, datetime

    record = chain.record_of(
        run_id=run_id, seq=1, type="x", agent_id=None, task_id=None, payload={"k": 1},
        ts=datetime(2026, 11, 20, 10, 0, 0, 5, tzinfo=UTC),
    )  # fmt: skip
    assert record["ts"] == "2026-11-20T10:00:00.000005+00:00"
    assert chain.link(first, record) == chain.link(
        first, dict(reversed(record.items()))
    )  # key order
    assert chain.link(first, record) != chain.link("0" * 64, record)  # depends on what came before
    assert chain.link(first, record) != chain.link(first, {**record, "seq": 2})


async def test_every_event_is_chained_to_the_one_before_and_the_chain_verifies(
    app: FastAPI, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)

    await fill(app, run_id, 6)

    async with app.state.sessionmaker() as session:
        events = await list_events(session, run_id)
    assert [e.seq for e in events] == [1, 2, 3, 4, 5, 6]
    assert events[0].prev_hash == chain.genesis(run_id)
    for before, after in zip(events, events[1:], strict=False):
        assert after.prev_hash == before.hash and len(after.hash) == 64
    result = await audit(app, run_id)
    assert (
        result.ok and result.events == 6 and result.head == events[-1].hash and result.legacy == 0
    )


async def test_several_events_in_one_transaction_chain_in_order(
    app: FastAPI, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)

    async with app.state.sessionmaker.begin() as session:
        for number in range(4):
            await append_event(
                session, run_id, EventType.TOOL_CALLED,
                payload={"tool": "t", "ok": True, "summary": str(number)},
            )  # fmt: skip

    assert (await audit(app, run_id)).ok


async def test_a_rolled_back_event_leaves_no_gap_and_no_break(app: FastAPI, tmp_path: Path) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 2)

    with pytest.raises(RuntimeError):
        async with app.state.sessionmaker.begin() as session:
            await append_event(
                session,
                run_id,
                EventType.TOOL_CALLED,
                payload={"tool": "t", "ok": True, "summary": "x"},
            )
            raise RuntimeError("the caller failed after logging")
    await fill(app, run_id, 2)

    result = await audit(app, run_id)
    assert result.ok and result.events == 4


# ---------- tampering ----------


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("UPDATE agent_events SET payload = jsonb_set(payload, '{summary}', '\"edited\"') "
         "WHERE run_id = :r AND seq = 3", "its content was changed"),
        ("UPDATE agent_events SET type = 'run_completed' WHERE run_id = :r AND seq = 3",
         "its content was changed"),
        ("UPDATE agent_events SET agent_id = 'someone_else' WHERE run_id = :r AND seq = 3",
         "its content was changed"),
        ("UPDATE agent_events SET ts = ts + interval '1 second' WHERE run_id = :r AND seq = 3",
         "its content was changed"),
        ("UPDATE agent_events SET hash = repeat('0', 64) WHERE run_id = :r AND seq = 3",
         "its content was changed"),
        ("UPDATE agent_events SET prev_hash = repeat('0', 64) WHERE run_id = :r AND seq = 3",
         "does not follow the event before it"),
    ],
)  # fmt: skip
async def test_changing_a_stored_event_is_found_at_that_event(
    app: FastAPI, tmp_path: Path, statement: str, reason: str
) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 6)
    assert (await audit(app, run_id)).ok

    await sql(app, statement, r=run_id)

    result = await audit(app, run_id)
    assert not result.ok and result.broken is not None
    assert (result.broken.seq, reason in result.broken.reason) == (3, True), result.broken


async def test_removing_an_event_from_the_middle_is_found(app: FastAPI, tmp_path: Path) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 6)

    await sql(app, "DELETE FROM agent_events WHERE run_id = :r AND seq = 3", r=run_id)

    result = await audit(app, run_id)
    assert result.broken is not None and (
        result.broken.seq,
        "3 is missing" in result.broken.reason,
    ) == (4, True)


async def test_cutting_the_end_of_the_log_is_found(app: FastAPI, tmp_path: Path) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 6)

    await sql(app, "DELETE FROM agent_events WHERE run_id = :r AND seq > 4", r=run_id)

    result = await audit(app, run_id)
    assert result.broken is not None and "missing" in result.broken.reason


async def test_a_careful_rewrite_is_caught_only_by_the_head_you_kept(
    app: FastAPI, tmp_path: Path
) -> None:
    """Someone who recomputes every later hash fools the chain on its own (it proves consistency,
    not history); the head hash recorded elsewhere is what exposes them."""
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 6)
    kept = (await audit(app, run_id)).head
    async with app.state.sessionmaker.begin() as session:
        events = list(
            await session.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )
        previous = chain.genesis(run_id)
        for event in events:
            if event.seq == 3:
                event.payload = {
                    "tool": "write_file",
                    "ok": True,
                    "summary": "src/evil.js: created",
                }
            event.prev_hash = previous
            event.hash = previous = chain.hash_of_event(event)

    forged = await audit(app, run_id)
    assert forged.ok and forged.head != kept  # internally consistent...
    caught = await audit(app, run_id, head=kept)
    assert not caught.ok and caught.broken is not None
    assert "does not end where you recorded it did" in caught.broken.reason


async def test_cutting_the_log_and_its_counter_together_is_also_caught_by_the_kept_head(
    app: FastAPI, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 6)
    kept = (await audit(app, run_id)).head

    await sql(app, "DELETE FROM agent_events WHERE run_id = :r AND seq > 4", r=run_id)
    await sql(app, "UPDATE runs SET last_event_seq = 4 WHERE id = :r", r=run_id)

    assert (await audit(app, run_id)).ok  # nothing inside the log gives it away
    assert not (await audit(app, run_id, head=kept)).ok


async def test_events_from_before_the_chain_are_counted_not_trusted(
    app: FastAPI, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 3)

    await sql(
        app, "UPDATE agent_events SET hash = NULL, prev_hash = NULL WHERE run_id = :r", r=run_id
    )

    result = await audit(app, run_id)
    assert result.ok and result.legacy == 3 and result.head is None
    assert (await audit(app, uuid.uuid4())).broken is not None  # an unknown run is not "fine"


# ---------- the API ----------


async def test_the_audit_api_verifies_one_run_a_mission_or_everything(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    first = await make_run(app, tmp_path / "a")
    second = await make_run(app, tmp_path / "b")
    await fill(app, first, 4)
    await fill(app, second, 3)

    one = (await client.get("/api/audit/verify", params={"run_id": str(first)})).json()
    everything = (await client.get("/api/audit/verify")).json()

    assert one["ok"] and [r["events"] for r in one["runs"]] == [4]
    assert everything["ok"] and sorted(r["events"] for r in everything["runs"]) == [3, 4]
    head = (await client.get("/api/audit/head", params={"run_id": str(first)})).json()
    assert head["head"] == one["runs"][0]["head"] and len(head["head"]) == 64
    ok = await client.get(
        "/api/audit/verify", params={"run_id": str(first), "expected_head": head["head"]}
    )
    assert ok.json()["ok"]
    wrong = await client.get(
        "/api/audit/verify", params={"run_id": str(first), "expected_head": "f" * 64}
    )
    assert wrong.json()["ok"] is False
    assert wrong.json()["runs"][0]["broken"]["reason"].startswith("the log does not end")

    await sql(app, "UPDATE agent_events SET agent_id = 'x' WHERE run_id = :r AND seq = 2", r=second)
    broken = (await client.get("/api/audit/verify")).json()
    assert broken["ok"] is False
    bad = next(r for r in broken["runs"] if r["run_id"] == str(second))
    assert (
        bad["broken"]["seq"] == 2
        and next(r for r in broken["runs"] if r["run_id"] == str(first))["ok"]
    )


async def test_the_audit_api_lists_events_with_their_hashes_and_refuses_bad_requests(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    run_id = await make_run(app, tmp_path)
    await fill(app, run_id, 5)

    listed = (
        await client.get(
            "/api/audit/events", params={"run_id": str(run_id), "after_seq": 2, "limit": 2}
        )
    ).json()

    assert [e["seq"] for e in listed] == [3, 4] and all(len(e["hash"]) == 64 for e in listed)
    assert listed[1]["prev_hash"] == listed[0]["hash"]
    missing = str(uuid.uuid4())
    assert (await client.get("/api/audit/verify", params={"run_id": missing})).status_code == 404
    assert (
        await client.get("/api/audit/verify", params={"mission_id": missing})
    ).status_code == 404
    assert (await client.get("/api/audit/head")).status_code == 422  # which run?
    assert (await client.get("/api/audit/events")).status_code == 422
    assert (
        await client.get("/api/audit/verify", params={"expected_head": "a" * 64})
    ).status_code == 422
    assert (
        await client.get(
            "/api/audit/verify", params={"run_id": str(run_id), "expected_head": "short"}
        )
    ).status_code == 422


# ---------- model calls ----------


async def test_every_model_call_records_hashes_of_what_was_sent_and_received_not_the_text(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    secret_prompt = "Summarise the file. The key is sk-abcdefghijklmnopqrstuvwxyz123456."
    use_adapter(
        app,
        ScriptedAdapter(
            lambda r: Completion(content="the answer is 42", input_tokens=5, output_tokens=3)
        ),
    )
    run_id = await make_run(app, tmp_path)
    request = LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content=secret_prompt)])

    result = await app.state.provider_router.complete(request, CallContext(run_id=run_id))

    assert result.ok
    sent, got = digests(request, Completion(content="the answer is 42"))
    async with app.state.sessionmaker() as session:
        [call] = list(await session.scalars(select(LLMCall).where(LLMCall.run_id == run_id)))
        events = [e for e in await list_events(session, run_id) if e.type == "llm_call_completed"]
    assert call.request_sha256 == sent and call.response_sha256 == got
    assert (
        events[0].payload["request_sha256"] == sent and events[0].payload["response_sha256"] == got
    )
    stored = json.dumps([call.request_sha256, call.response_sha256, events[0].payload])
    assert "sk-abcdef" not in stored and "Summarise" not in stored  # the text is never kept
    assert (await audit(app, run_id)).ok


def test_the_hashes_tell_calls_apart_and_ignore_what_is_not_content() -> None:
    one = LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hello")])
    two = LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hello!")])

    assert digests(one, None)[0] != digests(two, None)[0] and digests(one, None)[1] is None
    cheap = Completion(content="ok", input_tokens=1, output_tokens=1)
    dear = Completion(content="ok", input_tokens=900, output_tokens=7)
    assert digests(one, cheap) == digests(one, dear)  # same words, same hash, whatever it cost
    assert digests(one, Completion(content="ok"))[1] != digests(one, Completion(content="ok."))[1]


async def test_a_failed_call_has_a_request_hash_and_no_response_hash(
    app: FastAPI, tmp_path: Path
) -> None:
    from app.providers.base import ProviderError

    def fail(request: LLMRequest) -> Completion:
        raise ProviderError("down", retryable=False)

    use_adapter(app, ScriptedAdapter(fail))
    run_id = await make_run(app, tmp_path)

    result = await app.state.provider_router.complete(
        LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")]),
        CallContext(run_id=run_id),
    )

    assert not result.ok
    async with app.state.sessionmaker() as session:
        [call] = list(await session.scalars(select(LLMCall).where(LLMCall.run_id == run_id)))
    assert call.request_sha256 and call.response_sha256 is None


# ---------- a real mission ----------


@needs_docker
async def test_a_mission_leaves_a_chain_that_verifies_and_breaks_if_a_file_write_is_edited(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)
    await approve(client, mission)
    await finish(app)
    _, _, run = await load(app, mission["id"])

    result = (await client.get("/api/audit/verify", params={"mission_id": mission["id"]})).json()
    assert result["ok"] and result["runs"][0]["events"] > 20 and result["runs"][0]["legacy"] == 0
    head = (await client.get("/api/audit/head", params={"mission_id": mission["id"]})).json()[
        "head"
    ]

    await sql(
        app,
        "UPDATE agent_events SET payload = jsonb_set("
        "payload, '{summary}', '\"src/innocent.js: updated\"') "
        "WHERE run_id = :r AND type = 'tool_called' AND payload->>'tool' = 'write_file' "
        "AND seq = (SELECT min(seq) FROM agent_events WHERE run_id = :r AND type = 'tool_called' "
        "AND payload->>'tool' = 'write_file')",
        r=run.id,
    )

    broken = (
        await client.get(
            "/api/audit/verify", params={"mission_id": mission["id"], "expected_head": head}
        )
    ).json()
    assert (
        broken["ok"] is False
        and "changed after it was written" in broken["runs"][0]["broken"]["reason"]
    )


# ---------- resume after a restart ----------


async def mission_in(app: FastAPI, client: httpx.AsyncClient, repo: Path, status: str) -> uuid.UUID:
    mission = await new_mission(client, repo)
    await sql(
        app, "UPDATE missions SET status = :s WHERE id = :m", s=status, m=uuid.UUID(mission["id"])
    )
    return uuid.UUID(mission["id"])


async def test_missions_that_were_running_when_the_backend_stopped_are_paused_with_the_reason(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    repos = []
    for name in ("a", "b", "c", "d"):
        from tests.test_run_contract import repo_with

        (tmp_path / name).mkdir()
        repos.append(repo_with(tmp_path / name, None))
    interrupted = await mission_in(app, client, repos[0], "running")
    waiting = await mission_in(app, client, repos[1], "needs_user")
    paused = await mission_in(app, client, repos[2], "paused")
    done = await mission_in(app, client, repos[3], "completed")

    count = await pause_interrupted_missions(app.state.services)

    assert count == 1
    async with app.state.sessionmaker() as session:
        status = {m.id: m.status for m in await session.scalars(select(Mission))}
        run = await session.get(Run, (await session.get(Mission, interrupted)).run_id)  # type: ignore[union-attr]
        events = [
            e for e in await list_events(session, run.id) if e.type == "mission_status_changed"
        ]  # type: ignore[union-attr]
    assert status == {
        interrupted: "paused",
        waiting: "needs_user",
        paused: "paused",
        done: "completed",
    }
    assert events[-1].payload["status"] == "paused" and events[-1].payload["reason"] == REASON
    assert events[-1].payload["previous"] == "running"
    assert await pause_interrupted_missions(app.state.services) == 0  # nothing left to do
    assert (await audit(app, run.id)).ok  # the pause is chained like everything else


async def test_a_mission_whose_runner_is_alive_is_left_alone(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    import asyncio

    mission_id = await mission_in(app, client, repo, "running")
    forever = asyncio.create_task(asyncio.sleep(60))
    app.state.services.mission_tasks[mission_id] = forever
    try:
        assert await pause_interrupted_missions(app.state.services) == 0
    finally:
        forever.cancel()
        app.state.services.mission_tasks.pop(mission_id, None)

    async with app.state.sessionmaker() as session:
        assert (await session.get(Mission, mission_id)).status == "running"  # type: ignore[union-attr]


@needs_docker
async def test_a_paused_mission_resumes_from_its_last_checkpoint_and_finishes(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)
    mission_id = uuid.UUID(mission["id"])
    await sql(app, "UPDATE missions SET status = 'running' WHERE id = :m", m=mission_id)
    await pause_interrupted_missions(app.state.services)

    resumed = await client.post(f"/api/missions/{mission['id']}/resume")

    assert resumed.status_code == 200 and resumed.json()["status"] == "running"
    await finish(app)
    row, features, run = await load(app, mission["id"])
    assert row.status == "completed" and {f.status for f in features.values()} == {"done"}
    assert PLAN["title"] == "Todo app" and (await audit(app, run.id)).ok
