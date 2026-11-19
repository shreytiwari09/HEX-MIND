"""The skill registry (PRD §11.2): what skills exist, where they come from, and who has them."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.persona import builtin_personas
from app.api.deps import SettingsDep
from app.skills.registry import SkillRegistry

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillOut(BaseModel):
    name: str
    description: str
    source: str  # builtin | user
    version: str  # name@<hash prefix>: recorded on every handoff
    files: list[str]
    personas: list[str]  # built-in personas that list it


class SkillsOut(BaseModel):
    skills: list[SkillOut]
    # Skill folders that failed validation, with the reason; they are never offered to agents.
    problems: dict[str, str]


@router.get("", response_model=SkillsOut)
async def list_skills(settings: SettingsDep) -> SkillsOut:
    skills, problems = SkillRegistry(settings.data_dir / "skills").load()
    owners: dict[str, list[str]] = {}
    for persona in builtin_personas().values():
        for name in persona.skills:
            owners.setdefault(name, []).append(persona.id)
    return SkillsOut(
        skills=[
            SkillOut(
                name=s.name,
                description=s.description,
                source=s.source,
                version=s.version,
                files=list(s.files),
                personas=owners.get(s.name, []),
            )
            for s in skills.values()
        ],
        problems=problems,
    )
