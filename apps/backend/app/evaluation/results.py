"""Results of the experiments (PRD §15.4, §15.5), computed from `eval_runs` and nothing else.

The honesty rules are built into the numbers: every figure carries the number of trials it comes
from; a figure that could not be measured is `None` and printed as "n/a", never zero; trials that
errored are counted and listed rather than dropped; and two conditions are only called different
when their 95% intervals do not overlap, which with a few trials is rare, and the report says so.
"""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalRun, EvalTask
from app.evaluation import experiments as exp

Z95 = 1.96


def wilson(successes: int, n: int) -> tuple[float, float] | None:
    """95% Wilson score interval for a pass rate; None without trials."""
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + Z95**2 / n
    centre = (p + Z95**2 / (2 * n)) / denominator
    margin = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _sd(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


@dataclass
class Summary:
    condition: str
    trials: int = 0
    errors: int = 0  # trials that could not be run or graded
    completed: int = 0  # the mission itself finished
    passed: int = 0  # every hidden test passed
    pass_rate: float | None = None
    interval: tuple[float, float] | None = None
    # pass^k: the share of apps that passed in every one of their repeats (consistency).
    pass_k: float | None = None
    k: int | None = None
    needs_you_mean: float | None = None
    retries_mean: float | None = None
    escalations_mean: float | None = None
    duration_s_mean: float | None = None
    duration_s_sd: float | None = None
    cost_usd_mean: float | None = None
    cost_usd_sd: float | None = None
    cost_trials: int = 0  # trials with a known cost (a model without a price has none)
    tokens_in_mean: float | None = None
    tokens_out_mean: float | None = None
    tests_passed_mean: float | None = None
    by_app: dict[str, tuple[int, int]] = field(default_factory=dict)  # app -> (passed, trials)


def summarize(condition: str, rows: list[EvalRun], slug_of: dict[Any, str]) -> Summary:
    graded = [r for r in rows if r.status != "error"]
    out = Summary(condition=condition, trials=len(rows), errors=len(rows) - len(graded))
    out.completed = sum(1 for r in graded if r.completed)
    out.passed = sum(1 for r in graded if r.passed)
    if graded:
        out.pass_rate = out.passed / len(graded)
        out.interval = wilson(out.passed, len(graded))
    by_app: dict[str, list[EvalRun]] = defaultdict(list)
    for r in graded:
        by_app[slug_of[r.eval_task_id].removeprefix("mission-")].append(r)
    out.by_app = {a: (sum(r.passed for r in rs), len(rs)) for a, rs in sorted(by_app.items())}
    if by_app:
        out.k = min(len(rs) for rs in by_app.values())
        out.pass_k = sum(all(r.passed for r in rs) for rs in by_app.values()) / len(by_app)
    out.needs_you_mean = _mean([float(r.needs_you) for r in graded])
    out.retries_mean = _mean([float(r.retries) for r in graded])
    out.escalations_mean = _mean([float(r.escalations) for r in graded])
    seconds = [r.latency_ms / 1000 for r in graded if r.latency_ms is not None]
    out.duration_s_mean, out.duration_s_sd = _mean(seconds), _sd(seconds)
    costs = [float(r.cost_usd) for r in graded if r.cost_usd is not None]
    out.cost_usd_mean, out.cost_usd_sd, out.cost_trials = _mean(costs), _sd(costs), len(costs)
    out.tokens_in_mean = _mean([float(r.tokens_in) for r in graded if r.tokens_in is not None])
    out.tokens_out_mean = _mean([float(r.tokens_out) for r in graded if r.tokens_out is not None])
    tests = [float(r.tests_passed) for r in graded if r.tests_passed is not None]
    out.tests_passed_mean = _mean(tests)
    return out


def distinguishable(a: Summary, b: Summary) -> bool:
    """True only when the pass-rate intervals do not overlap."""
    if a.interval is None or b.interval is None:
        return False
    return a.interval[1] < b.interval[0] or b.interval[1] < a.interval[0]


async def collect(session: AsyncSession, experiment: str) -> dict[str, Any]:
    """Everything stored for one experiment: a summary per condition and the errored trials."""
    slugs = {t.id: t.slug for t in await session.scalars(select(EvalTask))}
    rows = list(
        await session.scalars(
            select(EvalRun)
            .where(EvalRun.experiment == experiment)
            .order_by(EvalRun.created_at, EvalRun.repeat)
        )
    )
    by_condition: dict[str, list[EvalRun]] = defaultdict(list)
    for r in rows:
        by_condition[r.condition or "?"].append(r)
    summaries = [summarize(c, rs, slugs) for c, rs in by_condition.items()]
    return {
        "experiment": experiment,
        "trials": len(rows),
        "benchmark_versions": sorted({r.benchmark_version or "?" for r in rows}),
        "conditions": summaries,
        "errors": [
            {
                "condition": r.condition,
                "app": slugs[r.eval_task_id].removeprefix("mission-"),
                "repeat": r.repeat,
                "error": r.error,
            }
            for r in rows
            if r.status == "error"
        ],
    }


# ---------- the report ----------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _spread(mean: float | None, sd: float | None, digits: int = 1) -> str:
    if mean is None:
        return "n/a"
    return f"{mean:.{digits}f}" if sd is None else f"{mean:.{digits}f} ± {sd:.{digits}f}"


def _interval(s: Summary) -> str:
    return "n/a" if s.interval is None else f"{s.interval[0] * 100:.0f}–{s.interval[1] * 100:.0f}%"


def render(
    collected: list[dict[str, Any]], experiments: dict[str, exp.Experiment], today: date
) -> str:
    """A dated markdown report of every experiment: what ran, what did not and why."""
    lines = [
        f"# H.E.X Mind experiment results, {today.isoformat()}",
        "",
        "Generated from the `eval_runs` table. Every number is measured: the hidden tests grade "
        "the worktree in the sandbox, and tokens, cost and time come from the stored record. "
        "`n/a` means it could not be measured, not zero. A difference is only called a "
        "difference when the 95% intervals of the pass rates do not overlap.",
        "",
    ]
    stored = {c["experiment"]: c for c in collected}
    for experiment in experiments.values():
        lines += [f"## {experiment.id} {experiment.title}", "", f"*{experiment.question}*", ""]
        data = stored.get(experiment.id)
        if data is None or not data["trials"]:
            reason = experiment.blocked or "no trials have been run yet"
            lines += [f"**Not run:** {reason}.", ""]
            continue
        if experiment.note:
            lines += [f"Note: {experiment.note}", ""]
        if experiment.blocked:
            lines += [f"Note: {experiment.blocked}. Only stored trials are shown.", ""]
        lines += _table(data)
        lines += _reading(data)
    return "\n".join(lines).rstrip() + "\n"


def _table(data: dict[str, Any]) -> list[str]:
    lines = [
        f"Benchmark version: {', '.join(data['benchmark_versions'])}. "
        f"{data['trials']} trials stored.",
        "",
        "| Condition | Trials | Errors | Mission completed | Hidden tests passed | "
        "Pass rate (95%) | pass^k | Needs you | Retries | Escalations | Time (s) | "
        "Cost (USD) | Tokens in / out |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in data["conditions"]:
        pass_k = "n/a" if s.pass_k is None else f"{_pct(s.pass_k)} (k={s.k})"
        cost = _spread(s.cost_usd_mean, s.cost_usd_sd, 3)
        if s.cost_trials != s.trials - s.errors:
            cost += f" (known for {s.cost_trials} of {s.trials - s.errors})"
        lines.append(
            f"| {s.condition} | {s.trials} | {s.errors} | {s.completed} | {s.passed} | "
            f"{_pct(s.pass_rate)} ({_interval(s)}) | {pass_k} | {_num(s.needs_you_mean)} | "
            f"{_num(s.retries_mean)} | {_num(s.escalations_mean)} | "
            f"{_spread(s.duration_s_mean, s.duration_s_sd, 0)} | {cost} | "
            f"{_num(s.tokens_in_mean, 0)} / {_num(s.tokens_out_mean, 0)} |"
        )
    lines.append("")
    return lines


def _reading(data: dict[str, Any]) -> list[str]:
    summaries: list[Summary] = data["conditions"]
    lines = ["Per app (hidden tests passed / trials):", ""]
    for s in summaries:
        cells = ", ".join(f"{a} {p}/{n}" for a, (p, n) in s.by_app.items()) or "no graded trials"
        lines.append(f"- {s.condition}: {cells}")
    lines.append("")
    if len(summaries) > 1:
        differing = [
            (a.condition, b.condition)
            for i, a in enumerate(summaries)
            for b in summaries[i + 1 :]
            if distinguishable(a, b)
        ]
        if differing:
            lines.append(
                "Pass rates that differ beyond their intervals: "
                + "; ".join(f"{a} vs {b}" for a, b in differing)
                + "."
            )
        else:
            lines.append(
                "The conditions cannot be told apart on pass rate at this number of trials. "
                "This is a null result for now, not evidence that they are equal."
            )
        lines.append("")
    if data["errors"]:
        lines += ["Trials that errored (not counted in the rates):", ""]
        lines += [
            f"- {e['condition']} / {e['app']} / repeat {e['repeat']}: {e['error']}"
            for e in data["errors"]
        ]
        lines.append("")
    return lines
