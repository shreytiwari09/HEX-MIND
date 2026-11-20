"""Experiments (PRD §15.3): run the mission benchmark under different conditions and compare.

A *trial* is one benchmark app built by one mission under one condition. It runs the real
pipeline (the same `MissionRunner` the app uses, in this process) in a fresh project; when the
mission ends, the hidden tests grade the worktree in the sandbox, and the trial is stored in
`eval_runs` with the numbers measured from the record (`llm_calls`, events, needs). Nothing in a
trial is estimated or claimed by an agent.

Runnable now: **E4** (blackboard vs messaging) and **E5** (prompt/skill variants against the
baseline). The others need something that does not exist yet and say so (`BLOCKED`); they are
listed in every report so a missing result is never mistaken for a null one.

Trials are resumable: a trial that already has a stored result is skipped, so a sweep that was
stopped by a rate limit continues where it left off.
"""

import asyncio
import copy
import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalRun, EvalTask, FeatureRow, Mission, Need, Project, Run
from app.evaluation import benchmarks, missions
from app.metrics import service as metrics
from app.missions import service
from app.missions.models import MissionPlan
from app.orchestration.services import Services

logger = logging.getLogger(__name__)

MAX_BUDGET_USD = Decimal("5")  # per trial, unless the sweep says otherwise
TRIAL_TIMEOUT_S = 3600


@dataclass(frozen=True)
class Condition:
    id: str
    label: str
    coordination: str = "blackboard"
    variant_id: str | None = None
    pattern: str = "mission"  # how the team is organised for the trial (see `apply_pattern`)


SINGLE_AGENT = "backend"  # the one persona that builds everything in the single-agent pattern
PATTERNS = ("single", "mission", "pipeline")


def apply_pattern(plan: dict[str, Any], pattern: str) -> dict[str, Any]:
    """The benchmark's fixed plan, organised for `pattern` (E1). The runner is the same in every
    case; only who builds what and what reviews it changes:

    - `single`: one agent builds every feature, nothing reviews it (the baseline).
    - `mission`: the plan as written (P-mission, the default).
    - `pipeline`: plan, build, then a code review at the end of every milestone.
    """
    if pattern not in PATTERNS:
        raise ValueError(f"unknown pattern {pattern!r}")
    organised = copy.deepcopy(plan)
    for milestone in organised["milestones"]:
        if pattern == "single":
            milestone["validators"] = []
            for feature in milestone["features"]:
                feature["persona"] = SINGLE_AGENT
        elif pattern == "pipeline":
            milestone["validators"] = ["code-reviewer"]
    return organised


@dataclass(frozen=True)
class Experiment:
    id: str
    title: str
    question: str
    varies: str
    conditions: tuple[Condition, ...] = ()
    blocked: str | None = None  # why it cannot run yet; None when it can
    note: str | None = None  # what the comparison does and does not cover


BLOCKED = {
    "E2": "needs parallel builders, which are not built; features are built one after another",
    "E3": (
        "needs model presets across providers and real keys for each; none has had a live run, "
        "and the cheap/top/mixed presets are not defined"
    ),
    "E6": (
        "needs the scikit-learn baseline, which is not a dependency of the project yet, and a "
        "labeled request set big enough to split"
    ),
}

E1 = Experiment(
    id="E1",
    title="Patterns",
    question="Does the mission team beat a single agent?",
    varies="team pattern",
    conditions=(
        Condition("single", "Single agent", pattern="single"),
        Condition("mission", "Mission team (default)", pattern="mission"),
        Condition("pipeline", "Pipeline: build then review", pattern="pipeline"),
    ),
    note=(
        "Three of the six patterns are built. Reflection, parallel and adaptive are not, so this "
        "does not answer the whole question. The benchmark plans use only the backend persona, so "
        "single agent and mission differ only in the review step the pipeline adds."
    ),
)

E4 = Experiment(
    id="E4",
    title="State sharing",
    question="Does the way agents share state (blackboard or messages) change the outcome?",
    varies="coordination backend",
    conditions=(
        Condition("blackboard", "Blackboard (default)", coordination="blackboard"),
        Condition("messaging", "Messaging only", coordination="messaging"),
    ),
)


def e5(variants: Sequence[str]) -> Experiment:
    """The baseline (no variant) against each named prompt/skill variant."""
    conditions = (Condition("baseline", "No variant"),) + tuple(
        Condition(f"variant:{v}", f"Variant {v}", variant_id=v) for v in variants
    )
    return Experiment(
        id="E5",
        title="Prompt and skill variance",
        question="How much do instructions and skills matter?",
        varies="prompt/skill variant",
        conditions=conditions,
        blocked=None if variants else "pass at least one variant id to compare with the baseline",
    )


def experiments(variants: Sequence[str] = ()) -> dict[str, Experiment]:
    found = {"E1": E1, "E4": E4, "E5": e5(variants)}
    for exp_id, reason in BLOCKED.items():
        found[exp_id] = Experiment(exp_id, _TITLES[exp_id], _QUESTIONS[exp_id], "", (), reason)
    return dict(sorted(found.items()))


