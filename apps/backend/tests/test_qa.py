"""QA: the validation contract, acceptance tests only QA can write, and the QA validator.
Missions run for real (see test_mission_runner); only the models are scripted."""

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select

from app.a2a.protocol import PersonaRequest
from app.db.models import Checkpoint, Milestone
from app.mcp_server.tools import ToolError, WorkspaceTools
from app.missions.folder import render_validation_contract
from app.missions.models import MissionPlan
from app.providers.base import Completion, LLMRequest, ToolCall
from app.sandbox.contract import RunContract
from app.sandbox.runner import docker_available
from app.workspace.paths import PathViolation, resolve_in_workspace
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import GOOD, PLAN, Script, approve, finish, load, needs, new_mission
from tests.test_persona_crew import REPORT, feature, run_persona, start
from tests.test_run_contract import repo_with
from tests.test_run_workflow import TODOS_JS, TODOS_TEST
from tests.test_validators import Validators, milestone_statuses, reports

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

CONTRACT = {
    "stack": "plain node",
    "image": "node:22-alpine",
    "test": 'node --test "src/**/*.test.js"',
    "acceptance": 'node --test "tests/acceptance/**/*.test.js"',
}
QA_TESTS = """const test = require('node:test')
const assert = require('node:assert/strict')
const { addTodo } = require('../../src/todos')

test('VC-1 addTodo trims titles and marks them open', () => {
  assert.deepEqual(addTodo([], ' milk '), [{ id: 1, title: 'milk', done: false }])
})
"""
QA_TESTS_DEMANDING = QA_TESTS.replace("done: false }]", "done: false, priority: 'normal' }]")
TITLE = "Acceptance tests: Model"
CRITERIA = [
    {"id": "VC-1", "text": "addTodo trims titles", "how": "unit test", "feature": "todo-model"},
    {"id": "VC-2", "text": "the page lists todos", "how": "browser", "feature": "todo-model"},
    {"id": "VC-3", "text": "no secrets in code", "how": "security review", "feature": "todo-model"},
]


def git_output(worktree: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(worktree), *args], capture_output=True, text=True, check=True
    ).stdout


