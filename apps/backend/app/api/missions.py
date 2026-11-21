"""Missions (PRD §12.4): create one from a hand-written plan, read it back."""

import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agents import variants
from app.api.deps import ServicesDep, SessionDep, SettingsDep
from app.api.schemas import EventOut, FileDiffOut, RunDiffOut
from app.db.models import (
    AgentEvent,
    Connection,
    LLMCall,
    Mission,
    ModelAssignment,
    Need,
    PersonaBudget,
    Project,
    ValidatorReportRow,
)
from app.events.schema import EventType
from app.missions import lifecycle, service
from app.missions.apply import Refused
from app.missions.models import Coordination, MissionPlan

router = APIRouter(prefix="/missions", tags=["missions"])
needs_router = APIRouter(prefix="/needs", tags=["needs"])


class MissionCreate(BaseModel):
    project_id: uuid.UUID
    idea: str = Field(min_length=3, max_length=8000)
    plan: MissionPlan
    budget_usd: Decimal | None = Field(default=None, gt=0, le=10_000)
    variant_id: str | None = Field(default=None, max_length=32)  # run under a prompt variant
    coordination: Coordination = "blackboard"  # how the agents share state (PRD §9.8)


class FeatureOut(BaseModel):
    id: str
    title: str
    persona: str
    status: str
    attempts: int
    commit: str | None
    description: str
    preconditions: list[str]
    expected_behavior: list[str]
    contract_refs: list[str]
    extra_skills: list[str]
    target_files: list[str]


class MilestoneOut(BaseModel):
    id: str
    title: str
    status: str
    validators: list[str]
    features: list[FeatureOut]


class ApplyOut(BaseModel):
    """What Apply wrote into the user's project (None until the mission is applied)."""

    state: str  # applied | reverted
    files: list[str]
    commit: str | None
    commit_error: str | None
    include_mission_files: bool


class MissionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    title: str
    idea: str
    status: str
    branch: str
    budget_usd: float | None
    spent_usd: float  # summed from the provider layer's llm_calls
    tokens_in: int
    tokens_out: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    milestones: list[MilestoneOut]
    apply: ApplyOut | None
    validation_contract: list[dict]  # type: ignore[type-arg]
    variant_id: str | None = None  # the prompt variant it ran under
    coordination: str = "blackboard"


async def _mission_out(session: SessionDep, mission: Mission) -> MissionOut:
    document = await service.features_document(session, mission)
    totals = await service.usage(session, mission.run_id)
    return MissionOut(
        id=mission.id,
        project_id=mission.project_id,
        run_id=mission.run_id,
        title=mission.title,
        idea=mission.idea,
        status=mission.status,
        branch=mission.branch,
        budget_usd=float(mission.budget_usd) if mission.budget_usd is not None else None,
        spent_usd=float(totals.spent_usd),
        tokens_in=totals.tokens_in,
        tokens_out=totals.tokens_out,
        created_at=mission.created_at,
        started_at=mission.started_at,
        finished_at=mission.finished_at,
        milestones=[MilestoneOut.model_validate(m) for m in document["milestones"]],
        apply=_apply_out(mission.apply_record),
        validation_contract=mission.validation_contract or [],
        variant_id=mission.variant_id,
        coordination=mission.coordination,
    )


def _apply_out(record: dict | None) -> ApplyOut | None:
    if not record:
        return None
    return ApplyOut(
        state=record["state"],
        files=[f["path"] for f in record["files"]],
        commit=record.get("commit"),
        commit_error=record.get("commit_error"),
        include_mission_files=record["include_mission_files"],
    )


@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
async def create_mission(
    body: MissionCreate, session: SessionDep, settings: SettingsDep
) -> MissionOut:
    project = await session.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    try:
        await variants.get(session, body.variant_id)
    except variants.VariantError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    try:
        mission = await service.create_mission(
            session,
            settings,
            project,
            idea=body.idea,
            plan=body.plan,
            budget_usd=body.budget_usd,
            variant_id=body.variant_id,
            coordination=body.coordination,
        )
    except service.NotAGitRepo:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "missions need a Git repository: initialize Git for this project first",
        ) from None
    return await _mission_out(session, mission)


@router.get("", response_model=list[MissionOut])
async def list_missions(session: SessionDep, project_id: uuid.UUID) -> list[MissionOut]:
    missions = await session.scalars(
        select(Mission)
        .where(Mission.project_id == project_id)
        .order_by(Mission.created_at.desc())
        .limit(50)
    )
    return [await _mission_out(session, mission) for mission in missions]


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(mission_id: uuid.UUID, session: SessionDep) -> MissionOut:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    return await _mission_out(session, mission)


# ---------- control (PRD §8.1, §8.7) ----------


async def _get(session: SessionDep, mission_id: uuid.UUID) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    return mission


