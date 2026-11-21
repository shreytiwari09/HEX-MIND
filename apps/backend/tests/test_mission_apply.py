"""Applying a finished mission to the user's project, and undoing it: stale-file refusal, commits,
revert, keep, discard and checkpoint restore. Missions run for real (see test_mission_runner);
only the model is scripted."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import Checkpoint, HandoffRow, Mission
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import (
    FILTER_JS,
    TODOS_JS,
    Script,
    approve,
    finish,
    load,
    new_mission,
)
from tests.test_missions import git_output

pytestmark = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

MISSION_NOTES = {".hex/mission/features.json", ".hex/mission/handoffs.jsonl"}
APPLIED_FILES = {
    "src/filter.js",
    "src/filter.test.js",
    "src/todos.js",
    "src/todos.test.js",
}


async def completed(
    app: FastAPI, client: httpx.AsyncClient, root: Path, **extra: Any
) -> dict[str, Any]:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, root, **extra)
    await approve(client, mission)
    await finish(app)
    return mission


def post(client: httpx.AsyncClient, mission: dict[str, Any], action: str, **body: Any):
    return client.post(f"/api/missions/{mission['id']}/{action}", json=body or None)


def mission_branch(root: Path, mission: dict[str, Any]) -> str:
    return git_output(
        root, "branch", "--list", f"hex/mission-{mission['id'].replace('-', '')[:12]}"
    ).strip()


def committed_files(root: Path, ref: str = "HEAD") -> set[str]:
    return set(git_output(root, "show", "--name-only", "--format=", ref).split())


async def test_apply_writes_the_changes_and_commits_only_them(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await completed(app, client, repo)
    (repo / "notes.txt").write_text("my own work in progress\n")  # unrelated, uncommitted
    before = git_output(repo, "rev-parse", "HEAD").strip()

    diff = (await client.get(f"/api/missions/{mission['id']}/diff")).json()
    assert {f["path"] for f in diff["files"]} == APPLIED_FILES | MISSION_NOTES
    assert {f["status"] for f in diff["files"]} == {"pending"}
    assert not (repo / "src").exists()  # reviewing changes nothing

    response = await post(client, mission, "apply")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "applied"
    assert set(body["apply"]["files"]) == APPLIED_FILES
    assert body["apply"]["state"] == "applied" and body["apply"]["include_mission_files"] is False
    assert (repo / "src" / "todos.js").read_text() == TODOS_JS
    assert (repo / "src" / "filter.js").read_text() == FILTER_JS
    # One commit on the user's branch with exactly the mission's files, not their own work.
    assert git_output(repo, "rev-parse", "HEAD~1").strip() == before
    assert body["apply"]["commit"] == git_output(repo, "rev-parse", "HEAD").strip()
    assert committed_files(repo) == APPLIED_FILES
    assert git_output(repo, "log", "-1", "--format=%s").strip() == "H.E.X Mind: Todo app"
    assert git_output(repo, "status", "--porcelain").strip() == "?? notes.txt"
    after = (await client.get(f"/api/missions/{mission['id']}/diff")).json()["files"]
    assert {f["path"] for f in after} == APPLIED_FILES  # read from the apply commit now
    assert {f["status"] for f in after} == {"applied"}
    assert next(f for f in after if f["path"] == "src/todos.js")["modified"] == TODOS_JS
    _, _, run = await load(app, mission["id"])
    assert run.pre_apply_commit
    assert (await post(client, mission, "apply")).status_code == 409  # not twice


async def test_apply_cleans_up_the_working_copy_and_keeps_the_team_notes_out(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await completed(app, client, repo)
    _, _, run = await load(app, mission["id"])
    worktree = Path(run.worktree_path)
    assert worktree.is_dir()

    assert (await post(client, mission, "apply")).status_code == 200

    _, _, run = await load(app, mission["id"])
    assert run.worktree_path is None and not worktree.exists()  # the copy is gone
    assert mission_branch(repo, mission) == ""  # and so is its branch
    assert not (repo / ".hex" / "mission").exists()  # the team's notes stay out of the project
    # Revert still works without the working copy
    assert (await post(client, mission, "revert")).status_code == 200
    assert not (repo / "src" / "todos.js").exists()
    # and it can go in again, rebuilt from the apply commit
    assert (await post(client, mission, "apply")).status_code == 200
    assert (repo / "src" / "todos.js").read_text() == TODOS_JS


async def test_the_startup_sweep_removes_copies_left_by_older_versions(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    from app.missions.cleanup import clean_finished_worktrees

    mission = await completed(app, client, repo)
    _, _, run = await load(app, mission["id"])
    worktree = Path(run.worktree_path)
    async with app.state.sessionmaker.begin() as session:  # as an older version left it
        row = await session.get(Mission, uuid.UUID(mission["id"]))
        row.status = "discarded"

    assert await clean_finished_worktrees(app.state.services) == 1

    _, _, run = await load(app, mission["id"])
    assert run.worktree_path is None and not worktree.exists()
    assert await clean_finished_worktrees(app.state.services) == 0


async def test_apply_can_skip_the_mission_files_and_the_commit(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await completed(app, client, repo)
    before = git_output(repo, "rev-parse", "HEAD").strip()

    response = await post(client, mission, "apply", include_mission_files=False, commit=False)

    body = response.json()
    assert set(body["apply"]["files"]) == APPLIED_FILES
    assert body["apply"]["commit"] is None
    assert not (repo / ".hex").exists()
    assert git_output(repo, "rev-parse", "HEAD").strip() == before  # nothing committed
    assert "?? src/" in git_output(repo, "status", "--porcelain")


async def test_a_file_you_changed_since_the_mission_started_blocks_apply(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = tmp_path / "todo-app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "todos.js").write_text("// original\n")
    from app.workspace import git

    git.init_repo(root)
    mission = await completed(app, client, root)
    (root / "src" / "todos.js").write_text("// edited by the user meanwhile\n")

    response = await post(client, mission, "apply")

    assert response.status_code == 409
    assert response.json()["detail"]["paths"] == ["src/todos.js"]
    assert (root / "src" / "todos.js").read_text() == "// edited by the user meanwhile\n"
    assert not (root / "src" / "filter.js").exists()  # nothing at all was applied
    assert (await load(app, mission["id"]))[0].status == "completed"


async def test_revert_restores_the_project_and_refuses_after_later_edits(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = tmp_path / "todo-app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "todos.js").write_text("// original\n")
    from app.workspace import git

    git.init_repo(root)
    mission = await completed(app, client, root)
    applied = (await post(client, mission, "apply")).json()
    assert (root / "src" / "todos.js").read_text() == TODOS_JS

    (root / "src" / "filter.js").write_text("// I changed this after applying\n")
    refused = await post(client, mission, "revert")
    assert refused.status_code == 409
    assert refused.json()["detail"]["paths"] == ["src/filter.js"]
    assert (root / "src" / "todos.js").read_text() == TODOS_JS  # nothing was reverted

    (root / "src" / "filter.js").write_text(FILTER_JS)  # back to what was applied
    reverted = await post(client, mission, "revert")

    assert reverted.status_code == 200 and reverted.json()["status"] == "completed"
    assert reverted.json()["apply"]["state"] == "reverted"
    assert (root / "src" / "todos.js").read_text() == "// original\n"  # restored, not deleted
    assert not (root / "src" / "filter.js").exists()  # added files are removed
    assert not (root / ".hex").exists()
    assert git_output(root, "status", "--porcelain").strip() == ""
    assert git_output(root, "log", "-1", "--format=%s").strip() == "Revert H.E.X Mind: Todo app"
    assert applied["apply"]["commit"] != git_output(root, "rev-parse", "HEAD").strip()
    assert (await post(client, mission, "revert")).status_code == 409  # nothing left to revert
    assert (await post(client, mission, "apply")).status_code == 200  # and it can go in again


async def test_keep_then_apply_and_the_states_that_do_not_allow_it(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    fresh = await new_mission(client, repo)
    assert (await post(client, fresh, "apply")).status_code == 409  # not finished
    assert (await post(client, fresh, "keep")).status_code == 409
    assert (await post(client, fresh, "revert")).status_code == 409
    await approve(client, fresh)
    await finish(app)

    kept = await post(client, fresh, "keep")
    assert kept.json()["status"] == "kept"
    assert (await post(client, fresh, "apply")).json()["status"] == "applied"
    ghost = "00000000-0000-0000-0000-000000000000"
    assert (await client.post(f"/api/missions/{ghost}/apply")).status_code == 404


async def test_discard_removes_the_worktree_and_branch_but_not_a_revert(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    # a finished mission you do not want: its copy and branch go
    mission = await completed(app, client, repo)
    row, _, run = await load(app, mission["id"])
    worktree = Path(run.worktree_path or "")
    assert worktree.is_dir()

    discarded = await post(client, mission, "discard")

    assert discarded.json()["status"] == "discarded"
    assert not worktree.exists()
    assert git_output(repo, "branch", "--list", row.branch).strip() == ""
    assert (await load(app, mission["id"]))[2].worktree_path is None
    assert (await client.get(f"/api/missions/{mission['id']}/diff")).status_code == 409
    assert (await post(client, mission, "discard")).status_code == 409


async def test_discarding_an_applied_mission_keeps_its_files_and_its_revert(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await completed(app, client, repo)
    await post(client, mission, "apply")

    assert (await post(client, mission, "discard")).json()["status"] == "discarded"
    assert (repo / "src" / "todos.js").exists()  # the applied files stay in the project


async def test_discarding_a_mission_that_needs_you_closes_its_run_and_items(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    from app.providers.base import ProviderError

    def down(request: Any) -> Any:
        raise ProviderError("model unavailable", retryable=False)

    use_adapter(app, ScriptedAdapter(down))
    mission = await new_mission(client, repo)
    await approve(client, mission)
    await finish(app)
    assert (await load(app, mission["id"]))[0].status == "needs_user"

    assert (await post(client, mission, "discard")).json()["status"] == "discarded"

    _, _, run = await load(app, mission["id"])
    assert run.status == "cancelled"
    items = (await client.get(f"/api/missions/{mission['id']}/needs")).json()
    assert [i["status"] for i in items] == ["answered"]


async def test_restore_rewinds_the_branch_and_plan_and_the_mission_can_resume(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await completed(app, client, repo)
    async with app.state.sessionmaker() as session:
        checkpoints = list(
            await session.scalars(select(Checkpoint).order_by(Checkpoint.created_at))
        )
    first = checkpoints[0]
    assert first.label == "todo-model: Todo model"
    row, _, run = await load(app, mission["id"])
    worktree = Path(run.worktree_path or "")

    response = await client.post(
        f"/api/missions/{mission['id']}/checkpoints/{first.commit}/restore"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "paused"
    states = {f["id"]: f["status"] for m in body["milestones"] for f in m["features"]}
    assert states == {"todo-model": "done", "filter-helper": "pending"}
    assert [m["status"] for m in body["milestones"]] == ["completed", "pending"]
    assert git_output(worktree, "rev-parse", "HEAD").strip() == first.commit
    assert (worktree / "src" / "todos.js").exists()
    assert not (worktree / "src" / "filter.js").exists()
    async with app.state.sessionmaker() as session:
        handoffs = list(await session.scalars(select(HandoffRow)))
        remaining = list(await session.scalars(select(Checkpoint)))
    assert [h.data["feature_id"] for h in handoffs] == ["todo-model"]
    assert [c.commit for c in remaining] == [first.commit]
    document = json.loads((worktree / ".hex" / "mission" / "features.json").read_text())
    assert [f["status"] for m in document["milestones"] for f in m["features"]] == [
        "done",
        "pending",
    ]
    assert row.branch  # the mission branch itself moved back

    assert (await client.post(f"/api/missions/{mission['id']}/resume")).json()[
        "status"
    ] == "running"
    await finish(app)
    assert (await load(app, mission["id"]))[0].status == "completed"
    assert (worktree / "src" / "filter.js").exists()  # the rewound feature was rebuilt


async def test_restore_only_accepts_a_features_own_checkpoint(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await completed(app, client, repo)
    async with app.state.sessionmaker() as session:
        final = (await session.scalars(select(Checkpoint).order_by(Checkpoint.created_at))).all()[
            -1
        ]
    assert final.feature_id is None

    for commit in (final.commit, "0" * 40, uuid.uuid4().hex):
        response = await client.post(f"/api/missions/{mission['id']}/checkpoints/{commit}/restore")
        assert response.status_code == 404
    listed = (await client.get(f"/api/missions/{mission['id']}/checkpoints")).json()
    assert [c["label"] for c in listed] == [
        "todo-model: Todo model",
        "filter-helper: Filter helper",
        "Mission complete",
    ]
    assert (await load(app, mission["id"]))[0].status == "completed"  # nothing changed
