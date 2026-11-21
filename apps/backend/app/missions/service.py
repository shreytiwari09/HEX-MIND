"""Mission creation and persistence (PRD §8, §9, §12.5).

A mission is created from a hand-written plan (D24). Creating one takes a snapshot of the user's
workspace, creates the mission branch and an isolated git worktree, stores the plan in Postgres
and renders the mission folder in the worktree. The user's files are never touched.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    AgentEvent,
    Checkpoint,
    FeatureRow,
    HandoffRow,
    LLMCall,
    Milestone,
    Mission,
    Need,
    PersonaBudget,
    Project,
    Run,
)
from app.events.log import EventType, append_event
from app.missions import chat_updates, folder
from app.missions.models import Handoff, MissionPlan
from app.workspace import git

if TYPE_CHECKING:
    from app.orchestration.services import Services

# Feature fields kept in `features.spec` (the rest have their own columns).
SPEC_KEYS = (
    "description",
    "preconditions",
    "expected_behavior",
    "contract_refs",
    "extra_skills",
    "target_files",
)


class NotAGitRepo(RuntimeError):
    """Missions need git: the worktree keeps changes isolated and revertible."""


def worktree_path(settings: Settings, run_id: uuid.UUID) -> Path:
    return settings.data_dir / "worktrees" / str(run_id)


async def create_mission(
    session: AsyncSession,
    settings: Settings,
    project: Project,
    *,
    idea: str,
    plan: MissionPlan,
    budget_usd: Decimal | None = None,
    run: Run | None = None,
    prd: str | None = None,
    variant_id: str | None = None,
    coordination: str = "blackboard",
) -> Mission:
    """A mission awaiting approval, in a new worktree on its own branch. `run` is the scoping
    chat's run when the plan came from the PM, so the mission's trail starts at the idea; `prd`
    is the PM's plain-language PRD, written to `.hex/mission/prd.md`."""
    root = Path(project.workspace_path)
    if not await run_in_threadpool(git.is_repo, root):
        raise NotAGitRepo(project.workspace_path)

    mission_id = uuid.uuid4()
    branch = f"hex/mission-{mission_id.hex[:12]}"
    new_run = run is None
    if run is None:
        run = Run(project_id=project.id, title=plan.title, status="queued")
        session.add(run)
        await session.flush()
    else:
        run.title, run.status = plan.title, "queued"
    worktree = worktree_path(settings, run.id)
    base = await run_in_threadpool(git.snapshot, root)
    await run_in_threadpool(git.create_worktree, root, base, worktree, branch)
    try:
        run.base_commit = base
        run.worktree_path = str(worktree)
        mission = Mission(
            id=mission_id,
            project_id=project.id,
            run_id=run.id,
            title=plan.title,
            idea=idea,
            branch=branch,
            budget_usd=budget_usd,
            validation_contract=[c.model_dump() for c in plan.validation_contract],
            variant_id=variant_id,
            coordination=coordination,
        )
        session.add(mission)
        await session.flush()
        position = 0
        for milestone_position, milestone_plan in enumerate(plan.milestones):
            milestone = Milestone(
                mission_id=mission.id,
                key=milestone_plan.id,
                title=milestone_plan.title,
                position=milestone_position,
                validators=milestone_plan.validators,
            )
            session.add(milestone)
            await session.flush()
            for feature in milestone_plan.features:
                session.add(
                    FeatureRow(
                        mission_id=mission.id,
                        milestone_id=milestone.id,
                        key=feature.id,
                        title=feature.title,
                        persona_id=feature.persona,
                        position=position,
                        spec=feature.model_dump(include=set(SPEC_KEYS)),
                    )
                )
                position += 1
        await session.flush()
        if new_run:  # a scoping run already has its run_created event
            await append_event(
                session, run.id, EventType.RUN_CREATED, payload={"title": plan.title}
            )
        await _mission_status_event(session, run.id, mission.status, None, "plan received")
        await sync_mission_folder(session, mission, worktree)
        if plan.validation_contract:
            await run_in_threadpool(
                folder.write_validation_contract, worktree, mission.validation_contract
            )
        if prd:
            await run_in_threadpool(folder.write_prd, worktree, prd)
    except BaseException:
        await run_in_threadpool(git.remove_worktree, root, worktree)
        await run_in_threadpool(git.delete_branch, root, branch)
        raise
    return mission


