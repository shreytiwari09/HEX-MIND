"""The workspace tools added in P5 step 6: delete and move, read-only git, and the mission
tools. Pure functions over one worktree, like test_mcp.py; plus the per-persona tool lists."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.agents.persona import builtin_personas
from app.agents.tools import CODER, READ_ONLY, SPECS
from app.mcp_server.tools import ToolError, WorkspaceTools
from app.workspace import git

FEATURES = {
    "mission_id": "m",
    "milestones": [
        {
            "id": "m1-model",
            "title": "Model",
            "status": "active",
            "validators": [],
            "features": [
                {"id": "todo-model", "title": "Todo model", "persona": "backend", "status": "done"},
                {"id": "todo-api", "title": "Todo API", "persona": "backend", "status": "pending"},
            ],
        },
        {
            "id": "m2-ui",
            "title": "UI",
            "status": "pending",
            "validators": [],
            "features": [
                {
                    "id": "todo-page",
                    "title": "Todo page",
                    "persona": "frontend",
                    "status": "pending",
                }
            ],
        },
    ],
}
HANDOFF = {
    "feature_id": "todo-model",
    "persona_id": "backend",
    "implemented": ["addTodo"],
    "left_undone": [],
    "issues_found": [],
    "notes_for_next": ["addTodo returns a new list"],
    "files_changed": ["src/todos.js"],
    "model_used": "x:y",
    "cost_usd": 0.01,
}


def run(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "wt"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.js").write_text("one\n")
    (root / "src" / "b.js").write_text("two\n")
    git.init_repo(root)
    return root


def make(root: Path, tmp_path: Path, **extra: Any) -> WorkspaceTools:
    return WorkspaceTools(
        root, workspace=tmp_path / "ws", allowed_images=["node:22-alpine"], check_timeout_s=60,
        **extra,
    )  # fmt: skip


@pytest.fixture
def tools(worktree: Path, tmp_path: Path) -> WorkspaceTools:
    return make(worktree, tmp_path)


def mission_files(root: Path, handoffs: list[dict[str, Any]] | None = None) -> None:
    folder = root / ".hex" / "mission"
    folder.mkdir(parents=True)
    (folder / "features.json").write_text(json.dumps(FEATURES))
    (folder / "validation-contract.md").write_text(
        "# Validation contract\n\n## todo-model\n\n- VC-1: addTodo trims titles   [unit test]\n\n"
        "## todo-api\n\n- VC-2: POST /todos creates one   [api test]\n"
    )
    if handoffs is not None:
        (folder / "handoffs.jsonl").write_text("\n".join(json.dumps(h) for h in handoffs) + "\n")


# ---------- delete and move ----------


def test_delete_removes_one_file_and_nothing_else(tools: WorkspaceTools, worktree: Path) -> None:
    assert tools.delete_file("src/b.js") == "deleted src/b.js"
    assert not (worktree / "src" / "b.js").exists() and (worktree / "src" / "a.js").exists()
    with pytest.raises(ToolError, match="does not exist"):
        tools.delete_file("src/b.js")
    with pytest.raises(ToolError, match="not a regular file"):
        tools.delete_file("src")


def test_move_renames_creates_folders_and_never_overwrites(
    tools: WorkspaceTools, worktree: Path
) -> None:
    assert tools.move_file("src/a.js", "lib/deep/a.js") == "moved src/a.js to lib/deep/a.js"
    assert (worktree / "lib/deep/a.js").read_text() == "one\n" and not (
        worktree / "src/a.js"
    ).exists()
    with pytest.raises(ToolError, match="already exists"):
        tools.move_file("src/b.js", "lib/deep/a.js")
    with pytest.raises(ToolError, match="not an existing regular file"):
        tools.move_file("src/missing.js", "src/c.js")
    assert (worktree / "lib/deep/a.js").read_text() == "one\n"  # not overwritten


def test_delete_and_move_obey_the_path_guard(
    tools: WorkspaceTools, worktree: Path, tmp_path: Path
) -> None:
    (worktree / ".hex").mkdir()
    (worktree / ".hex" / "project.json").write_text("{}")
    (worktree / ".env").write_text("SECRET=1\n")
    (tmp_path / "outside.txt").write_text("x")
    for path in (".hex/project.json", ".env", "../outside.txt", ".git/config", "node_modules/x.js"):
        with pytest.raises(ToolError):
            tools.delete_file(path)
        with pytest.raises(ToolError):
            tools.move_file("src/a.js", path)
    with pytest.raises(ToolError):
        tools.move_file(".env", "src/env.txt")  # cannot even read the secret by moving it
    assert (worktree / ".env").read_text() == "SECRET=1\n" and (tmp_path / "outside.txt").exists()
    assert (worktree / "src/a.js").exists()


def test_acceptance_tests_cannot_be_deleted_or_moved_by_builders(
    worktree: Path, tmp_path: Path
) -> None:
    (worktree / "tests" / "acceptance").mkdir(parents=True)
    (worktree / "tests" / "acceptance" / "a.test.js").write_text("x")
    builder = make(worktree, tmp_path)
    qa = make(worktree, tmp_path, write_only=("tests/acceptance",))

    with pytest.raises(ToolError, match="only QA writes"):
        builder.delete_file("tests/acceptance/a.test.js")
    with pytest.raises(ToolError, match="only QA writes"):
        builder.move_file("tests/acceptance/a.test.js", "src/a.test.js")
    with pytest.raises(ToolError, match="outside the folders"):
        qa.delete_file("src/a.js")  # QA deletes only inside its folder
    assert qa.delete_file("tests/acceptance/a.test.js").startswith("deleted")


# ---------- git (read-only) ----------


def test_git_status_diff_and_log_show_the_features_own_changes(
    tools: WorkspaceTools, worktree: Path
) -> None:
    assert tools.git_status().startswith("(clean")
    assert "no changes" in tools.git_diff()
    (worktree / "src" / "a.js").write_text("one\nchanged\n")
    (worktree / "src" / "new.js").write_text("n\n")
    (worktree / "node_modules" / "dep").mkdir(parents=True)
    (worktree / "node_modules" / "dep" / "i.js").write_text("d\n")
    (worktree / ".hex" / "mission").mkdir(parents=True)
    (worktree / ".hex" / "mission" / "features.json").write_text("{}")

    status = tools.git_status().splitlines()
    assert sorted(status) == [" M src/a.js", "?? src/new.js"]  # no .hex, no node_modules
    diff = tools.git_diff()
    assert "+changed" in diff and "src/b.js" not in diff and ".hex" not in diff
    assert "+changed" in tools.git_diff("src/a.js")
    assert "no changes" in tools.git_diff("src/b.js")
    with pytest.raises(ToolError):
        tools.git_diff("../outside")
    run(worktree, "add", "-A")
    run(worktree, "commit", "-q", "-m", "Second commit")
    log = tools.git_log(2).splitlines()
    assert [line.split(" ", 1)[1] for line in log] == [
        "Second commit",
        "Initial commit (H.E.X Mind)",
    ]
    assert all("t@t" not in line and "@" not in line for line in log)  # no authors
    with pytest.raises(ToolError, match="between 1 and 50"):
        tools.git_log(0)
    with pytest.raises(ToolError, match="between 1 and 50"):
        tools.git_log(51)


def test_git_tools_change_nothing(tools: WorkspaceTools, worktree: Path) -> None:
    (worktree / "src" / "a.js").write_text("edited\n")
    before = run(worktree, "status", "--porcelain=v2", "--branch")
    index_before = (worktree / ".git" / "index").read_bytes()
    tools.git_status(), tools.git_diff(), tools.git_log()
    assert run(worktree, "status", "--porcelain=v2", "--branch") == before
    assert (worktree / ".git" / "index").read_bytes() == index_before
    assert (worktree / "src" / "a.js").read_text() == "edited\n"


def test_git_tools_say_so_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    for call in (lambda t: t.git_status(), lambda t: t.git_diff(), lambda t: t.git_log()):
        with pytest.raises(ToolError, match="git is not available"):
            call(make(plain, tmp_path))


# ---------- the mission ----------


def test_list_features_reads_the_mission_folder(tools: WorkspaceTools, worktree: Path) -> None:
    with pytest.raises(ToolError, match="not a mission worktree"):
        tools.list_features()
    mission_files(worktree)

    assert tools.list_features().splitlines() == [
        "todo-model | m1-model | backend | done | Todo model",
        "todo-api | m1-model | backend | pending | Todo API",
        "todo-page | m2-ui | frontend | pending | Todo page",
    ]


def test_feature_context_has_the_spec_the_criteria_and_only_earlier_handoffs(
    tools: WorkspaceTools, worktree: Path
) -> None:
    later = {**HANDOFF, "feature_id": "todo-page", "notes_for_next": ["not yet"]}
    mission_files(worktree, [HANDOFF, later])

    context = json.loads(tools.get_feature_context("todo-api"))

    assert context["feature"]["id"] == "todo-api" and context["feature"]["milestone"] == "m1-model"
    assert context["criteria"] == ["VC-2: POST /todos creates one   [api test]"]
    [earlier] = context["earlier_handoffs"]
    assert earlier["feature_id"] == "todo-model" and earlier["notes_for_next"] == [
        "addTodo returns a new list"
    ]
    assert "model_used" not in earlier and "cost_usd" not in earlier  # no usage in an agent's view
    first = json.loads(tools.get_feature_context("todo-model"))
    assert first["earlier_handoffs"] == [] and len(first["criteria"]) == 1


def test_feature_context_defaults_to_the_feature_in_progress(
    tools: WorkspaceTools, worktree: Path
) -> None:
    mission_files(worktree)
    with pytest.raises(ToolError, match="no feature is in progress"):
        tools.get_feature_context()
    document = json.loads((worktree / ".hex/mission/features.json").read_text())
    document["milestones"][0]["features"][1]["status"] = "in_progress"
    (worktree / ".hex/mission/features.json").write_text(json.dumps(document))

    assert json.loads(tools.get_feature_context())["feature"]["id"] == "todo-api"
    with pytest.raises(ToolError, match="no feature 'ghost'.*todo-model, todo-api, todo-page"):
        tools.get_feature_context("ghost")


# ---------- who gets which tools ----------


def test_every_tool_an_agent_can_have_is_specified_and_validators_cannot_change_files() -> None:
    assert set(READ_ONLY) <= set(CODER) <= set(SPECS)
    for writer in ("write_file", "replace_in_file", "delete_file", "move_file", "run_check"):
        assert writer not in READ_ONLY and writer in CODER
    assert {"git_status", "git_diff", "git_log", "list_features", "get_feature_context"} <= set(
        READ_ONLY
    )
    from app.agents.build import tool_names_for

    for persona in builtin_personas().values():
        names = tool_names_for(persona)
        assert names == (CODER if persona.kind == "worker" else READ_ONLY)
        if persona.kind != "worker":
            assert not {"write_file", "replace_in_file", "delete_file", "move_file"} & set(names)
