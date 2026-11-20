"""Coordination backends (PRD §9.8): the same mission runs on the blackboard or by messaging.

With messaging the workers have no mission board: no board tools, no reading `.hex/mission/`, and
everything they need travels in the request. A request that times out is sent again with the same
exchange id and the crew service does the work only once."""

import asyncio
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.a2a import client as a2a_client
from app.a2a.client import CrewCallFailed, CrewCallTimedOut, call_crew_with_resend
from app.a2a.server import CrewExecutor
from app.agents.build import feature_prompt, tool_names_for
from app.agents.persona import builtin_personas
from app.agents.tools import BOARD_TOOLS
from app.events.log import list_events
from app.mcp_server.tools import ToolError
from app.missions.models import Feature, MissionContext
from app.providers.base import Completion, LLMRequest
from app.sandbox.runner import docker_available
from app.workspace import git
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mcp_tools import HANDOFF, make, mission_files
from tests.test_mission_runner import PLAN, Script, approve, finish, load, new_mission

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

CONTRACT_PLAN = {
    **PLAN,
    "validation_contract": [
        {"id": "VC-1", "text": "addTodo trims titles", "how": "unit test", "feature": "todo-model"},
        {
            "id": "VC-2",
            "text": "filterTodos supports done",
            "how": "unit test",
            "feature": "filter-helper",
        },
    ],
}


# ---------- what a messaging worker cannot see ----------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "wt"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.js").write_text("one\n")
    git.init_repo(root)
    return root


def test_a_messaging_worker_cannot_read_the_mission_board(
    tree: Path,
    tmp_path: Path,
) -> None:
    mission_files(tree, [HANDOFF])
    (tree / ".hex" / "run-contract.json").write_text("{}")
    board = make(tree, tmp_path, coordination="blackboard")
    messaging = make(tree, tmp_path, coordination="messaging")

    assert "todo-model" in board.read_file(".hex/mission/features.json")  # the default still works
    for path in (
        ".hex/mission/features.json",
        ".hex/mission/handoffs.jsonl",
        "./.hex//mission/validation-contract.md",
        ".HEX/Mission/features.json",
    ):
        with pytest.raises(ToolError, match="mission board is not available"):
            messaging.read_file(path)
    with pytest.raises(ToolError, match="mission board is not available"):
        messaging.list_features()
    with pytest.raises(ToolError, match="mission board is not available"):
        messaging.get_feature_context("todo-model")

    assert not any(p.startswith(".hex/mission") for p in messaging.list_files().splitlines())
    assert any(p.startswith(".hex/mission") for p in board.list_files().splitlines())
    assert messaging.search_code("addTodo") == "(no matches)"  # the board mentions it, src does not
    assert "addTodo" in board.search_code("addTodo")
    assert messaging.read_file("src/a.js") == "one\n"  # the code itself is shared in both modes


def test_messaging_workers_are_not_offered_the_board_tools() -> None:
    for persona in builtin_personas().values():
        assert not set(BOARD_TOOLS) & set(tool_names_for(persona, coordination="messaging"))
    backend = builtin_personas()["backend"]
    assert set(BOARD_TOOLS) <= set(tool_names_for(backend))
    assert "write_file" in tool_names_for(backend, coordination="messaging")


def test_the_prompt_carries_the_criteria_only_when_they_are_sent(tmp_path: Path) -> None:
    feature = Feature(
        id="todo-model", title="Todo model", persona="backend", expected_behavior=["it works"]
    )
    ctx = MissionContext(worktree=tmp_path, workspace=tmp_path)
    backend = builtin_personas()["backend"]

    sent = feature_prompt(
        backend, feature, ctx, criteria=["VC-1: addTodo trims titles   [unit test]"]
    )
    plain = feature_prompt(backend, feature, ctx)

    assert "VC-1: addTodo trims titles" in sent and "no access to the mission board" in sent
    assert "Validation criteria" not in plain


# ---------- the same mission on both backends ----------


class Recording(Script):
    """The scripted workers, remembering which tools each attempt was offered."""

    def __init__(self) -> None:
        super().__init__()
        self.tools: defaultdict[str, set[str]] = defaultdict(set)

    def __call__(self, request: LLMRequest) -> Completion:
        for tool in request.tools or []:
            self.tools[self._title(request)].add(tool["function"]["name"])
        return super().__call__(request)

    @staticmethod
    def _title(request: LLMRequest) -> str:
        prompt = "\n".join(m.content or "" for m in request.messages)
        return next(
            line[len("Feature: ") :].strip()
            for line in prompt.splitlines()
            if line.startswith("Feature: ")
        )


