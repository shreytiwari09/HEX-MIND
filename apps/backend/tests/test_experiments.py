"""Experiments (PRD §15): the trial list, resumable sweeps, honest statistics and one real trial.

The real trial runs a benchmark mission through the whole pipeline (scripted workers, real
Docker/git/MCP/A2A) and has the hidden tests grade the worktree. A worker that writes the
reference solution passes; one that writes nothing does not, whatever it reports: the grade comes
from the tests, not from the agent."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import EvalRun, EvalTask
from app.evaluation import experiments as exp
from app.evaluation import missions, results, safety
from app.missions.models import MissionPlan
from app.providers.base import Completion, LLMRequest, ToolCall
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import report

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
APP_ID = "todo-login"


# ---------- the experiments and their trials ----------


def test_only_the_experiments_that_can_run_are_runnable() -> None:
    catalog = exp.experiments(["terse"])
    assert [e.id for e in catalog.values() if not e.blocked] == ["E1", "E4", "E5"]
    for blocked in ("E2", "E3", "E6"):
        assert catalog[blocked].blocked and not catalog[blocked].conditions
    assert exp.experiments()["E5"].blocked  # nothing to compare the baseline with
    assert [c.id for c in catalog["E5"].conditions] == ["baseline", "variant:terse"]
    assert {c.coordination for c in catalog["E4"].conditions} == {"blackboard", "messaging"}


def test_trials_keep_the_repeats_innermost_and_refuse_a_blocked_experiment() -> None:
    trials = exp.plan_trials(exp.E4, ["a", "b"], repeats=2)

    assert len(trials) == 2 * 2 * 2
    assert {t.repeat for t in trials[:4]} == {0}  # every condition and app has repeat 0 first
    assert len({t.key for t in trials}) == len(trials)
    with pytest.raises(ValueError, match="cannot run"):
        exp.plan_trials(exp.experiments()["E2"], ["a"], 1)
    with pytest.raises(ValueError, match="at least 1"):
        exp.plan_trials(exp.E4, ["a"], 0)


def test_patterns_reorganise_the_plan_without_touching_the_original() -> None:
    plan = missions.get_app("notes-tags").plan
    original = repr(plan)

    single = exp.apply_pattern(plan, "single")
    pipeline = exp.apply_pattern(plan, "pipeline")
    same = exp.apply_pattern(plan, "mission")

    def personas(p: dict) -> set[str]:  # type: ignore[type-arg]
        return {f["persona"] for m in p["milestones"] for f in m["features"]}

    assert personas(single) == {exp.SINGLE_AGENT}
    assert all(m["validators"] == [] for m in single["milestones"])
    assert all(m["validators"] == ["code-reviewer"] for m in pipeline["milestones"])
    assert same == plan and same is not plan
    assert repr(plan) == original  # the benchmark's plan itself is never changed
    for organised in (single, pipeline):  # still a plan the app accepts
        MissionPlan.model_validate(organised)
    with pytest.raises(ValueError, match="unknown pattern"):
        exp.apply_pattern(plan, "swarm")


# ---------- honest numbers ----------


def make_task(slug: str) -> EvalTask:
    return EvalTask(id=uuid.uuid4(), slug=slug, prompt="x", expected_complexity="high")


def run_row(task: EvalTask, condition: str, repeat: int, *, passed: bool, **extra: Any) -> EvalRun:
    values: dict[str, Any] = {
        "provider": "groq",
        "completed": True,
        "experiment": "E4",
        "condition": condition,
        "repeat": repeat,
        "status": "completed",
        "passed": passed,
        "latency_ms": 60_000,
        "cost_usd": Decimal("0.5"),
        "tokens_in": 1000,
        "tokens_out": 500,
        "needs_you": 0,
        "retries": 0,
        "escalations": 0,
        "benchmark_version": missions.BENCHMARK_VERSION,
    }
    values.update(extra)
    return EvalRun(eval_task_id=task.id, **values)


def test_a_pass_rate_has_an_interval_and_few_trials_are_not_told_apart() -> None:
    low, high = results.wilson(3, 3) or (0, 0)
    assert 0.4 < low < 1 and high == 1.0  # three passes are far from proof of 100%
    assert results.wilson(0, 0) is None

    def summary(passed: int, n: int) -> results.Summary:
        s = results.Summary("c", trials=n, passed=passed)
        s.interval = results.wilson(passed, n)
        return s

    assert not results.distinguishable(summary(3, 3), summary(1, 3))
    assert results.distinguishable(summary(30, 30), summary(2, 30))
    assert not results.distinguishable(summary(0, 0), summary(30, 30))


def test_summaries_count_errors_and_leave_unknowns_unknown() -> None:
    task = make_task("mission-todo-login")
    other = make_task("mission-notes-tags")
    rows = [
        run_row(task, "messaging", 0, passed=True),
        run_row(task, "messaging", 1, passed=False, cost_usd=None),  # a model with no price
        run_row(other, "messaging", 0, passed=True),
        run_row(other, "messaging", 1, passed=True),
        run_row(task, "messaging", 2, passed=False, status="error", error="boom"),
    ]
    slugs = {task.id: task.slug, other.id: other.slug}

    s = results.summarize("messaging", rows, slugs)

    assert (s.trials, s.errors, s.passed) == (5, 1, 3)
    assert s.pass_rate == 0.75  # the errored trial is not a failure of the team, and not a pass
    assert s.by_app == {"notes-tags": (2, 2), "todo-login": (1, 2)}
    assert (s.k, s.pass_k) == (2, 0.5)  # only notes-tags passed in every repeat
    assert s.cost_trials == 3 and s.cost_usd_mean == 0.5  # the unpriced trial has no cost
    empty = results.summarize("none", [], slugs)
    assert empty.pass_rate is None and empty.cost_usd_mean is None and empty.pass_k is None


def test_the_report_says_what_did_not_run_and_never_calls_a_tie_a_win() -> None:
    task = make_task("mission-todo-login")
    rows = [
        run_row(task, c, r, passed=r == 0) for c in ("blackboard", "messaging") for r in range(3)
    ]
    slugs = {task.id: task.slug}
    data = {
        "experiment": "E4",
        "trials": 6,
        "benchmark_versions": [missions.BENCHMARK_VERSION],
        "conditions": [
            results.summarize(c, [r for r in rows if r.condition == c], slugs)
            for c in ("blackboard", "messaging")
        ],
        "errors": [],
    }

    text = results.render([data], exp.experiments(), date(2026, 11, 20))

    assert "2026-11-20" in text
    assert "cannot be told apart" in text and "not evidence that they are equal" in text
    for experiment_id in ("E1", "E2", "E3", "E4", "E5", "E6"):
        assert f"## {experiment_id} " in text
    assert text.count("**Not run:**") == 5  # E1, E2, E3, E6 and E5 without variants


# ---------- sweeps ----------


async def test_a_sweep_skips_stored_trials_and_runs_the_rest_in_order(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.state.services
    async with services.sessionmaker.begin() as session:
        tasks = await exp.sync_tasks(session)
        session.add(run_row(tasks[APP_ID], "blackboard", 0, passed=True))
        session.add(  # an error is not a result: it is run again
            run_row(tasks[APP_ID], "messaging", 0, passed=False, status="error", error="x")
        )
    ran: list[tuple[str, str, int]] = []

    async def fake(_: Any, trial: exp.Trial, **kwargs: Any) -> uuid.UUID:
        ran.append((trial.condition.id, trial.app_id, trial.repeat))
        return uuid.uuid4()

    monkeypatch.setattr(exp, "run_trial", fake)
    sweeps: dict[str, exp.Sweep] = {}

    sweep = await exp.start_sweep(
        services, exp.E4, app_ids=[APP_ID], repeats=2, sweeps=sweeps, budget_usd=Decimal(1)
    )
    assert sweep.task is not None
    await sweep.task

    assert (sweep.total, sweep.skipped, sweep.done, sweep.state) == (3, 1, 3, "finished")
    assert ran == [
        ("messaging", APP_ID, 0),
        ("blackboard", APP_ID, 1),
        ("messaging", APP_ID, 1),
    ]
    with pytest.raises(ValueError, match="unknown mission benchmark apps"):
        await exp.start_sweep(services, exp.E4, app_ids=["nope"], repeats=1, sweeps=sweeps)


async def test_the_experiments_api_lists_runs_and_reports(
    client: httpx.AsyncClient,
) -> None:
    listing = (await client.get("/api/experiments")).json()
    by_id = {e["id"]: e for e in listing["experiments"]}
    assert listing["benchmark_version"] == missions.BENCHMARK_VERSION
    assert {a["id"] for a in listing["apps"]} == {
        "todo-login",
        "notes-tags",
        "expense-tracker",
        "habit-tracker",
        "inventory",
    }
    assert by_id["E4"]["blocked"] is None and by_id["E2"]["blocked"]

    assert (await client.post("/api/experiments/E2/run", json={})).status_code == 409
    assert (await client.post("/api/experiments/E5/run", json={})).status_code == 409
    assert (await client.post("/api/experiments/E9/run", json={})).status_code == 404
    assert (
        await client.post("/api/experiments/E4/run", json={"apps": ["nope"]})
    ).status_code == 422
    assert (await client.post("/api/experiments/E4/run", json={"repeats": 0})).status_code == 422
    bad = await client.post("/api/experiments/E5/run", json={"variants": ["ghost"]})
    assert bad.status_code == 404

    text = (await client.get("/api/experiments/report")).json()["markdown"]
    assert "**Not run:** no trials have been run yet" in text
    assert (await client.get("/api/experiments/results")).json()["experiments"][0]["trials"] == 0


# ---------- one real trial ----------


class ReferenceWorkers:
    """Scripted workers that write the reference solution of a benchmark app, or nothing."""

    def __init__(self, bench: missions.MissionApp, *, writes: bool) -> None:
        self.writes = writes
        self.files: dict[str, list[tuple[str, str]]] = {}
        for milestone in bench.plan["milestones"]:
            for feature in milestone["features"]:
                folder = bench.directory / "reference" / feature["id"]
                self.files[feature["title"]] = [
                    (str(p.relative_to(folder)), p.read_text())
                    for p in sorted(folder.rglob("*"))
                    if p.is_file()
                ]
        self.steps: dict[tuple[str, int], int] = {}

    def __call__(self, request: LLMRequest) -> Completion:
        prompt = "\n".join(m.content or "" for m in request.messages)
        title = next(
            line[len("Feature: ") :].strip()
            for line in prompt.splitlines()
            if line.startswith("Feature: ")
        )
        calls = sum(1 for m in request.messages if m.role == "assistant")
        written = self.files[title] if self.writes else []
        if calls < len(written):
            path, content = written[calls]
            call = ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name="write_file",
                arguments={"path": path, "content": content},
            )
            return Completion(tool_calls=[call])
        return Completion(content=report(title))


async def one_trial(app: FastAPI, *, writes: bool, condition: exp.Condition) -> EvalRun:
    use_adapter(app, ScriptedAdapter(ReferenceWorkers(missions.get_app(APP_ID), writes=writes)))
    trial = exp.Trial("E4", condition, APP_ID, 0)
    run_id = await exp.run_trial(app.state.services, trial, budget_usd=Decimal(5), timeout_s=600)
    async with app.state.sessionmaker() as session:
        row = await session.get(EvalRun, run_id)
        assert row is not None
        return row


@needs_docker
@pytest.mark.parametrize("coordination", ["blackboard", "messaging"])
async def test_a_trial_is_graded_by_the_hidden_tests(app: FastAPI, coordination: str) -> None:
    condition = next(c for c in exp.E4.conditions if c.id == coordination)

    row = await one_trial(app, writes=True, condition=condition)

    assert (row.experiment, row.condition, row.repeat) == ("E4", coordination, 0)
    assert row.status == "completed" and row.completed and row.passed
    assert row.tests_passed and row.tests_passed == row.tests_total
    assert (
        row.config["coordination"] == coordination
        and row.benchmark_version == missions.BENCHMARK_VERSION
    )
    assert row.mission_id is not None and row.error is None
    assert row.tokens_in is not None and row.latency_ms and row.latency_ms > 0
    async with app.state.sessionmaker() as session:
        stored = await session.scalar(select(EvalTask).where(EvalTask.id == row.eval_task_id))
    assert stored is not None and stored.kind == "mission"


@needs_docker
async def test_a_team_that_reports_success_but_builds_nothing_does_not_pass(app: FastAPI) -> None:
    row = await one_trial(app, writes=False, condition=exp.E4.conditions[0])

    assert not row.passed  # the report said "done"; the hidden tests say otherwise
    assert row.tests_total and row.tests_passed != row.tests_total


# ---------- safety negatives ----------


@needs_docker
async def test_every_safety_attack_is_blocked(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/experiments/safety")).json()

    assert body["summary"]["got_through"] == 0 and body["summary"]["not_run"] == 0
    assert body["summary"]["blocked"] == body["summary"]["cases"] >= 15
    assert {c["category"] for c in body["cases"]} == {
        "path escape",
        "secret read",
        "mission board",
        "network",
        "plugin misuse",
    }


def test_an_attack_that_gets_through_is_reported_as_such() -> None:
    assert safety._refused(lambda: "read it")[0] is False  # nothing stopped it
    assert safety._refused(lambda: 1 / 0)[0] is False  # a crash is not a defense either
    blocked, why = safety._refused(lambda: (_ for _ in ()).throw(safety.ToolError("no")))
    assert blocked and why == "no"
