"""Missions: creation from a hand-written plan, the mission folder, and handoff persistence."""

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.db.models import FeatureRow, HandoffRow, Mission, Run
from app.events.log import list_events
from app.missions import folder, service
from app.missions.models import Handoff

PLAN: dict[str, Any] = {
    "title": "Todo app",
    "milestones": [
        {
            "id": "m1-foundation",
            "title": "Foundation",
            "validators": ["code-reviewer"],
            "features": [
                {
                    "id": "todo-schema",
                    "title": "Todo schema",
                    "persona": "data",
                    "expected_behavior": ["a todos table exists"],
                    "target_files": ["db/schema.sql"],
                }
            ],
        },
        {
            "id": "m2-backend",
            "title": "Backend",
            "validators": ["code-reviewer", "security"],
            "features": [
                {
                    "id": "todo-api",
                    "title": "Todo API",
                    "persona": "backend",
                    "description": "CRUD endpoints for todos.",
                    "preconditions": ["the todos table exists"],
                    "expected_behavior": ["POST /todos creates a todo", "tests pass"],
                    "contract_refs": ["openapi.yaml#/paths/~1todos"],
                },
                {
                    "id": "todo-tests",
                    "title": "API tests",
                    "persona": "backend",
                    "expected_behavior": ["every endpoint has a test"],
                },
            ],
        },
    ],
}


def plan(**overrides: Any) -> dict[str, Any]:
    return {**json.loads(json.dumps(PLAN)), **overrides}


async def open_project(client: httpx.AsyncClient, root: Path) -> str:
    return (await client.post("/api/projects", json={"workspace_path": str(root)})).json()["id"]


async def create(
    client: httpx.AsyncClient, project_id: str, body: dict[str, Any] | None = None, **extra: Any
) -> httpx.Response:
    return await client.post(
        "/api/missions",
        json={"project_id": project_id, "idea": "A todo app", "plan": body or PLAN, **extra},
    )


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


async def test_creating_a_mission_stores_the_plan_and_renders_the_mission_folder(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    project_id = await open_project(client, workspace)

    response = await create(client, project_id, budget_usd=2.5)

    assert response.status_code == 201, response.text
    mission = response.json()
    assert mission["status"] == "awaiting_approval" and mission["budget_usd"] == 2.5
    assert [m["id"] for m in mission["milestones"]] == ["m1-foundation", "m2-backend"]
    api = mission["milestones"][1]["features"][0]
    assert (api["id"], api["persona"], api["status"], api["attempts"]) == (
        "todo-api",
        "backend",
        "pending",
        0,
    )
    assert api["preconditions"] == ["the todos table exists"]

    # The mission run: a worktree on the mission branch, based on a snapshot of the workspace.
    async with app.state.sessionmaker() as session:
        run = await session.get(Run, mission["run_id"])
        events = await list_events(session, run.id)
    worktree = Path(run.worktree_path)
    assert worktree.parent == app.state.settings.data_dir / "worktrees"
    assert git_output(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == mission["branch"]
    assert [e.type for e in events] == ["run_created", "mission_status_changed"]

    # features.json follows PRD §9.3 and is rendered from the database.
    document = json.loads((worktree / ".hex" / "mission" / "features.json").read_text())
    assert document["mission_id"] == mission["id"]
    second = document["milestones"][1]
    assert (second["id"], second["validators"]) == ("m2-backend", ["code-reviewer", "security"])
    assert [f["id"] for f in second["features"]] == ["todo-api", "todo-tests"]
    assert second["features"][0] | {"commit": None} == {
        "id": "todo-api",
        "title": "Todo API",
        "persona": "backend",
        "status": "pending",
        "description": "CRUD endpoints for todos.",
        "preconditions": ["the todos table exists"],
        "expected_behavior": ["POST /todos creates a todo", "tests pass"],
        "contract_refs": ["openapi.yaml#/paths/~1todos"],
        "extra_skills": [],
        "target_files": [],
        "attempts": 0,
        "commit": None,
    }
    # The user's own files are untouched.
    assert not (workspace / ".hex").exists()
    assert git_output(workspace, "status", "--porcelain") == ""


async def test_missions_can_be_listed_and_fetched(
    client: httpx.AsyncClient, workspace: Path
) -> None:
    project_id = await open_project(client, workspace)
    created = (await create(client, project_id)).json()

    fetched = (await client.get(f"/api/missions/{created['id']}")).json()
    listed = (await client.get("/api/missions", params={"project_id": project_id})).json()

    assert fetched == created
    assert [m["id"] for m in listed] == [created["id"]]
    missing = await client.get("/api/missions/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


async def test_missions_need_a_git_repository_and_a_known_project(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    project_id = await open_project(client, plain)

    response = await create(client, project_id)
    assert response.status_code == 409 and "Git" in response.json()["detail"]
    unknown = await create(client, "00000000-0000-0000-0000-000000000000")
    assert unknown.status_code == 404


def _with(milestones_edit: Any) -> dict[str, Any]:
    body = plan()
    milestones_edit(body["milestones"])
    return body


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda m: m[1]["features"][0].update(persona="ghost"), "not a worker persona"),
        (lambda m: m[1]["features"][0].update(persona="qa"), "not a worker persona"),
        (lambda m: m[0].update(validators=["backend"]), "not a validator"),
        (lambda m: m[1]["features"][1].update(id="todo-api"), "feature ids must be unique"),
        (lambda m: m[1].update(id="m1-foundation"), "milestone ids must be unique"),
        (lambda m: m[0]["features"][0].update(status="done"), "starts every feature fresh"),
        (lambda m: m[0]["features"][0].update(expected_behavior=[]), "at least 1 item"),
        (lambda m: m[0]["features"][0].update(id="Bad Id"), "string_pattern_mismatch"),
        (lambda m: m[0].update(features=[]), "at least 1 item"),
    ],
)
async def test_a_bad_plan_is_rejected_and_creates_nothing(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path, edit: Any, message: str
) -> None:
    project_id = await open_project(client, workspace)

    response = await create(client, project_id, _with(edit))

    assert response.status_code == 422
    assert message in response.text
    async with app.state.sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Mission)) == 0
    assert not (app.state.settings.data_dir / "worktrees").exists()


