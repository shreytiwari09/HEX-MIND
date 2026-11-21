"""Per-persona model assignments (PRD §12.4): which model each persona uses."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.persona import all_personas
from app.api.deps import ServicesDep, SessionDep
from app.catalog.assigner import Pick, Preset, assign
from app.catalog.measured import role_loads
from app.catalog.requirements import requirements_with_custom
from app.db.models import ModelAssignment
from app.providers import assignments
from app.providers.assignments import AssignmentError, AssignmentIn, ModelRef

router = APIRouter(prefix="/assignments", tags=["assignments"])


class AssignmentOut(BaseModel):
    persona_id: str
    primary: ModelRef
    fallbacks: list[ModelRef]
    escalate: ModelRef | None
    set_by: str
    reason: str | None
    updated_at: datetime


def _out(row: ModelAssignment) -> AssignmentOut:
    return AssignmentOut(
        persona_id=row.persona_id,
        primary=ModelRef(connection_id=row.primary_connection_id, model=row.primary_model),
        fallbacks=[ModelRef.model_validate(f) for f in row.fallbacks or []],
        escalate=ModelRef.model_validate(row.escalate) if row.escalate else None,
        set_by=row.set_by,
        reason=row.reason,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[AssignmentOut])
async def list_assignments(session: SessionDep) -> list[AssignmentOut]:
    rows = await session.scalars(select(ModelAssignment).order_by(ModelAssignment.persona_id))
    return [_out(r) for r in rows]


@router.put("/{persona_id}", response_model=AssignmentOut)
async def put_assignment(persona_id: str, body: AssignmentIn, session: SessionDep) -> AssignmentOut:
    if persona_id not in all_personas():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona not found")
    try:
        return _out(await assignments.set_assignment(session, persona_id, body))
    except AssignmentError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(persona_id: str, session: SessionDep) -> None:
    row = await session.scalar(
        select(ModelAssignment).where(ModelAssignment.persona_id == persona_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no assignment for this persona")
    await session.delete(row)


class AutoRequest(BaseModel):
    preset: Preset = "balanced"
    # Compute and show the choices without saving them.
    dry_run: bool = False
    # By default a persona you assigned yourself is left alone.
    overwrite_manual: bool = False


class ProposalOut(BaseModel):
    persona_id: str
    primary: ModelRef | None
    fallbacks: list[ModelRef]
    escalate: ModelRef | None
    reason: str
    verified: bool
    # What happened: saved, would_save (dry run), kept_manual, or none (nothing usable).
    outcome: Literal["saved", "would_save", "kept_manual", "none"]


class AutoResult(BaseModel):
    preset: str
    proposals: list[ProposalOut]


def _ref(pick: Pick | None) -> ModelRef | None:
    return ModelRef(connection_id=uuid.UUID(pick.connection_id), model=pick.model) if pick else None


@router.post("/auto", response_model=AutoResult)
async def auto_assign(body: AutoRequest, session: SessionDep, services: ServicesDep) -> AutoResult:
    """Choose a model for every persona from the models you can reach (PRD §10.4), with a
    one-line reason each. Auto never overwrites a persona you set yourself unless asked."""
    assert services.catalog is not None
    entries = await services.catalog.entries(session)
    persona_ids = sorted(all_personas())
    loads = await role_loads(session)  # what each role's requests weigh, measured here (D71)
    proposals = assign(persona_ids, entries, body.preset, requirements_with_custom(), loads)
    existing = {row.persona_id: row for row in await session.scalars(select(ModelAssignment))}

    out: list[ProposalOut] = []
    for proposal in proposals:
        current = existing.get(proposal.persona_id)
        manual = current is not None and current.set_by == "user"
        if manual and not body.overwrite_manual:
            outcome = "kept_manual"
        elif proposal.primary is None:
            outcome = "none"
            if current is not None and not body.dry_run:
                await session.delete(current)  # a stale automatic choice is not kept
        else:
            outcome = "would_save" if body.dry_run else "saved"
            if not body.dry_run:
                await assignments.set_assignment(
                    session,
                    proposal.persona_id,
                    AssignmentIn(
                        primary=_ref(proposal.primary),  # type: ignore[arg-type]
                        fallbacks=[_ref(p) for p in proposal.fallbacks],  # type: ignore[misc]
                        escalate=_ref(proposal.escalate),
                    ),
                    set_by="auto",
                    reason=proposal.reason,
                )
        out.append(
            ProposalOut(
                persona_id=proposal.persona_id,
                primary=_ref(proposal.primary),
                fallbacks=[r for p in proposal.fallbacks if (r := _ref(p))],
                escalate=_ref(proposal.escalate),
                reason=proposal.reason,
                verified=proposal.verified,
                outcome=outcome,  # type: ignore[arg-type]
            )
        )
    return AutoResult(preset=body.preset, proposals=out)
