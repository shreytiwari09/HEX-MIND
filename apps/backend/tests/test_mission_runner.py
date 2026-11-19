"""The MissionRunner end to end: real worktrees, real git checkpoints, the real MCP/A2A path and
Docker quick checks. Only the language model is scripted."""

import asyncio
import json
import re
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import (
    Checkpoint,
    FeatureRow,
    HandoffRow,
    LLMCall,
    Mission,
    Need,
    Run,
)
from app.events.log import list_events
from app.providers.base import Completion, LLMRequest, ProviderError, ToolCall
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_missions import git_output
from tests.test_run_workflow import FILTER_JS, FILTER_TEST, TODOS_JS, TODOS_TEST

pytestmark = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

FAILING_TEST = """const test = require('node:test')
const assert = require('node:assert/strict')

test('addTodo works', () => assert.equal(1, 2))
"""
RETRY_MARK = "Your previous attempt was not accepted"

PLAN = {
    "title": "Todo app",
    "milestones": [
        {
            "id": "m1-model",
            "title": "Model",
            "features": [
                {
                    "id": "todo-model",
                    "title": "Todo model",
                    "persona": "backend",
                    "expected_behavior": ["addTodo and toggleTodo work"],
                }
            ],
        },
        {
            "id": "m2-filter",
            "title": "Filtering",
            "features": [
                {
                    "id": "filter-helper",
                    "title": "Filter helper",
                    "persona": "frontend",
                    "expected_behavior": ["filterTodos supports all, active and done"],
                }
            ],
        },
    ],
}
GOOD = {
    "Todo model": [("src/todos.js", TODOS_JS), ("src/todos.test.js", TODOS_TEST)],
    "Filter helper": [("src/filter.js", FILTER_JS), ("src/filter.test.js", FILTER_TEST)],
}


def report(title: str) -> str:
    return json.dumps(
        {
            "implemented": [title],
            "left_undone": [],
            "issues_found": [],
            "procedures_followed": True,
            "notes_for_next": [f"{title} is in place"],
        }
    )


class Script:
    """Plays the worker personas. `files[(title, round)]` lists what to write in that round
    (round 0 is the first attempt; a retry's prompt carries the feedback marker). A round that is
    not scripted repeats the title's last scripted one."""

    def __init__(self, files: dict[tuple[str, int], list[tuple[str, str]]] | None = None) -> None:
        self.files = files or {(title, 0): written for title, written in GOOD.items()}
        self.attempts: defaultdict[str, int] = defaultdict(int)
        self.steps: defaultdict[tuple[str, int], int] = defaultdict(int)
        # The prompt of each attempt's first model call, per feature title.
        self.prompts: defaultdict[str, list[str]] = defaultdict(list)

    def __call__(self, request: LLMRequest) -> Completion:
        assert request.purpose == "coder", request.purpose
        prompt = "\n".join(m.content or "" for m in request.messages)
        title = re.search(r"(?m)^Feature: (.+)$", prompt).group(1).strip()  # type: ignore[union-attr]
        if not any(m.role == "tool" for m in request.messages):  # an attempt's first call
            self.attempts[title] += 1
            self.prompts[title].append(prompt)
        attempt = self.attempts[title]
        round_ = prompt.count(RETRY_MARK)
        scripted = [r for (t, r) in self.files if t == title and r <= round_]
        written = self.files[(title, max(scripted))]
        step = self.steps[(title, attempt)]
        self.steps[(title, attempt)] += 1
        if step < len(written):
            path, content = written[step]
            call = ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name="write_file",
                arguments={"path": path, "content": content},
            )
            return Completion(tool_calls=[call])
        return Completion(content=report(title))


class GatedAdapter(ScriptedAdapter):
    """Holds the first request of one feature until the test lets it go."""

    def __init__(self, handler: Any, title: str) -> None:
        super().__init__(handler)
        self.title = title
        self.reached = asyncio.Event()
        self.gate = asyncio.Event()

    async def complete(self, request: LLMRequest) -> Completion:
        prompt = "\n".join(m.content or "" for m in request.messages)
        if f"Feature: {self.title}" in prompt and not self.reached.is_set():
            self.reached.set()
            await self.gate.wait()
        return await super().complete(request)


