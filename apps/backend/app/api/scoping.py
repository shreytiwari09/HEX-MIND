"""The PM scoping chat and plan review (PRD F2): start from an idea, answer the PM, edit the
plan, then turn it into a mission awaiting approval."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.agents import variants
from app.api.deps import ServicesDep, SessionDep, SettingsDep
from app.api.missions import MissionOut, _mission_out
from app.db.models import Project, ScopingSession
from app.missions import scoping, service
from app.missions.models import Coordination, MissionPlan

router = APIRouter(prefix="/scoping", tags=["scoping"])


class ScopingCreate(BaseModel):
    project_id: uuid.UUID
    idea: str = Field(min_length=3, max_length=8000)
    budget_usd: Decimal | None = Field(default=None, gt=0, le=10_000)
    variant_id: str | None = Field(default=None, max_length=32)
    coordination: Coordination = "blackboard"
    # Advanced research: researchers search and read public websites before the PM plans. It
    # needs `research_confirmed`, the user's tick that they know that.
    research: bool = False
    research_confirmed: bool = False

    @model_validator(mode="after")
    def _research_needs_a_tick(self) -> "ScopingCreate":
        if self.research and not self.research_confirmed:
            raise ValueError("confirm that researchers may search the web and read public websites")
        return self


class ScopingReply(BaseModel):
    content: str = Field(min_length=1, max_length=scoping.MAX_MESSAGE_CHARS)


class PlanEdit(BaseModel):
    plan: MissionPlan
    prd: str | None = Field(default=None, max_length=scoping.MAX_PRD_CHARS)
    budget_usd: Decimal | None = Field(default=None, gt=0, le=10_000)


class ScopingOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    idea: str
    status: str
    messages: list[dict[str, Any]]
    plan: dict[str, Any] | None
    prd: str | None
    error: str | None
    budget_usd: float | None
    mission_id: uuid.UUID | None
    variant_id: str | None = None
    coordination: str = "blackboard"
    research: bool = False
    research_notes: dict[str, Any] | None = None
    # What the calls cost so far (from llm_calls, not estimated). It covers only calls whose
    # model has a known price: `unpriced_calls` says how many answered without one.
    cost_usd: float
    unpriced_calls: int = 0
    created_at: datetime
    updated_at: datetime


async def _out(session: SessionDep, row: ScopingSession) -> ScopingOut:
    await session.refresh(row)
    spent = await service.usage(session, row.run_id)  # the same totals a mission reports
    return ScopingOut(
        id=row.id,
        project_id=row.project_id,
        run_id=row.run_id,
        idea=row.idea,
        status=row.status,
        messages=row.messages,
        plan=row.plan,
        prd=row.prd,
        error=row.error,
        budget_usd=float(row.budget_usd) if row.budget_usd is not None else None,
        mission_id=row.mission_id,
        variant_id=row.variant_id,
        coordination=row.coordination,
        research=row.research,
        research_notes=row.research_notes,
        cost_usd=float(spent.spent_usd),
        unpriced_calls=spent.unpriced_calls,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _refused(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc).strip("'\""))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post("", response_model=ScopingOut, status_code=status.HTTP_201_CREATED)
async def start(body: ScopingCreate, session: SessionDep, services: ServicesDep) -> ScopingOut:
    """Start scoping an idea; the PM answers before this returns."""
    project = await session.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    try:
        await variants.get(session, body.variant_id)
    except variants.VariantError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    try:
        row = await scoping.start(
            session,
            services,
            project,
            idea=body.idea,
            budget_usd=body.budget_usd,
            variant_id=body.variant_id,
            coordination=body.coordination,
            advanced_research=body.research,
        )
    except scoping.ScopingError as exc:
        raise _refused(exc) from None
    return await _out(session, row)


@router.get("", response_model=list[ScopingOut])
async def list_sessions(session: SessionDep, project_id: uuid.UUID) -> list[ScopingOut]:
    rows = await session.scalars(
        select(ScopingSession)
        .where(ScopingSession.project_id == project_id)
        .order_by(ScopingSession.created_at.desc())
        .limit(50)
    )
    return [await _out(session, row) for row in rows]


@router.get("/{scoping_id}", response_model=ScopingOut)
async def get_session(scoping_id: uuid.UUID, session: SessionDep) -> ScopingOut:
    row = await session.get(ScopingSession, scoping_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scoping session not found")
    return await _out(session, row)


@router.post("/{scoping_id}/messages", response_model=ScopingOut)
async def reply(
    scoping_id: uuid.UUID, body: ScopingReply, session: SessionDep, services: ServicesDep
) -> ScopingOut:
    try:
        row = await scoping.reply(session, services, scoping_id, body.content)
    except (LookupError, scoping.ScopingError) as exc:
        raise _refused(exc) from None
    return await _out(session, row)


@router.post("/{scoping_id}/retry", response_model=ScopingOut)
async def retry(scoping_id: uuid.UUID, session: SessionDep, services: ServicesDep) -> ScopingOut:
    try:
        row = await scoping.retry(session, services, scoping_id)
    except (LookupError, scoping.ScopingError) as exc:
        raise _refused(exc) from None
    return await _out(session, row)


@router.put("/{scoping_id}/plan", response_model=ScopingOut)
async def edit_plan(scoping_id: uuid.UUID, body: PlanEdit, session: SessionDep) -> ScopingOut:
    try:
        row = await scoping.edit_plan(
            session, scoping_id, plan=body.plan, prd=body.prd, budget_usd=body.budget_usd
        )
    except (LookupError, scoping.ScopingError) as exc:
        raise _refused(exc) from None
    return await _out(session, row)


@router.post("/{scoping_id}/mission", response_model=MissionOut, status_code=201)
async def to_mission(
    scoping_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> MissionOut:
    """Turn the plan into a mission awaiting approval."""
    try:
        mission = await scoping.to_mission(session, settings, scoping_id)
    except (LookupError, scoping.ScopingError) as exc:
        raise _refused(exc) from None
    except service.NotAGitRepo:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "missions need a Git repository: initialize Git for this project first",
        ) from None
    return await _mission_out(session, mission)


@router.post("/{scoping_id}/abandon", response_model=ScopingOut)
async def abandon(scoping_id: uuid.UUID, session: SessionDep) -> ScopingOut:
    try:
        row = await scoping.abandon(session, scoping_id)
    except (LookupError, scoping.ScopingError) as exc:
        raise _refused(exc) from None
    return await _out(session, row)