async def features_document(session: AsyncSession, mission: Mission) -> dict[str, Any]:
    """`features.json` content (PRD §9.3), rendered from the database."""
    milestones = list(
        await session.scalars(
            select(Milestone).where(Milestone.mission_id == mission.id).order_by(Milestone.position)
        )
    )
    features = list(
        await session.scalars(
            select(FeatureRow)
            .where(FeatureRow.mission_id == mission.id)
            .order_by(FeatureRow.position)
        )
    )
    rendered = []
    for milestone in milestones:
        rendered.append(
            {
                "id": milestone.key,
                "title": milestone.title,
                "status": milestone.status,
                "validators": milestone.validators,
                "features": [
                    {
                        "id": f.key,
                        "title": f.title,
                        "persona": f.persona_id,
                        "status": f.status,
                        **{k: f.spec.get(k, [] if k != "description" else "") for k in SPEC_KEYS},
                        "attempts": f.attempts,
                        "commit": f.commit,
                    }
                    for f in features
                    if f.milestone_id == milestone.id
                ],
            }
        )
    return folder.render_features_json(str(mission.id), rendered)


async def sync_mission_folder(session: AsyncSession, mission: Mission, worktree: Path) -> None:
    document = await features_document(session, mission)
    await run_in_threadpool(folder.write_features_json, worktree, document)


async def record_handoff(
    session: AsyncSession,
    mission: Mission,
    feature: FeatureRow,
    handoff: Handoff,
    worktree: Path,
) -> HandoffRow:
    """Store a handoff in both places (PRD §9.1): the database row and the `handoffs.jsonl` line."""
    if (handoff.feature_id, handoff.persona_id) != (feature.key, feature.persona_id):
        raise ValueError("the handoff is for a different feature or persona")
    row = HandoffRow(
        mission_id=mission.id,
        feature_id=feature.id,
        persona_id=handoff.persona_id,
        attempt=feature.attempts,
        data=handoff.model_dump(mode="json"),
    )
    session.add(row)
    await session.flush()
    await run_in_threadpool(folder.append_handoff, worktree, handoff)
    await append_event(
        session,
        mission.run_id,
        EventType.HANDOFF_RECORDED,
        payload={
            "feature_id": feature.key,
            "persona": handoff.persona_id,
            "model_used": handoff.model_used,
            "files_changed": handoff.files_changed,
            "tokens_in": handoff.tokens_in,
            "tokens_out": handoff.tokens_out,
            "cost_usd": handoff.cost_usd,
        },
    )
    return row


# ---------- lifecycle and Needs you (PRD §8.1, §8.6, §8.7) ----------


class InvalidTransition(RuntimeError):
    pass


NEED_ACTIONS: dict[str, tuple[str, ...]] = {
    "feature_failed": ("retry", "skip", "stop"),
    "provider_unavailable": ("retry", "stop"),
    "budget_reached": ("raise_budget", "stop"),
    "persona_budget_reached": ("raise_budget", "skip", "stop"),
    # retry: validate again; accept: go on without a pass (recorded as "accepted").
    "milestone_failed": ("retry", "accept", "stop"),
    "validator_unavailable": ("retry", "accept", "stop"),
}
WARN_AT = Decimal("0.8")  # PRD §8.6: a warning at 80% of a budget
OPEN_STATES = ("awaiting_approval", "running", "paused", "needs_user")


async def set_status(
    session: AsyncSession,
    mission_id: uuid.UUID,
    to: str,
    *,
    only_from: tuple[str, ...],
    reason: str | None = None,
) -> bool:
    """Move a mission to `to` only if it is currently in one of `only_from`, and record the
    change. The runner and the API both use this, so a pause or stop is never overwritten by a
    runner that is finishing."""
    current = (
        await session.execute(
            select(Mission.status, Mission.run_id).where(Mission.id == mission_id).with_for_update()
        )
    ).first()
    if current is None or current.status not in only_from:
        return False
    values: dict[str, Any] = {"status": to}
    if to in ("completed", "cancelled", "failed"):
        values["finished_at"] = func.clock_timestamp()
    await session.execute(update(Mission).where(Mission.id == mission_id).values(**values))
    await _mission_status_event(session, current.run_id, to, current.status, reason)
    return True


async def change_status(
    session: AsyncSession, mission: Mission, to: str, *, reason: str | None = None
) -> None:
    """Set a mission's status directly (the caller already holds it locked) and record it."""
    previous, mission.status = mission.status, to
    await _mission_status_event(session, mission.run_id, to, previous, reason)


