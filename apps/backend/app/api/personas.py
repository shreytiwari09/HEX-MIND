"""The built-in personas (PRD §12.4): who is on the team."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.persona import builtin_personas

router = APIRouter(prefix="/personas", tags=["personas"])


class PersonaOut(BaseModel):
    id: str
    name: str
    kind: str  # orchestrator | worker | validator | research
    skills: list[str]
    plugins: list[str]


@router.get("", response_model=list[PersonaOut])
async def list_personas() -> list[PersonaOut]:
    return [
        PersonaOut(id=p.id, name=p.name, kind=p.kind, skills=p.skills, plugins=p.plugins)
        for p in builtin_personas().values()
    ]