async def _move(
    session: SessionDep, mission: Mission, to: str, only_from: tuple[str, ...], reason: str
) -> None:
    if not await service.set_status(session, mission.id, to, only_from=only_from, reason=reason):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"a {mission.status} mission cannot move to {to}",
        )
    await session.commit()  # the runner reads this status as soon as it starts
    await session.refresh(mission)


def _launch(services: ServicesDep, mission: Mission) -> None:
    if services.mission_active(mission.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the mission is still finishing its current step; try again"
        )
    services.launch_mission(mission.id)


@router.post("/{mission_id}/approve", response_model=MissionOut)
async def approve(mission_id: uuid.UUID, session: SessionDep, services: ServicesDep) -> MissionOut:
    """Approve the plan and start building."""
    mission = await _get(session, mission_id)
    await _move(session, mission, "running", ("awaiting_approval",), "plan approved")
    _launch(services, mission)
    return await _mission_out(session, mission)


@router.post("/{mission_id}/pause", response_model=MissionOut)
async def pause(mission_id: uuid.UUID, session: SessionDep) -> MissionOut:
    """The step in flight finishes, then the mission stops."""
    mission = await _get(session, mission_id)
    await _move(session, mission, "paused", ("running",), "paused by you")
    return await _mission_out(session, mission)


@router.post("/{mission_id}/resume", response_model=MissionOut)
async def resume(mission_id: uuid.UUID, session: SessionDep, services: ServicesDep) -> MissionOut:
    mission = await _get(session, mission_id)
    if services.mission_active(mission.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the mission is still finishing its current step; try again"
        )
    await _move(session, mission, "running", ("paused",), "resumed by you")
    _launch(services, mission)
    return await _mission_out(session, mission)


@router.post("/{mission_id}/stop", response_model=MissionOut)
async def stop(mission_id: uuid.UUID, session: SessionDep, services: ServicesDep) -> MissionOut:
    """Cancel the mission. A runner mid-step finishes that step and exits."""
    mission = await _get(session, mission_id)
    await _move(session, mission, "cancelled", service.OPEN_STATES, "stopped by you")
    if not services.mission_active(mission.id):
        await service.settle_cancelled(services, mission.id)
    return await _mission_out(session, mission)


# ---------- Needs you (PRD §8.6) ----------


class NeedOut(BaseModel):
    id: uuid.UUID
    mission_id: uuid.UUID
    feature_id: uuid.UUID | None
    kind: str
    summary: str
    evidence: dict
    options: list[str]
    status: str
    created_at: datetime


class NeedAnswer(BaseModel):
    action: str
    budget_usd: Decimal | None = Field(default=None, gt=0, le=10_000)


@router.get("/{mission_id}/needs", response_model=list[NeedOut])
async def list_needs(mission_id: uuid.UUID, session: SessionDep) -> list[Need]:
    await _get(session, mission_id)
    result = await session.scalars(
        select(Need).where(Need.mission_id == mission_id).order_by(Need.created_at)
    )
    return list(result)


@needs_router.post("/{need_id}/answer", response_model=MissionOut)
async def answer_need(
    need_id: uuid.UUID, body: NeedAnswer, session: SessionDep, services: ServicesDep
) -> MissionOut:
    need = await session.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    if services.mission_active(need.mission_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the mission is still finishing its current step; try again"
        )
    try:
        outcome = await service.answer_need(
            session, need, action=body.action, budget_usd=body.budget_usd
        )
    except service.InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    mission = await _get(session, need.mission_id)
    if outcome == "running":
        _launch(services, mission)
    else:
        await service.settle_cancelled(services, mission.id)
    return await _mission_out(session, mission)


# ---------- review, apply, revert, restore (PRD §8.8) ----------


def _refuse(exc: Refused) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


async def _after(session: SessionDep, mission_id: uuid.UUID) -> MissionOut:
    session.expire_all()
    return await _mission_out(session, await _get(session, mission_id))


@router.get("/{mission_id}/diff", response_model=RunDiffOut)
async def get_diff(mission_id: uuid.UUID, services: ServicesDep) -> RunDiffOut:
    """The proposed changes, live from the mission worktree, for review before Apply."""
    try:
        ctx, files = await lifecycle.mission_diff(services, mission_id)
    except Refused as exc:
        raise _refuse(exc) from None
    return RunDiffOut(
        run_id=ctx.run.id,
        base_commit=ctx.run.base_commit,
        files=[FileDiffOut(**f) for f in files],
    )


class ApplyRequest(BaseModel):
    # None: follow the server setting (the `.hex/` mission files are applied by default).
    include_mission_files: bool | None = None
    commit: bool = True  # record the result as a commit on the user's current branch