async def test_a_failure_while_creating_removes_the_worktree_branch_and_rows(
    app: FastAPI,
    client: httpx.AsyncClient,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = await open_project(client, workspace)

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(folder, "write_features_json", broken)
    with pytest.raises(OSError, match="disk full"):
        await create(client, project_id)

    assert git_output(workspace, "branch", "--list", "hex/mission-*").strip() == ""
    worktrees = app.state.settings.data_dir / "worktrees"
    assert not worktrees.exists() or not any(worktrees.iterdir())
    async with app.state.sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Mission)) == 0
        assert await session.scalar(select(func.count()).select_from(Run)) == 0


async def test_a_handoff_is_recorded_in_the_database_and_in_handoffs_jsonl(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    project_id = await open_project(client, workspace)
    created = (await create(client, project_id)).json()
    handoff = Handoff(
        feature_id="todo-schema",
        persona_id="data",
        model_used="scripted-model",
        implemented=["todos table"],
        procedures_followed=True,
        files_changed=["db/schema.sql"],
    )

    async with app.state.sessionmaker.begin() as session:
        mission = await session.get(Mission, created["id"])
        feature = await session.scalar(
            select(FeatureRow).where(
                FeatureRow.mission_id == mission.id, FeatureRow.key == "todo-schema"
            )
        )
        run = await session.get(Run, mission.run_id)
        worktree = Path(run.worktree_path)
        await service.record_handoff(session, mission, feature, handoff, worktree)
        with pytest.raises(ValueError, match="different feature"):
            other = await session.scalar(
                select(FeatureRow).where(
                    FeatureRow.mission_id == mission.id, FeatureRow.key == "todo-api"
                )
            )
            await service.record_handoff(session, mission, other, handoff, worktree)

    async with app.state.sessionmaker() as session:
        rows = list(await session.scalars(select(HandoffRow)))
    assert len(rows) == 1 and rows[0].data["files_changed"] == ["db/schema.sql"]
    lines = (worktree / ".hex" / "mission" / "handoffs.jsonl").read_text().splitlines()
    assert [json.loads(line)["feature_id"] for line in lines] == ["todo-schema"]


async def test_features_json_follows_the_database(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    project_id = await open_project(client, workspace)
    created = (await create(client, project_id)).json()

    async with app.state.sessionmaker.begin() as session:
        mission = await session.get(Mission, created["id"])
        feature = await session.scalar(
            select(FeatureRow).where(
                FeatureRow.mission_id == mission.id, FeatureRow.key == "todo-schema"
            )
        )
        feature.status, feature.attempts, feature.commit = "done", 1, "abc123"
        await session.flush()
        run = await session.get(Run, mission.run_id)
        await service.sync_mission_folder(session, mission, Path(run.worktree_path))

    document = json.loads((Path(run.worktree_path) / ".hex/mission/features.json").read_text())
    done = document["milestones"][0]["features"][0]
    assert (done["status"], done["attempts"], done["commit"]) == ("done", 1, "abc123")
    assert (await client.get(f"/api/missions/{created['id']}")).json()["milestones"][0]["features"][
        0
    ]["status"] == "done"
