"""The team (PRD §7, §11.1): the built-in personas, the user's edits to them, and custom ones.
Every change is a new version; the crew gets the current one on its next job."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.agents import store
from app.agents.persona import UnknownPersona, all_personas
from app.api.deps import SessionDep, SettingsDep
from app.skills.registry import SkillRegistry

router = APIRouter(prefix="/personas", tags=["personas"])


class PersonaOut(BaseModel):
    id: str
    name: str
    kind: str  # orchestrator | worker | validator | research
    skills: list[str]
    plugins: list[str]
    instructions: str
    version: int
    source: str  # builtin | customized | custom
    # Skills this persona lists that do not exist (never offered to the agent).
    missing_skills: list[str]


class PersonaEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    instructions: str | None = Field(default=None, max_length=store.MAX_INSTRUCTIONS)
    skills: list[str] | None = Field(default=None, max_length=store.MAX_SKILLS)
    plugins: list[str] | None = Field(default=None, max_length=10)


class PersonaCreateIn(BaseModel):
    id: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=60)
    instructions: str = Field(min_length=store.MIN_INSTRUCTIONS, max_length=store.MAX_INSTRUCTIONS)
    skills: list[str] = Field(default_factory=list, max_length=store.MAX_SKILLS)


class VersionOut(BaseModel):
    version: int
    snapshot: dict[str, Any]
    created_at: datetime


def _registry(settings: SettingsDep) -> SkillRegistry:
    return SkillRegistry(settings.data_dir / "skills")


async def _out(session: SessionDep, persona_id: str, registry: SkillRegistry) -> PersonaOut:
    rows = await store.rows_by_id(session)
    persona = all_personas()[persona_id]
    _, missing = registry.resolve(persona.skills)
    return PersonaOut(
        id=persona.id,
        name=persona.name,
        kind=persona.kind,
        skills=persona.skills,
        plugins=persona.plugins,
        instructions=persona.instructions,
        version=persona.version,
        source=store.source_of(persona.id, rows),
        missing_skills=missing,
    )


def _refused(exc: store.PersonaError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.get("", response_model=list[PersonaOut])
async def list_personas(session: SessionDep, settings: SettingsDep) -> list[PersonaOut]:
    registry = _registry(settings)
    return [await _out(session, pid, registry) for pid in all_personas()]


@router.get("/{persona_id}", response_model=PersonaOut)
async def get_persona(persona_id: str, session: SessionDep, settings: SettingsDep) -> PersonaOut:
    if persona_id not in all_personas():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona not found")
    return await _out(session, persona_id, _registry(settings))


@router.put("/{persona_id}", response_model=PersonaOut)
async def edit_persona(
    persona_id: str, body: PersonaEditIn, session: SessionDep, settings: SettingsDep
) -> PersonaOut:
    registry = _registry(settings)
    try:
        await store.edit(
            session,
            persona_id,
            store.Edit(
                name=body.name,
                instructions=body.instructions,
                skills=body.skills,
                plugins=body.plugins,
            ),
            registry,
        )
    except store.PersonaError as exc:
        raise _refused(exc) from None
    return await _out(session, persona_id, registry)


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(
    body: PersonaCreateIn, session: SessionDep, settings: SettingsDep
) -> PersonaOut:
    registry = _registry(settings)
    try:
        persona = await store.create(
            session,
            persona_id=body.id,
            name=body.name,
            instructions=body.instructions,
            skills=body.skills,
            registry=registry,
        )
    except store.PersonaError as exc:
        raise _refused(exc) from None
    return await _out(session, persona.id, registry)


@router.delete("/{persona_id}", response_model=PersonaOut | None)
async def delete_persona(
    persona_id: str, session: SessionDep, settings: SettingsDep, response: Response
) -> PersonaOut | None:
    """Delete a custom persona, or reset a built-in one to its default (returned)."""
    try:
        what = await store.remove(session, persona_id)
    except store.PersonaError as exc:
        raise _refused(exc) from None
    if what == "deleted":
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return await _out(session, persona_id, _registry(settings))


@router.get("/{persona_id}/versions", response_model=list[VersionOut])
async def persona_versions(persona_id: str, session: SessionDep) -> list[VersionOut]:
    try:
        rows = await store.versions(session, persona_id)
    except UnknownPersona:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona not found") from None
    return [
        VersionOut(version=r.version, snapshot=r.snapshot, created_at=r.created_at) for r in rows
    ]
