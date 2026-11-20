"""Metrics (PRD §14.1, §14.3): what a project's missions cost, how long they took and how the
process behaved, computed from stored data only (`llm_calls`, the event log, features, validator
reports). Nothing is estimated here beyond what the provider layer already recorded.

Where a figure cannot be measured it is `None`, never a guess: the false-positive rate of the
validators needs ground truth that does not exist, and edit-format compliance needs the edit-format
layer (deferred, D45).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentEvent,
    FeatureRow,
    LLMCall,
    Milestone,
    Mission,
    ValidatorReportRow,
)

PROCESS_EVENTS = {
    "provider_fallback": "fallbacks",
    "key_rotated": "key_rotations",
    "escalated": "escalations",
    "budget_warning": "budget_warnings",
    "guardrail_triggered": "guardrail_triggers",
    "need_raised": "needs_raised",
}


def _num(value: Any) -> float:
    return float(value) if value is not None else 0.0


@dataclass(frozen=True)
class Scope:
    mission_ids: list[uuid.UUID]
    run_ids: list[uuid.UUID]


async def scope_for(
    session: AsyncSession, *, project_id: uuid.UUID | None, mission_id: uuid.UUID | None
) -> Scope:
    query = select(Mission.id, Mission.run_id)
    if mission_id is not None:
        query = query.where(Mission.id == mission_id)
    elif project_id is not None:
        query = query.where(Mission.project_id == project_id)
    rows = (await session.execute(query)).all()
    return Scope([r.id for r in rows], [r.run_id for r in rows])


def _group(rows: Any, key_names: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append(
            {
                **{k: getattr(r, k) for k in key_names},
                "calls": r.calls,
                "failed": r.failed,
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0),
                "cost_usd": _num(r.cost),
                "avg_latency_ms": round(_num(r.latency)),
            }
        )
    return out


def _call_columns() -> list[Any]:
    return [
        func.count().label("calls"),
        func.count().filter(LLMCall.error.is_not(None)).label("failed"),
        func.sum(LLMCall.input_tokens).label("input_tokens"),
        func.sum(LLMCall.output_tokens).label("output_tokens"),
        func.sum(LLMCall.est_cost_usd).label("cost"),
        func.avg(LLMCall.latency_ms).label("latency"),
        func.count().filter(LLMCall.replayed.is_(True)).label("replayed"),
    ]


async def compute(session: AsyncSession, scope: Scope) -> dict[str, Any]:
    runs = scope.run_ids
    # ---- model calls
    total = (await session.execute(select(*_call_columns()).where(LLMCall.run_id.in_(runs)))).one()
    percentiles = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(LLMCall.latency_ms).cast(Float),
                func.percentile_cont(0.95).within_group(LLMCall.latency_ms).cast(Float),
            ).where(LLMCall.run_id.in_(runs), LLMCall.error.is_(None))
        )
    ).one()
    unpriced = await session.scalar(
        select(func.count()).where(
            LLMCall.run_id.in_(runs), LLMCall.error.is_(None), LLMCall.est_cost_usd.is_(None)
        )
    )
    by_persona = (
        await session.execute(
            select(LLMCall.persona_id.label("persona"), *_call_columns())
            .where(LLMCall.run_id.in_(runs))
            .group_by(LLMCall.persona_id)
            .order_by(func.sum(LLMCall.est_cost_usd).desc().nulls_last())
        )
    ).all()
    by_model = (
        await session.execute(
            select(
                LLMCall.provider.label("provider"), LLMCall.model.label("model"), *_call_columns()
            )
            .where(LLMCall.run_id.in_(runs))
            .group_by(LLMCall.provider, LLMCall.model)
            .order_by(func.sum(LLMCall.est_cost_usd).desc().nulls_last())
        )
    ).all()

    # ---- the missions themselves
    missions = list(await session.scalars(select(Mission).where(Mission.id.in_(scope.mission_ids))))
    statuses: dict[str, int] = {}
    for m in missions:
        statuses[m.status] = statuses.get(m.status, 0) + 1
    durations = [
        (m.finished_at - m.started_at).total_seconds()
        for m in missions
        if m.started_at and m.finished_at
    ]
    cost_by_run = dict(
        (
            await session.execute(
                select(LLMCall.run_id, func.sum(LLMCall.est_cost_usd))
                .where(LLMCall.run_id.in_(runs))
                .group_by(LLMCall.run_id)
            )
        ).all()
    )
    by_variant: dict[str | None, dict[str, Any]] = {}
    for m in missions:
        entry = by_variant.setdefault(
            m.variant_id,
            {"variant_id": m.variant_id, "missions": 0, "completed": 0, "cost_usd": 0.0},
        )
        entry["missions"] += 1
        entry["completed"] += m.status in ("completed", "applied", "kept")
        entry["cost_usd"] += _num(cost_by_run.get(m.run_id))

    # ---- features and retries
    features = list(
        await session.scalars(
            select(FeatureRow).where(FeatureRow.mission_id.in_(scope.mission_ids))
        )
    )
    feature_status: dict[str, int] = {}
    for f in features:
        feature_status[f.status] = feature_status.get(f.status, 0) + 1
    attempts = sum(f.attempts for f in features)
    retried = sum(1 for f in features if f.attempts > 1)

    # ---- process events
    event_counts = dict(
        (
            await session.execute(
                select(AgentEvent.type, func.count())
                .where(AgentEvent.run_id.in_(runs), AgentEvent.type.in_(list(PROCESS_EVENTS)))
                .group_by(AgentEvent.type)
            )
        ).all()
    )
    process = {name: int(event_counts.get(event, 0)) for event, name in PROCESS_EVENTS.items()}
    guardrails: dict[str, int] = {}
    for payload in await session.scalars(
        select(AgentEvent.payload).where(
            AgentEvent.run_id.in_(runs), AgentEvent.type == "guardrail_triggered"
        )
    ):
        name = str(payload.get("guardrail", "unknown"))
        guardrails[name] = guardrails.get(name, 0) + 1

    # ---- validators: how often they found something, and whether it was then fixed
    reports = (
        await session.execute(
            select(
                ValidatorReportRow.milestone_id,
                ValidatorReportRow.validator,
                ValidatorReportRow.round,
                ValidatorReportRow.verdict,
            )
            .where(ValidatorReportRow.mission_id.in_(scope.mission_ids))
            .order_by(ValidatorReportRow.milestone_id, ValidatorReportRow.round)
        )
    ).all()
    milestones = await session.scalar(
        select(func.count()).where(Milestone.mission_id.in_(scope.mission_ids))
    )
    first_round: dict[tuple[Any, str], str] = {}
    last_round: dict[tuple[Any, str], str] = {}
    for r in reports:
        first_round.setdefault((r.milestone_id, r.validator), r.verdict)
        last_round[(r.milestone_id, r.validator)] = r.verdict
    checked = len(first_round)
    caught = [k for k, v in first_round.items() if v == "fail"]
    fixed = [k for k in caught if last_round[k] == "pass"]
    validators = {
        "milestones": int(milestones or 0),
        "checks": checked,  # a validator's look at a milestone
        "caught": len(caught),  # found something blocking in the first round
        "caught_and_fixed": len(fixed),  # ...and passed after the builder reworked it
        "unavailable": sum(1 for v in first_round.values() if v == "needs_user"),
        "catch_rate": round(len(caught) / checked, 4) if checked else None,
        # Needs ground truth (was a finding really a problem?): not measurable from the record.
        "false_positive_rate": None,
    }

    return {
        "missions": {
            "count": len(missions),
            "by_status": statuses,
            "avg_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
        },
        "calls": {
            "count": total.calls,
            "failed": total.failed,
            "error_rate": round(total.failed / total.calls, 4) if total.calls else None,
            "input_tokens": int(total.input_tokens or 0),
            "output_tokens": int(total.output_tokens or 0),
            "cost_usd": _num(total.cost),
            "replayed": int(total.replayed or 0),  # answered from the response cache (D60)
            "without_cost": int(unpriced or 0),  # answered, but no price known (e.g. local models)
            "avg_latency_ms": round(_num(total.latency)),
            "p50_latency_ms": round(percentiles[0]) if percentiles[0] is not None else None,
            "p95_latency_ms": round(percentiles[1]) if percentiles[1] is not None else None,
        },
        "by_persona": _group(by_persona, ("persona",)),
        "by_model": _group(by_model, ("provider", "model")),
        "by_variant": sorted(
            by_variant.values(), key=lambda v: (v["variant_id"] is None, v["variant_id"] or "")
        ),
        "features": {
            "by_status": feature_status,
            "attempts": attempts,
            "retried": retried,
            "first_try_rate": (
                round(
                    sum(1 for f in features if f.status == "done" and f.attempts <= 1)
                    / len(features),
                    4,
                )
                if features
                else None
            ),
        },
        "process": {**process, "guardrails": guardrails},
        "validators": validators,
        "edit_format_compliance": None,  # the edit-format layer is deferred (D45)
    }