async def _mission_status_event(
    session: AsyncSession, run_id: uuid.UUID, to: str, previous: str | None, reason: str | None
) -> None:
    await append_event(
        session,
        run_id,
        EventType.MISSION_STATUS_CHANGED,
        payload={"status": to, "previous": previous, "reason": reason},
    )
    if to != previous:
        await chat_updates.mission_status(session, run_id, to, reason)


async def set_feature(
    session: AsyncSession, mission: Mission, row: FeatureRow, status: str
) -> None:
    """Set a feature's status and record it, with its attempts and checkpoint as they are now."""
    row.status = status
    await append_event(
        session,
        mission.run_id,
        EventType.FEATURE_STATUS_CHANGED,
        payload={
            "feature_id": row.key,
            "title": row.title,
            "persona": row.persona_id,
            "status": status,
            "attempts": row.attempts,
            "commit": row.commit,
        },
    )
    text = chat_updates.feature_text(row.title, row.persona_id, status, row.attempts)
    if text is not None:
        await chat_updates.post(session, mission, text, {"feature_id": row.key, "status": status})


async def set_milestone(
    session: AsyncSession, mission: Mission, milestone: Milestone, status: str
) -> None:
    if milestone.status == status:
        return
    milestone.status = status
    await append_event(
        session,
        mission.run_id,
        EventType.MILESTONE_STATUS_CHANGED,
        payload={"milestone_id": milestone.key, "title": milestone.title, "status": status},
    )


async def add_checkpoint(
    session: AsyncSession,
    mission: Mission,
    *,
    commit: str,
    label: str,
    feature: FeatureRow | None = None,
) -> Checkpoint:
    checkpoint = Checkpoint(
        mission_id=mission.id,
        feature_id=feature.id if feature else None,
        commit=commit,
        label=label,
    )
    session.add(checkpoint)
    await session.flush()
    await append_event(
        session,
        mission.run_id,
        EventType.CHECKPOINT_CREATED,
        payload={"commit": commit, "label": label, "feature_id": feature.key if feature else None},
    )
    return checkpoint


async def create_need(
    session: AsyncSession,
    mission: Mission,
    *,
    kind: str,
    summary: str,
    feature: FeatureRow | None = None,
    evidence: dict[str, Any] | None = None,
) -> Need:
    need = Need(
        mission_id=mission.id,
        feature_id=feature.id if feature else None,
        kind=kind,
        summary=summary,
        evidence=evidence or {},
        options=list(NEED_ACTIONS[kind]),
    )
    session.add(need)
    await session.flush()
    await append_event(
        session,
        mission.run_id,
        EventType.NEED_RAISED,
        payload={
            "need_id": str(need.id),
            "kind": kind,
            "summary": summary,
            "options": list(NEED_ACTIONS[kind]),
            "feature_id": feature.key if feature else None,
        },
    )
    await chat_updates.post(
        session, mission, chat_updates.need_text(summary, list(NEED_ACTIONS[kind])), {"need": kind}
    )
    return need


async def spent_usd(session: AsyncSession, run_id: uuid.UUID) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(LLMCall.est_cost_usd), 0)).where(LLMCall.run_id == run_id)
    )
    return Decimal(total or 0)


@dataclass(frozen=True)
class Usage:
    spent_usd: Decimal
    tokens_in: int
    tokens_out: int
    calls: int
    unpriced_calls: int  # successful calls whose model has no known price


