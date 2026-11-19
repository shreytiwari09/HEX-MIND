"""Missions (PRD §12.4): create one from a hand-written plan, read it back."""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ServicesDep, SessionDep, SettingsDep
from app.db.models import Mission, Need, Project
from app.missions import service
from app.missions.models import MissionPlan

router = APIRouter(prefix="/missions", tags=["missions"])
needs_router = APIRouter(prefix="/needs", tags=["needs"])


class MissionCreate(BaseModel):
    project_id: uuid.UUID
    idea: str = Field(min_length=3, max_length=8000)
    plan: MissionPlan
    budget_usd: Decimal | None = Field(default=None, gt=0, le=10_000)


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
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    milestones: list[MilestoneOut]


async def _mission_out(session: SessionDep, mission: Mission) -> MissionOut:
    document = await service.features_document(session, mission)
    return MissionOut(
        id=mission.id,
        project_id=mission.project_id,
        run_id=mission.run_id,
        title=mission.title,
        idea=mission.idea,
        status=mission.status,
        branch=mission.branch,
        budget_usd=float(mission.budget_usd) if mission.budget_usd is not None else None,
        spent_usd=float(await service.spent_usd(session, mission.run_id)),
        created_at=mission.created_at,
        started_at=mission.started_at,
        finished_at=mission.finished_at,
        milestones=[MilestoneOut.model_validate(m) for m in document["milestones"]],
    )


@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
async def create_mission(
    body: MissionCreate, session: SessionDep, settings: SettingsDep
) -> MissionOut:
    project = await session.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    try:
        mission = await service.create_mission(
            session,
            settings,
            project,
            idea=body.idea,
            plan=body.plan,
            budget_usd=body.budget_usd,
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


async def _move(session: SessionDep, mission: Mission, to: str, only_from: tuple[str, ...]) -> None:
    if not await service.set_status(session, mission.id, to, only_from=only_from):
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
    await _move(session, mission, "running", ("awaiting_approval",))
    _launch(services, mission)
    return await _mission_out(session, mission)


@router.post("/{mission_id}/pause", response_model=MissionOut)
async def pause(mission_id: uuid.UUID, session: SessionDep) -> MissionOut:
    """The step in flight finishes, then the mission stops."""
    mission = await _get(session, mission_id)
    await _move(session, mission, "paused", ("running",))
    return await _mission_out(session, mission)


@router.post("/{mission_id}/resume", response_model=MissionOut)
async def resume(mission_id: uuid.UUID, session: SessionDep, services: ServicesDep) -> MissionOut:
    mission = await _get(session, mission_id)
    if services.mission_active(mission.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the mission is still finishing its current step; try again"
        )
    await _move(session, mission, "running", ("paused",))
    _launch(services, mission)
    return await _mission_out(session, mission)


@router.post("/{mission_id}/stop", response_model=MissionOut)
async def stop(mission_id: uuid.UUID, session: SessionDep, services: ServicesDep) -> MissionOut:
    """Cancel the mission. A runner mid-step finishes that step and exits."""
    mission = await _get(session, mission_id)
    await _move(session, mission, "cancelled", service.OPEN_STATES)
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