_TITLES = {
    "E2": "Serial vs parallel",
    "E3": "Model delegation",
    "E6": "Router",
}
_QUESTIONS = {
    "E2": "Do parallel builders conflict?",
    "E3": "Does mixing models per role pay off?",
    "E6": "LLM Router vs scikit-learn baseline",
}


@dataclass(frozen=True)
class Trial:
    experiment: str
    condition: Condition
    app_id: str
    repeat: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.experiment, self.condition.id, self.app_id, self.repeat)


def plan_trials(experiment: Experiment, app_ids: Iterable[str], repeats: int) -> list[Trial]:
    """Every (condition, app, repeat), repeats innermost so a stopped sweep still has complete
    early repeats for every condition."""
    if experiment.blocked:
        raise ValueError(f"{experiment.id} cannot run: {experiment.blocked}")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    apps = list(app_ids)
    return [
        Trial(experiment.id, condition, app_id, repeat)
        for repeat in range(repeats)
        for app_id in apps
        for condition in experiment.conditions
    ]


# ---------- running ----------


def task_slug(app_id: str) -> str:
    return f"mission-{app_id}"


async def sync_tasks(session: AsyncSession) -> dict[str, EvalTask]:
    """The mission apps as `eval_tasks` rows (kind `mission`), by app id."""
    rows = {t.slug: t for t in await session.scalars(select(EvalTask))}
    found: dict[str, EvalTask] = {}
    for app in missions.load_apps():
        row = rows.get(task_slug(app.id)) or EvalTask(slug=task_slug(app.id))
        row.prompt = app.idea
        row.expected_complexity = "high"
        row.acceptance_tests = ["acceptance.test.js"]
        row.kind = "mission"
        session.add(row)
        found[app.id] = row
    await session.flush()
    return found


async def finished_keys(session: AsyncSession, experiment: str) -> set[tuple[str, str, str, int]]:
    """Trials that already have a stored result (an `error` result is not a result: it is run
    again)."""
    rows = await session.execute(
        select(EvalRun.condition, EvalTask.slug, EvalRun.repeat)
        .join(EvalTask, EvalTask.id == EvalRun.eval_task_id)
        .where(EvalRun.experiment == experiment, EvalRun.status != "error")
    )
    return {
        (experiment, condition or "", slug.removeprefix("mission-"), repeat)
        for condition, slug, repeat in rows
    }


async def run_trial(
    services: Services,
    trial: Trial,
    *,
    budget_usd: Decimal = MAX_BUDGET_USD,
    timeout_s: float = TRIAL_TIMEOUT_S,
) -> uuid.UUID:
    """Run one trial to the end and store its result. Returns the `eval_runs` id."""
    app = missions.get_app(trial.app_id)
    started = datetime.now(UTC)
    workspace = services.settings.data_dir / "experiments" / uuid.uuid4().hex
    mission_id: uuid.UUID | None = None
    error: str | None = None
    try:
        await run_in_threadpool(missions.prepare_workspace, workspace)
        async with services.sessionmaker.begin() as session:
            project = Project(
                name=f"{trial.experiment}-{app.id}", workspace_path=str(workspace), git_enabled=True
            )
            session.add(project)
            await session.flush()
            mission = await service.create_mission(
                session,
                services.settings,
                project,
                idea=app.idea,
                plan=MissionPlan.model_validate(apply_pattern(app.plan, trial.condition.pattern)),
                budget_usd=budget_usd,
                variant_id=trial.condition.variant_id,
                coordination=trial.condition.coordination,
            )
            mission_id = mission.id
            await service.set_status(
                session, mission.id, "running", only_from=("awaiting_approval",), reason="trial"
            )
        services.launch_mission(mission_id)
        try:
            await asyncio.wait_for(asyncio.shield(services.mission_tasks[mission_id]), timeout_s)
        except asyncio.CancelledError:  # the sweep was stopped: stop the mission with it
            await _abandon(services, mission_id, "the sweep was stopped")
            raise
        except TimeoutError:
            error = f"the mission did not finish within {int(timeout_s)} s"
            await _abandon(services, mission_id, error)
    except Exception as exc:  # recorded, not raised: one bad trial must not stop a sweep
        logger.exception("trial %s failed", trial.key)
        error = f"{type(exc).__name__}: {exc}"[:500]
    return await _record(services, trial, app, mission_id, workspace, started, error)


async def _abandon(services: Services, mission_id: uuid.UUID, reason: str) -> None:
    async with services.sessionmaker.begin() as session:
        await service.set_status(
            session, mission_id, "cancelled", only_from=service.OPEN_STATES, reason=reason
        )
    task = services.mission_tasks.get(mission_id)
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)
    await service.settle_cancelled(services, mission_id)


