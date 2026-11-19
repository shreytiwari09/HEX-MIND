"""The Mission Control stream: a real WebSocket against a real server, so auth, the snapshot,
replay and live pushes are exercised the way the desktop app will use them."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.api import stream
from app.providers.base import LLMRequest, ProviderError
from app.sandbox.runner import docker_available
from tests.conftest import TOKEN, ScriptedAdapter, use_adapter
from tests.test_mission_runner import Script, approve, finish, new_mission

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


@pytest.fixture
async def base_url(app: FastAPI) -> AsyncIterator[str]:
    """The app served on a real local port (lifespan off: tests start their own services)."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"ws://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def open_stream(
    base_url: str, mission_id: str, *, after_seq: int | None = None, token: str = TOKEN
) -> tuple[ClientConnection, dict[str, Any]]:
    suffix = "" if after_seq is None else f"?after_seq={after_seq}"
    ws = await connect(f"{base_url}/ws/missions/{mission_id}{suffix}")
    await ws.send(json.dumps({"type": "auth", "token": token}))
    return ws, json.loads(await asyncio.wait_for(ws.recv(), 30))


async def read_until(
    ws: ClientConnection, done: Callable[[dict[str, Any]], bool], timeout: float = 150
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with asyncio.timeout(timeout):
        while True:
            frame = json.loads(await ws.recv())
            assert frame["type"] == "event", frame
            events.append(frame["event"])
            if done(frame["event"]):
                return events


def assert_contiguous(events: list[dict[str, Any]], first: int) -> None:
    assert [e["seq"] for e in events] == list(range(first, first + len(events)))


async def closed_with(ws: ClientConnection) -> int:
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(ws.recv(), 10)
    assert ws.close_code is not None
    return ws.close_code


async def test_the_first_frame_must_be_the_token(
    app: FastAPI,
    client: httpx.AsyncClient,
    base_url: str,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission = await new_mission(client, repo)

    wrong = await connect(f"{base_url}/ws/missions/{mission['id']}")
    await wrong.send(json.dumps({"type": "auth", "token": "not-the-token-0123456789"}))
    assert await closed_with(wrong) == stream.UNAUTHORIZED

    monkeypatch.setattr(stream, "AUTH_TIMEOUT_S", 0.3)
    silent = await connect(f"{base_url}/ws/missions/{mission['id']}")  # never sends a frame
    assert await closed_with(silent) == stream.UNAUTHORIZED

    malformed = await connect(f"{base_url}/ws/missions/{mission['id']}")
    await malformed.send(json.dumps({"type": "hello"}))
    assert await closed_with(malformed) == stream.UNAUTHORIZED

    ghost = await connect(f"{base_url}/ws/missions/00000000-0000-0000-0000-000000000000")
    await ghost.send(json.dumps({"type": "auth", "token": TOKEN}))
    assert await closed_with(ghost) == stream.NOT_FOUND


async def test_the_snapshot_then_the_replayed_events_without_gaps(
    app: FastAPI, client: httpx.AsyncClient, base_url: str, repo: Path
) -> None:
    mission = await new_mission(client, repo)

    ws, snapshot = await open_stream(base_url, mission["id"], after_seq=0)
    async with ws:
        events = await read_until(ws, lambda e: e["seq"] == snapshot["last_seq"])

    assert snapshot["type"] == "snapshot" and snapshot["last_seq"] == 2
    assert snapshot["mission"] == mission  # the same view the REST API gives
    assert_contiguous(events, 1)
    assert [e["type"] for e in events] == ["run_created", "mission_status_changed"]
    assert events[1]["payload"] == {
        "status": "awaiting_approval",
        "previous": None,
        "reason": "plan received",
    }
    assert {e["schema_version"] for e in events} == {7}

    # A client that reconnects with its last seq gets only what it missed, and nothing at all
    # replays when it is already up to date.
    ws, _ = await open_stream(base_url, mission["id"], after_seq=1)
    async with ws:
        resumed = await read_until(ws, lambda e: e["seq"] == 2)
        assert [e["seq"] for e in resumed] == [2]
    ws, _ = await open_stream(base_url, mission["id"])  # live only
    async with ws:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(ws.recv(), 0.5)


@needs_docker
async def test_a_running_mission_is_pushed_live_and_matches_the_event_log(
    app: FastAPI, client: httpx.AsyncClient, base_url: str, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)
    ws, snapshot = await open_stream(base_url, mission["id"])  # live only, before anything runs
    assert snapshot["mission"]["status"] == "awaiting_approval"

    async with ws:
        await approve(client, mission)
        events = await read_until(
            ws,
            lambda e: (
                e["type"] == "mission_status_changed" and e["payload"]["status"] == "completed"
            ),
        )
        await finish(app)
        run_id = mission["run_id"]
        log = (await client.get(f"/api/runs/{run_id}/events", params={"limit": 5000})).json()
        events += await read_until(ws, lambda e: e["seq"] == log[-1]["seq"])

        assert_contiguous(events, snapshot["last_seq"] + 1)
        assert [e["seq"] for e in events] == [
            e["seq"] for e in log if e["seq"] > snapshot["last_seq"]
        ]
        assert [e["event_id"] for e in events] == [
            e["event_id"] for e in log if e["seq"] > snapshot["last_seq"]
        ]

        def of(kind: str) -> list[dict[str, Any]]:
            return [e["payload"] for e in events if e["type"] == kind]

        statuses = [(p["previous"], p["status"]) for p in of("mission_status_changed")]
        assert statuses == [("awaiting_approval", "running"), ("running", "completed")]
        assert [(p["feature_id"], p["status"]) for p in of("feature_status_changed")] == [
            ("todo-model", "in_progress"),
            ("todo-model", "done"),
            ("filter-helper", "in_progress"),
            ("filter-helper", "done"),
        ]
        assert [(p["milestone_id"], p["status"]) for p in of("milestone_status_changed")] == [
            ("m1-model", "active"),
            ("m1-model", "completed"),
            ("m2-filter", "active"),
            ("m2-filter", "completed"),
        ]
        handoffs = of("handoff_recorded")
        assert [h["feature_id"] for h in handoffs] == ["todo-model", "filter-helper"]
        assert handoffs[0]["files_changed"] == ["src/todos.js", "src/todos.test.js"]
        assert [p["label"] for p in of("checkpoint_created")] == [
            "todo-model: Todo model",
            "filter-helper: Filter helper",
            "Mission complete",
        ]
        # Events written by the crew's own database work arrive on the same stream.
        kinds = {e["type"] for e in events}
        assert {"llm_call_completed", "tool_called", "a2a_message", "check_completed"} <= kinds

        # Apply and revert show up too, with the reason.
        await client.post(f"/api/missions/{mission['id']}/apply")
        applied = await read_until(ws, lambda e: e["type"] == "mission_status_changed")
        assert applied[-1]["payload"] == {
            "status": "applied",
            "previous": "completed",
            "reason": "applied to your project",
        }


@needs_docker
async def test_needs_you_is_pushed_and_so_is_the_answer(
    app: FastAPI, client: httpx.AsyncClient, base_url: str, repo: Path
) -> None:
    def down(request: LLMRequest) -> Any:
        raise ProviderError("model unavailable", retryable=False)

    use_adapter(app, ScriptedAdapter(down))
    mission = await new_mission(client, repo)
    ws, snapshot = await open_stream(base_url, mission["id"])

    async with ws:
        await approve(client, mission)
        events = await read_until(ws, lambda e: e["type"] == "need_raised")
        raised = events[-1]["payload"]
        assert raised["kind"] == "provider_unavailable" and raised["options"] == ["retry", "stop"]
        assert raised["feature_id"] == "todo-model"
        assert [
            (e["payload"]["previous"], e["payload"]["status"])
            for e in events
            if e["type"] == "mission_status_changed"
        ] == [("awaiting_approval", "running"), ("running", "needs_user")]

        await finish(app)
        answer = await client.post(
            f"/api/needs/{raised['need_id']}/answer", json={"action": "stop"}
        )
        assert answer.status_code == 200
        after = await read_until(ws, lambda e: e["type"] == "run_cancelled")
        assert [
            e["type"] for e in after if e["type"] in ("need_answered", "mission_status_changed")
        ] == [
            "need_answered",
            "mission_status_changed",
        ]
        answered = next(e for e in after if e["type"] == "need_answered")
        assert answered["payload"] == {"need_id": raised["need_id"], "action": "stop"}
        assert_contiguous(events + after, snapshot["last_seq"] + 1)