async def usage(session: AsyncSession, run_id: uuid.UUID) -> Usage:
    """Real totals from the provider layer's `llm_calls` for a mission's run."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LLMCall.est_cost_usd), 0),
                func.coalesce(func.sum(LLMCall.input_tokens), 0),
                func.coalesce(func.sum(LLMCall.output_tokens), 0),
                func.count(),
                func.count().filter(LLMCall.error.is_(None), LLMCall.est_cost_usd.is_(None)),
            ).where(LLMCall.run_id == run_id)
        )
    ).one()
    return Usage(Decimal(row[0] or 0), int(row[1]), int(row[2]), int(row[3]), int(row[4]))


async def persona_spent(session: AsyncSession, run_id: uuid.UUID, persona_id: str) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(LLMCall.est_cost_usd), 0)).where(
            LLMCall.run_id == run_id, LLMCall.persona_id == persona_id
        )
    )
    return Decimal(total or 0)


async def persona_budget(session: AsyncSession, persona_id: str) -> Decimal | None:
    return await session.scalar(
        select(PersonaBudget.budget_usd).where(PersonaBudget.persona_id == persona_id)
    )


async def warn_if_near(
    session: AsyncSession, mission: Mission, scope: str, spent: Decimal, budget: Decimal
) -> None:
    """One `budget_warning` per scope when spending first reaches 80% of the budget."""
    if budget <= 0 or spent < budget * WARN_AT:
        return
    already = await session.scalar(
        select(func.count())
        .select_from(AgentEvent)
        .where(
            AgentEvent.run_id == mission.run_id,
            AgentEvent.type == EventType.BUDGET_WARNING.value,
            AgentEvent.payload["scope"].astext == scope,
        )
    )
    if already:
        return
    await append_event(
        session,
        mission.run_id,
        EventType.BUDGET_WARNING,
        payload={
            "scope": scope,
            "spent_usd": float(spent),
            "budget_usd": float(budget),
            "percent": int(spent / budget * 100),
        },
    )


async def settle_cancelled(services: "Services", mission_id: uuid.UUID) -> None:
    """Close the mission's run after a stop (idempotent)."""
    async with services.sessionmaker.begin() as session:
        mission = await session.get(Mission, mission_id)
        run = await session.get(Run, mission.run_id) if mission else None
        if mission is None or run is None or mission.status != "cancelled":
            return
        if run.status == "cancelled":
            return
        previous, run.status, run.finished_at = run.status, "cancelled", func.clock_timestamp()
        await append_event(
            session,
            run.id,
            EventType.RUN_STATUS_CHANGED,
            payload={"status": "cancelled", "previous": previous, "stub": False},
        )
        await append_event(
            session, run.id, EventType.RUN_CANCELLED, payload={"reason": "stopped by the user"}
        )


async def answer_need(
    session: AsyncSession,
    need: Need,
    *,
    action: str,
    budget_usd: Decimal | None = None,
) -> str:
    """Apply the user's answer; returns the mission status afterwards. The caller restarts the
    runner when the mission is `running`."""
    if need.status != "open":
        raise InvalidTransition("this item was already answered")
    if action not in NEED_ACTIONS[need.kind]:
        raise InvalidTransition(f"{action!r} is not an option for {need.kind}")
    mission = await session.get(Mission, need.mission_id)
    assert mission is not None
    feature = await session.get(FeatureRow, need.feature_id) if need.feature_id else None

    if action == "stop":
        target = "cancelled"
    else:
        target = "running"
        if need.kind in ("milestone_failed", "validator_unavailable"):
            milestone = await session.scalar(
                select(Milestone).where(
                    Milestone.mission_id == mission.id,
                    Milestone.key == str(need.evidence.get("milestone_id", "")),
                )
            )
            if milestone is not None:
                await set_milestone(
                    session, mission, milestone, "completed" if action == "retry" else "accepted"
                )
        elif action == "retry" and feature is not None and need.kind == "feature_failed":
            feature.attempts = 0
            await set_feature(session, mission, feature, "pending")
        elif action == "skip" and feature is not None:
            await set_feature(session, mission, feature, "skipped")
        elif action == "raise_budget" and need.kind == "persona_budget_reached":
            persona_id = str(need.evidence.get("persona_id", ""))
            spent = await persona_spent(session, mission.run_id, persona_id)
            if budget_usd is None or budget_usd <= spent:
                raise InvalidTransition(
                    f"the new budget must be above the {spent} USD {persona_id} has spent"
                )
            await session.merge(PersonaBudget(persona_id=persona_id, budget_usd=budget_usd))
        elif action == "raise_budget":
            spent = await spent_usd(session, mission.run_id)
            if budget_usd is None or budget_usd <= spent:
                raise InvalidTransition(f"the new budget must be above the {spent} USD spent")
            mission.budget_usd = budget_usd
    # The answer is recorded before the change it causes. If the mission turns out not to be
    # waiting, InvalidTransition rolls the whole transaction back, event included.
    await append_event(
        session,
        mission.run_id,
        EventType.NEED_ANSWERED,
        payload={"need_id": str(need.id), "action": action},
    )
    reason = f"you chose {action.replace('_', ' ')}"
    if not await set_status(session, mission.id, target, only_from=("needs_user",), reason=reason):
        raise InvalidTransition("the mission is not waiting for you")
    need.status = "answered"
    need.answer = {"action": action, "budget_usd": float(budget_usd) if budget_usd else None}
    need.answered_at = func.clock_timestamp()
    await session.flush()
    return target