async def new_mission(
    client: httpx.AsyncClient, root: Path, plan: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    project = (await client.post("/api/projects", json={"workspace_path": str(root)})).json()
    response = await client.post(
        "/api/missions",
        json={"project_id": project["id"], "idea": "A todo app", "plan": plan or PLAN, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def approve(client: httpx.AsyncClient, mission: dict[str, Any]) -> httpx.Response:
    return await client.post(f"/api/missions/{mission['id']}/approve")


async def finish(app: FastAPI) -> None:
    await asyncio.wait_for(app.state.services.background.wait_all(), timeout=300)


async def load(app: FastAPI, mission_id: str) -> tuple[Mission, dict[str, FeatureRow], Run]:
    async with app.state.sessionmaker() as session:
        mission = await session.get(Mission, uuid.UUID(mission_id))
        assert mission is not None
        features = {
            f.key: f
            for f in await session.scalars(
                select(FeatureRow).where(FeatureRow.mission_id == mission.id)
            )
        }
        run = await session.get(Run, mission.run_id)
        assert run is not None
        return mission, features, run


async def needs(app: FastAPI, mission_id: str) -> list[Need]:
    async with app.state.sessionmaker() as session:
        return list(
            await session.scalars(
                select(Need)
                .where(Need.mission_id == uuid.UUID(mission_id))
                .order_by(Need.created_at)
            )
        )


async def test_a_two_milestone_mission_runs_end_to_end(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    script = Script()
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo)

    assert (await approve(client, mission)).json()["status"] == "running"
    await finish(app)

    row, features, run = await load(app, mission["id"])
    assert row.status == "completed" and row.finished_at is not None
    assert run.status == "completed"
    assert [(f.status, f.attempts) for f in features.values()] == [("done", 1), ("done", 1)]
    worktree = Path(run.worktree_path or "")
    assert (worktree / "src" / "todos.js").read_text() == TODOS_JS
    assert (worktree / "src" / "filter.js").read_text() == FILTER_JS
    assert not (repo / "src").exists()  # the user's files are untouched until apply

    # One checkpoint commit per feature, named after it, plus the closing mission-files commit.
    log = git_output(worktree, "log", "--format=%s", row.branch).splitlines()
    assert log[:3] == [
        "Mission complete: update mission files",
        "filter-helper: Filter helper",
        "todo-model: Todo model",
    ]
    async with app.state.sessionmaker() as session:
        checkpoints = list(
            await session.scalars(select(Checkpoint).order_by(Checkpoint.created_at))
        )
        handoffs = list(await session.scalars(select(HandoffRow).order_by(HandoffRow.created_at)))
        events = await list_events(session, run.id)
    assert [c.label for c in checkpoints] == [
        "todo-model: Todo model",
        "filter-helper: Filter helper",
        "Mission complete",
    ]
    assert features["todo-model"].commit == checkpoints[0].commit

    # Handoffs carry measured facts, not the agent's claims.
    first = handoffs[0].data
    assert first["files_changed"] == ["src/todos.js", "src/todos.test.js"]  # from git, no .hex/
    assert first["model_used"] == "scripted:scripted-model"  # from llm_calls
    assert [(c["exit_code"], c["command"]) for c in first["commands"]] == [(0, "node --test")]
    assert "pass" in first["commands"][0]["summary"]
    # The second worker sees the first one's handoff, not its chat history.
    assert any("Todo model is in place" in p for p in script.prompts["Filter helper"])
    assert not any("Filter helper" in p for p in script.prompts["Todo model"])

    folder = worktree / ".hex" / "mission"
    document = json.loads((folder / "features.json").read_text())
    assert [m["status"] for m in document["milestones"]] == ["completed", "completed"]
    assert [f["commit"] for m in document["milestones"] for f in m["features"]] == [
        checkpoints[0].commit,
        checkpoints[1].commit,
    ]
    assert len((folder / "handoffs.jsonl").read_text().splitlines()) == 2
    types = [e.type for e in events]
    assert types.count("check_completed") == 2 and types.count("run_completed") == 1
    assert "run_failed" not in types


async def test_a_failed_check_is_retried_with_the_exact_findings(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    script = Script(
        {
            ("Todo model", 0): GOOD["Todo model"],
            ("Filter helper", 0): [
                ("src/filter.js", FILTER_JS),
                ("src/filter.test.js", FAILING_TEST),
            ],
            ("Filter helper", 1): GOOD["Filter helper"],
        }
    )
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "completed"
    assert (features["filter-helper"].status, features["filter-helper"].attempts) == ("done", 2)
    retry_prompt = script.prompts["Filter helper"][-1]
    assert RETRY_MARK in retry_prompt and "check is failing" in retry_prompt
    async with app.state.sessionmaker() as session:
        handoffs = list(await session.scalars(select(HandoffRow)))
    assert len(handoffs) == 2  # only accepted attempts produce a handoff


@pytest.mark.parametrize(
    ("written", "finding"),
    [
        ([], "did not change any files"),
        ([("src/todos.js", TODOS_JS)], "ran NO tests"),
        ([("src/todos.js", TODOS_JS), ("src/todos.test.js", FAILING_TEST)], "FAILED"),
    ],
)
async def test_unaccepted_work_ends_in_needs_you_with_the_evidence_then_skip_continues(
    app: FastAPI,
    client: httpx.AsyncClient,
    repo: Path,
    written: list[tuple[str, str]],
    finding: str,
) -> None:
    script = Script({("Todo model", 0): written, ("Filter helper", 0): GOOD["Filter helper"]})
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    row, features, run = await load(app, mission["id"])
    assert row.status == "needs_user" and run.status == "running"
    assert (features["todo-model"].status, features["todo-model"].attempts) == ("failed", 3)
    assert features["filter-helper"].status == "pending"  # never started
    [need] = await needs(app, mission["id"])
    assert need.kind == "feature_failed" and need.status == "open"
    assert need.options == ["retry", "skip", "stop"]
    assert need.evidence["attempts"] == 3 and finding in need.evidence["last_findings"]
    assert len(script.prompts["Todo model"]) == 3  # the first try and two retries
    worktree = Path(run.worktree_path or "")

    # Skipping drops the unaccepted work and the mission carries on.
    response = await client.post(f"/api/needs/{need.id}/answer", json={"action": "skip"})
    assert response.status_code == 200 and response.json()["status"] == "running"
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "completed"
    assert (features["todo-model"].status, features["filter-helper"].status) == ("skipped", "done")
    assert not (worktree / "src" / "todos.js").exists()  # reset to the last checkpoint
    assert (worktree / "src" / "filter.js").exists()
    [answered] = await needs(app, mission["id"])
    assert answered.status == "answered" and answered.answer == {
        "action": "skip",
        "budget_usd": None,
    }


async def test_a_provider_outage_is_not_an_attempt(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    def down(request: LLMRequest) -> Completion:
        raise ProviderError("model unavailable", retryable=False)

    use_adapter(app, ScriptedAdapter(down))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "needs_user"
    assert (features["todo-model"].status, features["todo-model"].attempts) == ("pending", 0)
    [need] = await needs(app, mission["id"])
    assert need.kind == "provider_unavailable" and need.options == ["retry", "stop"]
    assert "did not count as an attempt" in need.summary

    use_adapter(app, ScriptedAdapter(Script()))  # the provider is back
    await client.post(f"/api/needs/{need.id}/answer", json={"action": "retry"})
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "completed"
    assert features["todo-model"].attempts == 1


async def test_pause_finishes_the_step_in_flight_and_resume_continues(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    adapter = GatedAdapter(Script(), "Todo model")
    use_adapter(app, adapter)
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await asyncio.wait_for(adapter.reached.wait(), timeout=60)
    paused = await client.post(f"/api/missions/{mission['id']}/pause")
    assert paused.json()["status"] == "paused"
    # The runner is still finishing its step, so a resume has to wait.
    early = await client.post(f"/api/missions/{mission['id']}/resume")
    assert early.status_code == 409
    adapter.gate.set()
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "paused"
    assert features["todo-model"].status == "done"  # the step in flight finished
    assert features["filter-helper"].status == "pending"  # and nothing new started

    resumed = await client.post(f"/api/missions/{mission['id']}/resume")
    assert resumed.json()["status"] == "running"
    await finish(app)
    row, features, _ = await load(app, mission["id"])
    assert row.status == "completed" and features["filter-helper"].status == "done"


async def test_stop_cancels_the_mission_and_its_run(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    adapter = GatedAdapter(Script(), "Todo model")
    use_adapter(app, adapter)
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await asyncio.wait_for(adapter.reached.wait(), timeout=60)
    stopped = await client.post(f"/api/missions/{mission['id']}/stop")
    assert stopped.json()["status"] == "cancelled"
    adapter.gate.set()
    await finish(app)

    row, features, run = await load(app, mission["id"])
    assert (row.status, run.status) == ("cancelled", "cancelled")
    assert features["filter-helper"].status == "pending"
    async with app.state.sessionmaker() as session:
        types = [e.type for e in await list_events(session, run.id)]
    assert types.count("run_cancelled") == 1
    assert (await client.post(f"/api/missions/{mission['id']}/resume")).status_code == 409


async def test_the_budget_pauses_the_mission_until_the_user_raises_it(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo, budget_usd=0.25)
    async with app.state.sessionmaker.begin() as session:  # real spend, recorded earlier
        session.add(
            LLMCall(
                run_id=uuid.UUID(mission["run_id"]),
                purpose="coder",
                provider="scripted",
                model="m",
                latency_ms=5,
                est_cost_usd=Decimal("0.5"),
            )
        )

    await approve(client, mission)
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "needs_user" and features["todo-model"].attempts == 0
    [need] = await needs(app, mission["id"])
    assert need.kind == "budget_reached" and need.options == ["raise_budget", "stop"]
    shown = (await client.get(f"/api/missions/{mission['id']}")).json()
    assert shown["spent_usd"] == 0.5 and shown["budget_usd"] == 0.25

    too_low = await client.post(
        f"/api/needs/{need.id}/answer", json={"action": "raise_budget", "budget_usd": 0.4}
    )
    assert too_low.status_code == 409 and "above the" in too_low.json()["detail"]
    raised = await client.post(
        f"/api/needs/{need.id}/answer", json={"action": "raise_budget", "budget_usd": 5}
    )
    assert raised.json()["status"] == "running"
    await finish(app)
    assert (await load(app, mission["id"]))[0].status == "completed"


async def test_lifecycle_guards(app: FastAPI, client: httpx.AsyncClient, repo: Path) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)
    ghost = "00000000-0000-0000-0000-000000000000"

    assert (await client.post(f"/api/missions/{mission['id']}/pause")).status_code == 409
    assert (await client.post(f"/api/missions/{mission['id']}/resume")).status_code == 409
    assert (await client.post(f"/api/missions/{ghost}/approve")).status_code == 404
    assert (
        await client.post(f"/api/needs/{ghost}/answer", json={"action": "stop"})
    ).status_code == 404
    await approve(client, mission)
    assert (await approve(client, mission)).status_code == 409  # already approved
    await finish(app)
    assert (await client.get(f"/api/missions/{mission['id']}/needs")).json() == []


async def test_only_the_last_attempt_asks_for_the_escalation_model(
    app: FastAPI, client: httpx.AsyncClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.missions import runner as runner_module

    seen: list[bool] = []
    real = runner_module.call_crew

    async def spy(role: str, **kwargs: Any) -> str:
        seen.append(kwargs["request"].escalate)
        return await real(role, **kwargs)

    monkeypatch.setattr(runner_module, "call_crew", spy)
    script = Script({("Todo model", 0): [], ("Filter helper", 0): GOOD["Filter helper"]})
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    # Three attempts at the failing feature: the first two normal, the third escalated.
    assert seen == [False, False, True]