async def _record(
    services: Services,
    trial: Trial,
    app: missions.MissionApp,
    mission_id: uuid.UUID | None,
    workspace: Path,
    started: datetime,
    error: str | None,
) -> uuid.UUID:
    passed, tests = False, (None, None)
    worktree: Path | None = None
    measured: dict[str, Any] = {}
    status = "error"
    needs = retries = 0
    usage: service.Usage | None = None
    async with services.sessionmaker() as session:
        mission = await session.get(Mission, mission_id) if mission_id else None
        if mission is not None:
            status = mission.status
            needs = len(
                list(await session.scalars(select(Need.id).where(Need.mission_id == mission.id)))
            )
            attempts = await session.scalars(
                select(FeatureRow.attempts).where(FeatureRow.mission_id == mission.id)
            )
            retries = sum(max(a - 1, 0) for a in attempts)
            usage = await service.usage(session, mission.run_id)
            measured = await metrics.compute(session, metrics.Scope([mission.id], [mission.run_id]))
            run = await session.get(Run, mission.run_id)
            worktree = Path(run.worktree_path) if run and run.worktree_path else None
    if worktree is not None and worktree.exists():
        outcome = await run_in_threadpool(missions.grade, worktree, app)
        if outcome.exit_code is None:
            error = error or f"grading failed: {outcome.error}"
        else:
            passed = benchmarks.passed(outcome)
            tests = benchmarks.counts(outcome)
    elif error is None:
        error = "the mission has no worktree to grade"
    finished = datetime.now(UTC)
    calls = measured.get("calls", {})
    process = measured.get("process", {})
    models = [f"{m['provider']}/{m['model']}" for m in measured.get("by_model", [])]
    row = EvalRun(
        eval_task_id=uuid.UUID(int=0),  # set below, once the task row exists
        run_id=mission.run_id if mission_id and mission else None,
        provider=",".join(sorted({m.split("/")[0] for m in models})) or "none",
        completed=status == "completed",
        tests_passed=tests[0],
        tests_total=tests[1],
        latency_ms=int((finished - started).total_seconds() * 1000),
        cost_usd=usage.spent_usd if usage and not usage.unpriced_calls else None,
        retries=retries,
        fallback_count=int(process.get("fallbacks", 0)),
        experiment=trial.experiment,
        condition=trial.condition.id,
        repeat=trial.repeat,
        config={
            "coordination": trial.condition.coordination,
            "variant_id": trial.condition.variant_id,
            "pattern": trial.condition.pattern,
            "app": app.id,
            "models": models,
            "unpriced_calls": usage.unpriced_calls if usage else None,
            "calls": calls.get("count"),
        },
        benchmark_version=missions.BENCHMARK_VERSION,
        mission_id=mission_id,
        status=status,
        passed=passed,
        needs_you=needs,
        escalations=int(process.get("escalations", 0)),
        tokens_in=usage.tokens_in if usage else None,
        tokens_out=usage.tokens_out if usage else None,
        error=error,
    )
    async with services.sessionmaker.begin() as session:
        row.eval_task_id = (await sync_tasks(session))[app.id].id
        session.add(row)
        await session.flush()
        return row.id


# ---------- sweeps ----------


@dataclass
class Sweep:
    """One sweep that is running (or has run) in this process."""

    id: str
    experiment: str
    total: int
    skipped: int  # already had a stored result
    done: int = 0
    current: str | None = None
    state: str = "running"  # running | finished | stopped
    started_at: datetime | None = None
    task: "asyncio.Task[None] | None" = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experiment": self.experiment,
            "total": self.total,
            "skipped": self.skipped,
            "done": self.done,
            "current": self.current,
            "state": self.state,
        }


async def start_sweep(
    services: Services,
    experiment: Experiment,
    *,
    app_ids: Sequence[str],
    repeats: int,
    budget_usd: Decimal = MAX_BUDGET_USD,
    sweeps: dict[str, Sweep],
) -> Sweep:
    """Run every trial that has no stored result yet, one after another, in the background."""
    known = {a.id for a in missions.load_apps()}
    unknown = [a for a in app_ids if a not in known]
    if unknown:
        raise ValueError(f"unknown mission benchmark apps: {', '.join(unknown)}")
    trials = plan_trials(experiment, app_ids, repeats)
    async with services.sessionmaker() as session:
        have = await finished_keys(session, experiment.id)
    todo = [t for t in trials if t.key not in have]
    sweep = Sweep(
        id=uuid.uuid4().hex[:12],
        experiment=experiment.id,
        total=len(todo),
        skipped=len(trials) - len(todo),
        started_at=datetime.now(UTC),
    )
    sweeps[sweep.id] = sweep

    async def go() -> None:
        try:
            for trial in todo:
                sweep.current = f"{trial.condition.id} / {trial.app_id} / repeat {trial.repeat}"
                await run_trial(services, trial, budget_usd=budget_usd)
                sweep.done += 1
            sweep.state = "finished"
        except asyncio.CancelledError:
            sweep.state = "stopped"
            raise
        finally:
            sweep.current = None

    sweep.task = services.background.spawn(go(), name=f"sweep-{sweep.id}")
    return sweep