@router.post("/{mission_id}/apply", response_model=MissionOut)
async def apply_mission(
    mission_id: uuid.UUID,
    session: SessionDep,
    services: ServicesDep,
    request: Request,
    body: ApplyRequest | None = None,
) -> MissionOut:
    """Write the mission's changes into the user's project (explicit user action)."""
    await _get(session, mission_id)
    body = body or ApplyRequest()
    try:
        await lifecycle.apply_mission(
            services,
            mission_id,
            include_mission_files=body.include_mission_files,
            commit=body.commit,
        )
    except Refused as exc:
        raise _refuse(exc) from None
    await _restart_app(request, session, mission_id)
    return await _after(session, mission_id)


async def _restart_app(request: Request, session: SessionDep, mission_id: uuid.UUID) -> None:
    """An app the user is running from the project folder restarts with the applied files (D71);
    it runs in the background, so Apply does not wait for it."""
    runner = getattr(request.app.state, "apps", None)
    mission = await session.get(Mission, mission_id)
    if runner is None or mission is None:
        return
    running = runner.get(str(mission.project_id))
    project = await session.get(Project, mission.project_id)
    if running is None or project is None or running.folder != project.workspace_path:
        return
    services = request.app.state.services
    services.background.spawn(
        runner.start(str(project.id), Path(project.workspace_path)), name=f"app-{project.id}"
    )


@router.post("/{mission_id}/revert", response_model=MissionOut)
async def revert_mission(
    mission_id: uuid.UUID, session: SessionDep, services: ServicesDep
) -> MissionOut:
    await _get(session, mission_id)
    try:
        await lifecycle.revert_mission(services, mission_id)
    except Refused as exc:
        raise _refuse(exc) from None
    return await _after(session, mission_id)


@router.post("/{mission_id}/keep", response_model=MissionOut)
async def keep_mission(
    mission_id: uuid.UUID, session: SessionDep, services: ServicesDep
) -> MissionOut:
    await _get(session, mission_id)
    try:
        await lifecycle.keep_mission(services, mission_id)
    except Refused as exc:
        raise _refuse(exc) from None
    return await _after(session, mission_id)


@router.post("/{mission_id}/discard", response_model=MissionOut)
async def discard_mission(
    mission_id: uuid.UUID, session: SessionDep, services: ServicesDep
) -> MissionOut:
    await _get(session, mission_id)
    try:
        await lifecycle.discard_mission(services, mission_id)
    except Refused as exc:
        raise _refuse(exc) from None
    return await _after(session, mission_id)


class CheckpointOut(BaseModel):
    commit: str
    label: str
    feature_id: uuid.UUID | None
    created_at: datetime


@router.get("/{mission_id}/checkpoints", response_model=list[CheckpointOut])
async def list_checkpoints(mission_id: uuid.UUID, services: ServicesDep) -> list[CheckpointOut]:
    try:
        rows = await lifecycle.list_checkpoints(services, mission_id)
    except Refused as exc:
        raise _refuse(exc) from None
    return [
        CheckpointOut(
            commit=c.commit, label=c.label, feature_id=c.feature_id, created_at=c.created_at
        )
        for c in rows
    ]


@router.post("/{mission_id}/checkpoints/{commit}/restore", response_model=MissionOut)
async def restore_checkpoint(
    mission_id: uuid.UUID, commit: str, session: SessionDep, services: ServicesDep
) -> MissionOut:
    """Rewind the mission to a feature's checkpoint; it comes back paused, ready to resume."""
    await _get(session, mission_id)
    try:
        await lifecycle.restore_checkpoint(services, mission_id, commit)
    except Refused as exc:
        raise _refuse(exc) from None
    return await _after(session, mission_id)


# ---------- costs and delegation (PRD S8) ----------


class CostRow(BaseModel):
    spent_usd: float
    calls: int
    tokens_in: int
    tokens_out: int


class PersonaCost(CostRow):
    persona_id: str | None  # None: calls not made for a persona (routing, summaries)
    budget_usd: float | None


class ModelCost(CostRow):
    provider: str  # the connection's name
    model: str


class CostsOut(BaseModel):
    total_usd: float
    budget_usd: float | None
    tokens_in: int
    tokens_out: int
    calls: int
    # Successful calls whose model has no known price: their cost is not in the totals.
    unpriced_calls: int
    by_persona: list[PersonaCost]
    by_model: list[ModelCost]


