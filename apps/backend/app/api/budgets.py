"""Per-persona budgets (PRD §11.1, §8.6): the most a persona may spend in one mission."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.persona import all_personas
from app.api.deps import SessionDep
from app.db.models import PersonaBudget

router = APIRouter(prefix="/budgets/personas", tags=["budgets"])


class BudgetIn(BaseModel):
    budget_usd: Decimal = Field(gt=0, le=10_000)


class BudgetOut(BaseModel):
    persona_id: str
    budget_usd: float


@router.get("", response_model=list[BudgetOut])
async def list_budgets(session: SessionDep) -> list[BudgetOut]:
    rows = await session.scalars(select(PersonaBudget).order_by(PersonaBudget.persona_id))
    return [BudgetOut(persona_id=r.persona_id, budget_usd=float(r.budget_usd)) for r in rows]


@router.put("/{persona_id}", response_model=BudgetOut)
async def set_budget(persona_id: str, body: BudgetIn, session: SessionDep) -> BudgetOut:
    if persona_id not in all_personas():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona not found")
    await session.merge(PersonaBudget(persona_id=persona_id, budget_usd=body.budget_usd))
    return BudgetOut(persona_id=persona_id, budget_usd=float(body.budget_usd))


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_budget(persona_id: str, session: SessionDep) -> None:
    row = await session.get(PersonaBudget, persona_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no budget for this persona")
    await session.delete(row)