@needs_docker
@pytest.mark.parametrize("coordination", ["blackboard", "messaging"])
async def test_the_same_mission_completes_on_either_backend(
    app: FastAPI, client: httpx.AsyncClient, repo: Path, coordination: str
) -> None:
    script = Recording()
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo, CONTRACT_PLAN, coordination=coordination)
    assert mission["coordination"] == coordination

    assert (await approve(client, mission)).json()["status"] == "running"
    await finish(app)

    row, features, run = await load(app, mission["id"])
    assert row.status == "completed" and row.coordination == coordination
    assert [(f.status, f.attempts) for f in features.values()] == [("done", 1), ("done", 1)]
    worktree = Path(run.worktree_path or "")
    assert (worktree / "src" / "todos.js").exists() and (worktree / "src" / "filter.js").exists()

    offered = set().union(*script.tools.values())
    first = script.prompts["Todo model"][0]
    second = script.prompts["Filter helper"][0]
    assert "Todo model is in place" in second  # handoffs travel in the message in both modes
    if coordination == "messaging":
        assert not offered & set(BOARD_TOOLS)
        assert "VC-1: addTodo trims titles" in first and "VC-2" not in first
        assert "VC-2: filterTodos supports done" in second
    else:
        assert set(BOARD_TOOLS) <= offered
        assert "VC-1" not in first  # a blackboard worker reads its criteria from the board


async def test_the_coordination_is_validated_and_defaults_to_the_blackboard(
    client: httpx.AsyncClient, repo: Path
) -> None:
    project = (await client.post("/api/projects", json={"workspace_path": str(repo)})).json()
    body = {"project_id": project["id"], "idea": "A todo app", "plan": PLAN}

    default = await client.post("/api/missions", json=body)
    bad = await client.post("/api/missions", json={**body, "coordination": "telepathy"})

    assert default.status_code == 201 and default.json()["coordination"] == "blackboard"
    assert bad.status_code == 422


# ---------- timeout, resend and the idempotency key ----------


async def test_a_request_that_timed_out_is_sent_again_unchanged() -> None:
    sent: list[uuid.UUID] = []

    class Request:
        exchange_id = uuid.uuid4()

    async def flaky(**kwargs: Any) -> str:
        sent.append(kwargs["request"].exchange_id)
        if len(sent) < 3:
            raise CrewCallTimedOut("no answer")
        return "done"

    original = a2a_client.call_crew
    a2a_client.call_crew = flaky  # type: ignore[assignment]
    try:
        assert await call_crew_with_resend(resends=2, request=Request()) == "done"
        sent.clear()
        with pytest.raises(CrewCallTimedOut):
            await call_crew_with_resend(resends=1, request=Request())
        assert len(sent) == 2 and len(set(sent)) == 1  # the same idempotency key every time
    finally:
        a2a_client.call_crew = original  # type: ignore[assignment]


async def test_other_failures_are_not_resent() -> None:
    calls = 0

    async def broken(**kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        raise CrewCallFailed("the crew failed")

    original = a2a_client.call_crew
    a2a_client.call_crew = broken  # type: ignore[assignment]
    try:
        with pytest.raises(CrewCallFailed):
            await call_crew_with_resend(resends=3)
    finally:
        a2a_client.call_crew = original  # type: ignore[assignment]
    assert calls == 1


async def test_the_crew_service_does_the_work_once_per_exchange() -> None:
    executor = CrewExecutor(services=None, role="persona")  # type: ignore[arg-type]
    started = asyncio.Event()
    release = asyncio.Event()
    runs: list[str] = []

    async def slow(request: Any, prompt: str, hub: Any) -> str:
        runs.append(str(request.exchange_id))
        started.set()
        await release.wait()
        return f"result {len(runs)}"

    executor._run_crew = slow  # type: ignore[method-assign]

    class Request:
        def __init__(self, exchange_id: uuid.UUID) -> None:
            self.exchange_id = exchange_id

    key = uuid.uuid4()
    first = asyncio.ensure_future(executor._once(Request(key), "p", None))  # type: ignore[arg-type]
    await started.wait()
    first.cancel()  # the caller's connection timed out; the work must carry on
    again = asyncio.ensure_future(executor._once(Request(key), "p", None))  # type: ignore[arg-type]
    release.set()

    assert await again == "result 1"
    assert await executor._once(Request(key), "p", None) == "result 1"  # type: ignore[arg-type]
    assert await executor._once(Request(uuid.uuid4()), "p", None) == "result 2"  # type: ignore[arg-type]
    assert len(runs) == 2


@needs_docker
async def test_a_lost_reply_is_resent_without_running_the_feature_twice(
    app: FastAPI, client: httpx.AsyncClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Recording()
    use_adapter(app, ScriptedAdapter(script))
    real = a2a_client.call_crew
    lost: list[str] = []

    async def lose_first_reply(**kwargs: Any) -> str:
        text = await real(**kwargs)  # the crew did the work ...
        if not lost:
            lost.append(str(kwargs["request"].exchange_id))
            raise CrewCallTimedOut("the reply never arrived")  # ... but the answer was lost
        return text

    monkeypatch.setattr(a2a_client, "call_crew", lose_first_reply)
    mission = await new_mission(client, repo, CONTRACT_PLAN, coordination="messaging")

    await approve(client, mission)
    await finish(app)

    row, features, run = await load(app, mission["id"])
    assert row.status == "completed"
    assert script.attempts["Todo model"] == 1  # one model run, though the request was sent twice
    async with app.state.sessionmaker() as session:
        events = await list_events(session, run.id)
    sent = [
        e
        for e in events
        if e.type == "a2a_message"
        and e.payload.get("side") == "client"
        and e.payload.get("direction") == "sent"
        and e.payload.get("exchange_id") == lost[0]
    ]
    assert len(sent) == 2  # visible in the trail: the same exchange, sent twice
