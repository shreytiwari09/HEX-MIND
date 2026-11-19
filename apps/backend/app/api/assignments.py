"""Per-persona model assignments (PRD §12.4): which model each persona uses."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.persona import builtin_personas
from app.api.deps import SessionDep
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
    if persona_id not in builtin_personas():
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