@router.get("/{mission_id}/costs", response_model=CostsOut)
async def mission_costs(mission_id: uuid.UUID, session: SessionDep) -> CostsOut:
    """Real spend and tokens from the provider layer, by persona and by model."""
    mission = await _get(session, mission_id)
    totals = await service.usage(session, mission.run_id)

    def rows(*columns):  # type: ignore[no-untyped-def]
        return (
            select(
                *columns,
                func.coalesce(func.sum(LLMCall.est_cost_usd), 0),
                func.count(),
                func.coalesce(func.sum(LLMCall.input_tokens), 0),
                func.coalesce(func.sum(LLMCall.output_tokens), 0),
            )
            .where(LLMCall.run_id == mission.run_id)
            .group_by(*columns)
        )

    budgets = {
        pid: float(b)
        for pid, b in (
            await session.execute(select(PersonaBudget.persona_id, PersonaBudget.budget_usd))
        )
        if b is not None
    }
    by_persona = [
        PersonaCost(
            persona_id=pid,
            budget_usd=budgets.get(pid) if pid else None,
            spent_usd=float(cost),
            calls=calls,
            tokens_in=int(tin),
            tokens_out=int(tout),
        )
        for pid, cost, calls, tin, tout in await session.execute(rows(LLMCall.persona_id))
    ]
    by_model = [
        ModelCost(
            provider=provider,
            model=model,
            spent_usd=float(cost),
            calls=calls,
            tokens_in=int(tin),
            tokens_out=int(tout),
        )
        for provider, model, cost, calls, tin, tout in await session.execute(
            rows(LLMCall.provider, LLMCall.model)
        )
    ]
    return CostsOut(
        total_usd=float(totals.spent_usd),
        budget_usd=float(mission.budget_usd) if mission.budget_usd is not None else None,
        tokens_in=totals.tokens_in,
        tokens_out=totals.tokens_out,
        calls=totals.calls,
        unpriced_calls=totals.unpriced_calls,
        by_persona=sorted(by_persona, key=lambda r: -r.spent_usd),
        by_model=sorted(by_model, key=lambda r: -r.spent_usd),
    )


class DelegationAssignment(BaseModel):
    persona_id: str
    connection: str | None
    model: str
    set_by: str
    reason: str | None
    escalate_model: str | None
    budget_usd: float | None


class DelegationOut(BaseModel):
    # How each persona is set up now (not a history), with the reason Auto gave.
    assignments: list[DelegationAssignment]
    # What actually happened in this mission, oldest first.
    events: list[EventOut]


DELEGATION_EVENTS = (
    EventType.PROVIDER_FALLBACK,
    EventType.KEY_ROTATED,
    EventType.ESCALATED,
    EventType.BUDGET_WARNING,
    EventType.NEED_RAISED,
)


@router.get("/{mission_id}/delegation", response_model=DelegationOut)
async def mission_delegation(mission_id: uuid.UUID, session: SessionDep) -> DelegationOut:
    """The delegation log (PRD §10.6): who uses which model and why, and every fallback, key
    rotation, escalation and budget event of this mission."""
    mission = await _get(session, mission_id)
    names = {c.id: c.name for c in await session.scalars(select(Connection))}
    budgets = {
        pid: float(b)
        for pid, b in await session.execute(
            select(PersonaBudget.persona_id, PersonaBudget.budget_usd)
        )
    }
    assignments = [
        DelegationAssignment(
            persona_id=a.persona_id,
            connection=names.get(a.primary_connection_id),
            model=a.primary_model,
            set_by=a.set_by,
            reason=a.reason,
            escalate_model=(a.escalate or {}).get("model"),
            budget_usd=budgets.get(a.persona_id),
        )
        for a in await session.scalars(select(ModelAssignment).order_by(ModelAssignment.persona_id))
    ]
    events = await session.scalars(
        select(AgentEvent)
        .where(
            AgentEvent.run_id == mission.run_id,
            AgentEvent.type.in_([t.value for t in DELEGATION_EVENTS]),
        )
        .order_by(AgentEvent.seq)
    )
    return DelegationOut(
        assignments=assignments, events=[EventOut.model_validate(e) for e in events]
    )


# ---------- validation (PRD §8.5) ----------


class ValidatorReportOut(BaseModel):
    milestone_id: str
    validator: str
    round: int
    verdict: str
    findings: list[dict]  # type: ignore[type-arg]
    commands: list[dict]  # type: ignore[type-arg]
    created_at: datetime


@router.get("/{mission_id}/validation", response_model=list[ValidatorReportOut])
async def mission_validation(
    mission_id: uuid.UUID, session: SessionDep
) -> list[ValidatorReportOut]:
    """What each validator found at the end of each milestone, oldest first."""
    await _get(session, mission_id)
    rows = await session.scalars(
        select(ValidatorReportRow)
        .where(ValidatorReportRow.mission_id == mission_id)
        .order_by(ValidatorReportRow.created_at)
    )
    return [
        ValidatorReportOut(
            milestone_id=r.data["milestone_id"],
            validator=r.validator,
            round=r.round,
            verdict=r.verdict,
            findings=r.data["findings"],
            commands=r.data["commands"],
            created_at=r.created_at,
        )
        for r in rows
    ]
