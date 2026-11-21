"""The run contract (`.hex/project.json`): validation, how it takes priority, who may write it,
and the runner running its checks."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import CheckResult, HandoffRow
from app.events.log import list_events
from app.mcp_server.tools import ToolError, WorkspaceTools
from app.providers.base import Completion, LLMRequest, ToolCall
from app.sandbox.contract import (
    CONTRACT_PATH,
    ContractError,
    RunContract,
    load_contract,
)
from app.sandbox.profile import ProfileError, load_profile
from app.sandbox.runner import docker_available
from app.workspace import git
from app.workspace.paths import PathViolation, resolve_in_workspace
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import (
    FAILING_TEST,
    GOOD,
    PLAN,
    Script,
    approve,
    finish,
    load,
    needs,
    new_mission,
)
from tests.test_persona_crew import REPORT, feature, run_persona, start
from tests.test_run_workflow import FILTER_JS, FILTER_TEST, TODOS_JS, TODOS_TEST

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
IMAGES = ["node:22-alpine", "python:3.11-slim"]

# Fails when the source still contains a marker: tests can pass while this does not.
TYPECHECK = (
    "node -e \"process.exit(require('fs').readFileSync('src/todos.js','utf8')"
    ".includes('TODO_FIXME')?1:0)\""
)
CONTRACT: dict[str, Any] = {
    "stack": "plain node",
    "image": "node:22-alpine",
    "install": "true",
    "test": "node --test",
    "typecheck": TYPECHECK,
    "lint": "true",
    "start": "node src/todos.js",
    "port": 3000,
    "healthcheck": "/",
}


def write_contract(root: Path, contract: dict[str, Any] | str) -> None:
    path = root / CONTRACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contract if isinstance(contract, str) else json.dumps(contract))


def test_a_valid_contract_exposes_the_checks_it_defines(tmp_path: Path) -> None:
    write_contract(tmp_path, CONTRACT)

    contract = load_contract(tmp_path)

    assert contract is not None and contract.stack == "plain node" and contract.port == 3000
    assert list(contract.checks()) == ["install", "test", "typecheck", "lint"]
    assert contract.checks()["test"] == "node --test"
    assert contract.network.test == "none" and contract.network.install == "allowlist"
    assert RunContract(stack="x").checks() == {}  # a bare contract defines nothing


def test_no_contract_is_not_an_error_but_an_invalid_one_says_what_is_wrong(tmp_path: Path) -> None:
    assert load_contract(tmp_path) is None
    for bad, message in [
        ("{not json", "not valid JSON"),
        ('{"stack": ""}', "stack"),
        ('{"stack": "x", "test": "a\\nb"}', "one non-empty line"),
        ('{"stack": "x", "test": "' + "x" * 600 + '"}', "at most 500"),
        ('{"stack": "x", "port": 70000}', "port"),
        ('{"stack": "x", "dockerfile": "evil/Dockerfile"}', ".hex/Dockerfile"),
        ('{"stack": "x", "network": {"test": "allowlist"}}', "network.test"),
    ]:
        write_contract(tmp_path, bad)
        with pytest.raises(ContractError, match=message):
            load_contract(tmp_path)
    write_contract(tmp_path, '{"stack": "x", "pad": "' + "x" * 25_000 + '"}')
    with pytest.raises(ContractError, match="larger than"):
        load_contract(tmp_path)


def test_a_symlinked_contract_is_ignored(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(CONTRACT))
    (tmp_path / ".hex").mkdir()
    try:
        (tmp_path / CONTRACT_PATH).symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")

    assert load_contract(tmp_path) is None  # never read through a link


def test_the_contract_beats_the_user_profile_which_beats_detection(tmp_path: Path) -> None:
    workspace, worktree = tmp_path / "workspace", tmp_path / "worktree"
    for root in (workspace, worktree):
        root.mkdir()
    (worktree / "package.json").write_text('{"scripts": {"test": "node --test"}}')

    detected = load_profile(workspace, worktree, IMAGES)
    assert detected.source == "detected" and set(detected.checks) == {"test"}

    (workspace / ".hexmind").mkdir()
    (workspace / ".hexmind" / "profile.yaml").write_text(
        "image: python:3.11-slim\nchecks:\n  test: pytest -q\n"
    )
    assert load_profile(workspace, worktree, IMAGES).source == ".hexmind/profile.yaml"

    write_contract(worktree, CONTRACT)
    profile = load_profile(workspace, worktree, IMAGES)
    assert profile.source == ".hex/project.json" and profile.image == "node:22-alpine"
    assert set(profile.checks) == {"install", "test", "typecheck", "lint"}

    write_contract(worktree, {**CONTRACT, "image": "evil/image:latest"})
    with pytest.raises(ProfileError, match="not allowed"):
        load_profile(workspace, worktree, IMAGES)
    write_contract(worktree, "{broken")
    with pytest.raises(ContractError):  # a ValueError, so tools report it to the agent
        load_profile(workspace, worktree, IMAGES)


NODE_ACCEPTANCE = "node --test 'tests/acceptance/**/*.test.{js,mjs,cjs}'"


def _with_acceptance_tests(tmp_path: Path, contract: dict[str, Any], package: str | None = None):
    workspace, worktree = tmp_path / "workspace", tmp_path / "worktree"
    workspace.mkdir()
    (worktree / "tests" / "acceptance").mkdir(parents=True)
    (worktree / "tests" / "acceptance" / "VC-1.test.js").write_text("// QA's test\n")
    if package is not None:
        (worktree / "package.json").write_text(package)
    write_contract(worktree, contract)
    return load_profile(workspace, worktree, IMAGES).checks


@pytest.mark.parametrize(
    ("test_command", "package"),
    [
        ("node --test", None),
        ("npm test", '{"scripts": {"test": "node --test"}}'),
        ("npm run test", '{"scripts": {"test": "node --test --test-reporter=spec"}}'),
    ],
)
def test_node_projects_with_acceptance_tests_but_no_acceptance_check_get_one(
    tmp_path: Path, test_command: str, package: str | None
) -> None:
    checks = _with_acceptance_tests(tmp_path, {**CONTRACT, "test": test_command}, package)

    assert checks["acceptance"] == NODE_ACCEPTANCE


@pytest.mark.parametrize(
    ("contract", "package"),
    [
        # Another test runner: Node's would not understand its tests, so nothing is guessed.
        ({**CONTRACT, "test": "npx vitest run"}, None),
        ({**CONTRACT, "test": "npm test"}, '{"scripts": {"test": "vitest run"}}'),
        ({**CONTRACT, "test": "npm test"}, "{not json"),
        ({k: v for k, v in CONTRACT.items() if k != "test"}, None),
    ],
)
def test_no_acceptance_check_is_guessed_for_other_runners(
    tmp_path: Path, contract: dict[str, Any], package: str | None
) -> None:
    assert "acceptance" not in _with_acceptance_tests(tmp_path, contract, package)


def test_a_contracts_own_acceptance_check_is_kept(tmp_path: Path) -> None:
    checks = _with_acceptance_tests(tmp_path, {**CONTRACT, "acceptance": "npm run accept"})

    assert checks["acceptance"] == "npm run accept"


def test_agents_can_read_hex_files_but_only_write_the_paths_they_are_given(tmp_path: Path) -> None:
    (tmp_path / ".hex" / "mission").mkdir(parents=True)

    for path in (".hex/project.json", ".hex/mission/features.json", ".hex/mission/handoffs.jsonl"):
        resolve_in_workspace(tmp_path, path, agent=True)  # reading is fine
        with pytest.raises(PathViolation, match="read-only for agents"):
            resolve_in_workspace(tmp_path, path, for_write=True, agent=True)
    allowed = frozenset({".hex/project.json", ".hex/Dockerfile"})
    assert resolve_in_workspace(
        tmp_path, ".hex/project.json", for_write=True, agent=True, agent_writable=allowed
    )
    with pytest.raises(PathViolation):  # an exact path, not the folder
        resolve_in_workspace(
            tmp_path,
            ".hex/mission/features.json",
            for_write=True,
            agent=True,
            agent_writable=allowed,
        )
    with pytest.raises(PathViolation):
        resolve_in_workspace(tmp_path, ".HEX/project.json", for_write=True, agent=True)
    # Not an agent (the editor, H.E.X's own code): unaffected.
    assert resolve_in_workspace(tmp_path, ".hex/project.json", for_write=True)
    assert resolve_in_workspace(tmp_path, "src/app.js", for_write=True, agent=True)


def test_tools_apply_the_guard_and_list_the_checks(tmp_path: Path) -> None:
    workspace, worktree = tmp_path / "workspace", tmp_path / "worktree"
    workspace.mkdir()
    worktree.mkdir()
    write_contract(worktree, CONTRACT)
    builder = WorkspaceTools(
        worktree, workspace=workspace, allowed_images=IMAGES, check_timeout_s=5
    )
    devops = WorkspaceTools(
        worktree,
        workspace=workspace,
        allowed_images=IMAGES,
        check_timeout_s=5,
        writable_extra=frozenset({".hex/project.json", ".hex/Dockerfile"}),
    )

    with pytest.raises(ToolError, match="read-only for agents"):
        builder.write_file(".hex/project.json", "{}")
    with pytest.raises(ToolError, match="read-only for agents"):
        builder.replace_in_file(".hex/project.json", "plain node", "weaker")
    assert builder.read_file(".hex/project.json").startswith("{")
    assert devops.write_file(".hex/Dockerfile", "FROM node:22-alpine\n").startswith("created")
    assert "updated" in devops.write_file(
        ".hex/project.json", json.dumps({**CONTRACT, "stack": "n"})
    )
    with pytest.raises(ToolError, match="read-only for agents"):
        devops.write_file(".hex/mission/features.json", "{}")

    checks = builder.list_checks()
    assert "test: node --test" in checks and "(defined by .hex/project.json)" in checks
    empty = WorkspaceTools(
        tmp_path / "empty", workspace=workspace, allowed_images=IMAGES, check_timeout_s=5
    )
    (tmp_path / "empty").mkdir()
    assert "test: node --test" in empty.list_checks()  # detected for an empty project
    write_contract(worktree, "{broken")
    with pytest.raises(ToolError, match="invalid"):
        builder.list_checks()


async def test_only_the_devops_persona_can_write_the_run_contract_through_a_real_crew_call(
    app: FastAPI, workspace: Path
) -> None:
    results: dict[str, list[str]] = {"backend": [], "devops": []}

    def handler(request: LLMRequest) -> Completion:
        tool_results = [m.content or "" for m in request.messages if m.role == "tool"]
        persona = "devops" if "DevOps" in request.messages[0].content else "backend"  # type: ignore[operator]
        if not tool_results:
            call = ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name="write_file",
                arguments={"path": ".hex/project.json", "content": json.dumps(CONTRACT)},
            )
            return Completion(tool_calls=[call])
        results[persona].append(tool_results[0])
        return Completion(content=json.dumps(REPORT))

    use_adapter(app, ScriptedAdapter(handler))
    run_id, worktree = await start(app, workspace)

    await run_persona(app, run_id, worktree, workspace, "devops", feature("devops"))
    assert json.loads((worktree / CONTRACT_PATH).read_text())["stack"] == "plain node"
    (worktree / CONTRACT_PATH).unlink()
    await run_persona(app, run_id, worktree, workspace, "backend", feature("backend"))

    assert results["devops"][0].startswith("created .hex/project.json")
    assert "read-only for agents" in results["backend"][0]
    assert not (worktree / CONTRACT_PATH).exists()  # the backend persona wrote nothing


# ---------- the runner ----------


def repo_with(tmp_path: Path, contract: dict[str, Any] | str | None) -> Path:
    root = tmp_path / "todo-app"
    root.mkdir()
    (root / "README.md").write_bytes(b"# Todo app\n")
    if contract is not None:
        write_contract(root, contract)
    git.init_repo(root)
    return root


@needs_docker
async def test_the_runner_runs_the_contracts_typecheck_and_tests_and_records_both(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = repo_with(tmp_path, CONTRACT)
    bad_todos = TODOS_JS + "// TODO_FIXME remove\n"  # tests pass, the typecheck does not
    script = Script(
        {
            ("Todo model", 0): [("src/todos.js", bad_todos), ("src/todos.test.js", TODOS_TEST)],
            ("Todo model", 1): [("src/todos.js", TODOS_JS)],
            ("Filter helper", 0): [
                ("src/filter.js", FILTER_JS),
                ("src/filter.test.js", FILTER_TEST),
            ],
        }
    )
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, root)

    await approve(client, mission)
    await finish(app)

    row, features, run = await load(app, mission["id"])
    assert row.status == "completed"
    assert (features["todo-model"].attempts, features["filter-helper"].attempts) == (2, 1)
    assert "`typecheck` check is failing" in script.prompts["Todo model"][1]
    async with app.state.sessionmaker() as session:
        events = await list_events(session, run.id)
        results = list(await session.scalars(select(CheckResult).order_by(CheckResult.created_at)))
        handoffs = list(await session.scalars(select(HandoffRow).order_by(HandoffRow.created_at)))
    # The install ran once, before attempt 1 (the dependency files never changed afterwards);
    # attempt 1 stopped at the failing typecheck; attempts 2 and 3 ran typecheck then tests.
    assert [(r.name, r.exit_code == 0) for r in results] == [
        ("install", True),
        ("typecheck", False),
        ("typecheck", True),
        ("test", True),
        ("typecheck", True),
        ("test", True),
    ]
    assert [e.payload["name"] for e in events if e.type == "check_started"] == [
        r.name for r in results
    ]
    commands = [c["command"] for c in handoffs[0].data["commands"]]
    assert commands == [CONTRACT["typecheck"], "node --test"]  # what the sandbox really ran
    # Everything since the last checkpoint, including the test file from the rejected attempt.
    assert handoffs[0].data["files_changed"] == ["src/todos.js", "src/todos.test.js"]


@needs_docker
async def test_a_contract_with_no_test_check_cannot_pass_a_feature(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = repo_with(tmp_path, {"stack": "x", "image": "node:22-alpine", "typecheck": "true"})
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, root)

    await approve(client, mission)
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "needs_user" and features["todo-model"].status == "failed"
    [need] = await needs(app, mission["id"])
    assert "defines no `test` check" in need.evidence["last_findings"]


@needs_docker
async def test_an_invalid_contract_fails_the_mission_with_a_clear_reason(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = repo_with(tmp_path, '{"stack": "x", "test": "a\\nb"}')
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, root)

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "failed"
    async with app.state.sessionmaker() as session:
        failed = [e for e in await list_events(session, run.id) if e.type == "run_failed"]
    assert ".hex/project.json is invalid" in failed[0].payload["error"]
    assert PLAN and GOOD and FAILING_TEST  # (shared fixtures, kept importable)