def qa_plan(criteria: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    plan = json.loads(json.dumps(PLAN))
    plan["milestones"][0]["validators"] = ["qa"]
    plan["validation_contract"] = CRITERIA if criteria is None else criteria
    return plan


# ---------- the guard ----------


def test_acceptance_tests_are_read_only_for_agents_and_qa_writes_nothing_else(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests" / "acceptance").mkdir(parents=True)

    # Builders (and everyone else) can read them but not edit them.
    assert resolve_in_workspace(tmp_path, "tests/acceptance/a.test.js", agent=True)
    for path in (
        "tests/acceptance/a.test.js",
        "tests/acceptance/deep/b.test.js",
        "Tests/Acceptance/c.js",
    ):
        with pytest.raises(PathViolation, match="only QA writes"):
            resolve_in_workspace(tmp_path, path, for_write=True, agent=True)
    assert resolve_in_workspace(tmp_path, "tests/unit/a.test.js", for_write=True, agent=True)
    # QA's writes are confined to that folder.
    only = ("tests/acceptance",)
    assert resolve_in_workspace(
        tmp_path, "tests/acceptance/a.test.js", for_write=True, agent=True, agent_write_only=only
    )
    for path in ("src/app.js", "tests/acceptance-evil/a.js", "tests/other.js", "package.json"):
        with pytest.raises(PathViolation, match="outside the folders you may write"):
            resolve_in_workspace(tmp_path, path, for_write=True, agent=True, agent_write_only=only)
    # Not an agent (the editor): unaffected.
    assert resolve_in_workspace(tmp_path, "tests/acceptance/a.test.js", for_write=True)


def test_tools_enforce_it(tmp_path: Path) -> None:
    workspace, worktree = tmp_path / "workspace", tmp_path / "worktree"
    workspace.mkdir()
    worktree.mkdir()
    kwargs: dict[str, Any] = {
        "workspace": workspace,
        "allowed_images": ["node:22-alpine"],
        "check_timeout_s": 5,
    }
    builder = WorkspaceTools(worktree, **kwargs)
    qa = WorkspaceTools(worktree, write_only=("tests/acceptance",), **kwargs)

    with pytest.raises(ToolError, match="only QA writes"):
        builder.write_file("tests/acceptance/a.test.js", "x")
    assert qa.write_file("tests/acceptance/a.test.js", "x").startswith("created")
    with pytest.raises(ToolError, match="outside the folders"):
        qa.write_file("src/app.js", "x")
    with pytest.raises(ToolError, match="only QA writes"):
        builder.replace_in_file("tests/acceptance/a.test.js", "x", "y")  # cannot weaken them
    assert builder.read_file("tests/acceptance/a.test.js") == "x"


def test_the_run_contract_can_name_an_acceptance_check() -> None:
    contract = RunContract(stack="x", acceptance="node --test tests/acceptance")

    assert contract.checks() == {"acceptance": "node --test tests/acceptance"}
    with pytest.raises(ValidationError):
        RunContract(stack="x", acceptance="a\nb")


# ---------- the validation contract ----------


def test_a_plan_carries_a_valid_validation_contract_and_it_renders_as_markdown() -> None:
    plan = MissionPlan.model_validate(qa_plan())

    assert [c.id for c in plan.validation_contract] == ["VC-1", "VC-2", "VC-3"]
    markdown = render_validation_contract([c.model_dump() for c in plan.validation_contract])
    assert markdown.startswith("# Validation contract\n\n## todo-model\n")
    assert "- VC-1: addTodo trims titles   [unit test]" in markdown
    assert "- VC-2: the page lists todos   [browser]" in markdown
    assert MissionPlan.model_validate(json.loads(json.dumps(PLAN))).validation_contract == []


@pytest.mark.parametrize(
    ("criteria", "message"),
    [
        ([{"id": "VC-1", "text": "a b c", "how": "unit test"}] * 2, "criterion ids must be unique"),
        (
            [{"id": "VC-1", "text": "a b c", "how": "unit test", "feature": "ghost"}],
            "no feature 'ghost'",
        ),
        ([{"id": "spec-1", "text": "a b c", "how": "unit test"}], "string_pattern_mismatch"),
        ([{"id": "VC-1", "text": "a b c", "how": "vibes"}], "Input should be"),
        ([{"id": "VC-1", "text": "x", "how": "unit test"}], "at least 3"),
    ],
)
def test_a_bad_validation_contract_is_rejected(
    criteria: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        MissionPlan.model_validate(qa_plan(criteria))


async def test_creating_a_mission_stores_and_writes_the_contract(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await new_mission(client, repo, qa_plan())

    assert [c["id"] for c in mission["validation_contract"]] == ["VC-1", "VC-2", "VC-3"]
    _, _, run = await load(app, mission["id"])
    text = (
        Path(run.worktree_path or "") / ".hex" / "mission" / "validation-contract.md"
    ).read_text()
    assert "VC-1: addTodo trims titles   [unit test]" in text
    plain = await new_mission(client, repo, json.loads(json.dumps(PLAN)))
    assert plain["validation_contract"] == []
    _, _, plain_run = await load(app, plain["id"])
    assert not (
        Path(plain_run.worktree_path or "") / ".hex/mission/validation-contract.md"
    ).exists()


# ---------- QA through a real crew call ----------


async def test_qa_writes_acceptance_tests_through_a_crew_call_and_nothing_else(
    app: FastAPI, workspace: Path
) -> None:
    results: list[str] = []

    def handler(request: LLMRequest) -> Completion:
        tool_results = [m.content or "" for m in request.messages if m.role == "tool"]
        if len(tool_results) == 0:
            args = {"path": "tests/acceptance/todo.test.js", "content": QA_TESTS}
        elif len(tool_results) == 1:
            args = {"path": "src/app.js", "content": "// QA tries to edit the code"}
        else:
            results.extend(tool_results)
            return Completion(content=json.dumps(REPORT))
        call = ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name="write_file", arguments=args)
        return Completion(tool_calls=[call])

    use_adapter(app, ScriptedAdapter(handler))
    run_id, worktree = await start(app, workspace)
    request = PersonaRequest(
        exchange_id=uuid.uuid4(),
        run_id=run_id,
        agent_id="qa_acceptance_01",
        worktree=str(worktree),
        workspace=str(workspace),
        persona_id="qa",
        feature=feature("qa", id="acceptance-m1-model", title=TITLE),
        mode="acceptance",
    )
    from app.a2a.client import call_crew
    from app.telemetry.hub import TelemetryHub

    services = app.state.services
    await call_crew(
        "persona",
        hub=TelemetryHub(services, run_id),
        http=services.a2a_http,
        settings=services.settings,
        prompt="acceptance",
        request=request,
        parent="mission_runner",
    )

    assert (worktree / "tests" / "acceptance" / "todo.test.js").read_text() == QA_TESTS
    assert "created tests/acceptance/todo.test.js" in results[0]
    assert "outside the folders you may write" in results[1]
    assert not (worktree / "src" / "app.js").exists()  # QA could not touch the code
    # In normal feature mode QA stays read-only, and a builder cannot touch the folder.
    for persona, path in (
        ("qa", "tests/acceptance/x.test.js"),
        ("backend", "tests/acceptance/x.test.js"),
    ):
        results.clear()

        def deny(request: LLMRequest, path: str = path) -> Completion:
            seen = [m.content or "" for m in request.messages if m.role == "tool"]
            if not seen:
                return Completion(
                    tool_calls=[
                        ToolCall(
                            id="c1", name="write_file", arguments={"path": path, "content": "x"}
                        )
                    ]
                )
            results.extend(seen)
            return Completion(content=json.dumps(REPORT))

        use_adapter(app, ScriptedAdapter(deny))
        await run_persona(app, run_id, worktree, workspace, persona, feature(persona))
        assert not (worktree / path).exists()


# ---------- missions ----------


def qa_script(
    tests: str, extra: dict[tuple[str, int], list[tuple[str, str]]] | None = None
) -> Script:
    files: dict[tuple[str, int], list[tuple[str, str]]] = {
        (TITLE, 0): [("tests/acceptance/todo.test.js", tests)],
        ("Todo model", 0): GOOD["Todo model"],
        ("Filter helper", 0): GOOD["Filter helper"],
    }
    files.update(extra or {})
    return Script(files)


@needs_docker
async def test_qa_writes_tests_first_then_the_validator_runs_them_and_names_what_it_skipped(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = repo_with(tmp_path, CONTRACT)
    script = qa_script(QA_TESTS)
    use_adapter(app, ScriptedAdapter(Validators(script)))
    mission = await new_mission(client, root, qa_plan())

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    assert await milestone_statuses(app) == {"m1-model": "passed", "m2-filter": "completed"}
    # QA's commit comes before the builder's: the tests were written first, from the contract.
    log = git_output(Path(run.worktree_path or ""), "log", "--format=%s", row.branch).splitlines()
    assert log.index("Acceptance tests: m1-model") > log.index("todo-model: Todo model")
    assert "Feature: Acceptance tests: Model" in script.prompts[TITLE][0]
    assert "VC-1: addTodo trims titles  [unit test]" in script.prompts[TITLE][0]
    assert "VC-2:" not in script.prompts[TITLE][0]  # browser and review criteria are not QA's tests
    async with app.state.sessionmaker() as session:
        ready = (await session.scalars(select(Milestone).where(Milestone.key == "m1-model"))).one()
        labels = [
            c.label
            for c in await session.scalars(select(Checkpoint).order_by(Checkpoint.created_at))
        ]
    assert ready.acceptance_ready is True and "Acceptance tests: Model" in labels
    [report] = [r for r in await reports(app, mission["id"]) if r.validator == "qa"]
    assert report.verdict == "pass"
    assert [(c["command"], c["exit_code"]) for c in report.data["commands"]] == [
        (CONTRACT["acceptance"], 0)
    ]
    notes = [f["message"] for f in report.data["findings"]]
    assert notes == ["Not checked (browser testing is not available in this build): VC-2"]
    # QA's file is in the project the builder worked in, read-only to it.
    assert (Path(run.worktree_path or "") / "tests/acceptance/todo.test.js").read_text() == QA_TESTS


@needs_docker
async def test_qa_catches_a_deliberate_bug_names_the_criterion_and_the_builder_fixes_it(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = repo_with(tmp_path, CONTRACT)
    fixed = TODOS_JS.replace("done: false", "done: false, priority: 'normal'")
    script = qa_script(
        QA_TESTS_DEMANDING,
        {
            ("Todo model", 1): [
                ("src/todos.js", fixed),
                (
                    "src/todos.test.js",
                    TODOS_TEST.replace("done: false }", "done: false, priority: 'normal' }"),
                ),
            ]
        },
    )
    use_adapter(app, ScriptedAdapter(Validators(script)))
    mission = await new_mission(client, root, qa_plan())

    await approve(client, mission)
    await finish(app)

    row, _, _ = await load(app, mission["id"])
    assert row.status == "completed"
    first, second = [r for r in await reports(app, mission["id"]) if r.validator == "qa"]
    assert (first.round, first.verdict, second.round, second.verdict) == (1, "fail", 2, "pass")
    finding = first.data["findings"][0]
    assert finding["severity"] == "critical" and finding["contract_ref"] == "VC-1"
    assert "VC-1" in finding["message"] and "priority" in finding["evidence"]
    # The builder was told which criterion failed, with the test output as evidence.
    rework = script.prompts["Todo model"][-1]
    assert "[qa, critical] The acceptance check failed for VC-1." in rework
    assert "priority" in rework


@needs_docker
async def test_without_acceptance_tests_qa_checks_nothing_and_never_passes(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    # A test runner the app does not recognise: it cannot work out an acceptance command itself
    # (for Node's own runner it would, see test_run_contract), so QA has nothing to run.
    root = repo_with(tmp_path, {**CONTRACT, "test": "sh -c 'node --test'", "acceptance": None})
    use_adapter(app, ScriptedAdapter(Validators(qa_script(QA_TESTS))))
    mission = await new_mission(client, root, qa_plan())

    await approve(client, mission)
    await finish(app)

    row, _, _ = await load(app, mission["id"])
    assert row.status == "needs_user"
    assert (await milestone_statuses(app))["m1-model"] == "completed"  # never "passed"
    [report] = [r for r in await reports(app, mission["id"]) if r.validator == "qa"]
    assert report.verdict == "needs_user" and report.data["commands"] == []
    assert "defines no `acceptance` check" in report.data["findings"][0]["message"]
    [need] = await needs(app, mission["id"])
    assert need.kind == "validator_unavailable"


@needs_docker
async def test_a_milestone_that_needs_qa_but_has_nothing_testable_is_not_passed_silently(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Validators(Script())))
    mission = await new_mission(client, repo, qa_plan([]))  # QA is required, no criteria at all

    await approve(client, mission)
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "needs_user"
    [report] = [r for r in await reports(app, mission["id"]) if r.validator == "qa"]
    assert report.verdict == "needs_user"
    assert "has not written acceptance tests" in report.data["findings"][0]["message"]
