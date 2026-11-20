"""Edited and custom personas (PRD §11.1): stored in Postgres, every change a new version.

A built-in persona can be edited (name, instructions, skills, plugins); the stored row then
overlays the YAML one, and deleting the row resets it. A custom persona is a worker the user
creates. Validators and the PM are fixed in code (their kind cannot change), and a custom
persona is always a worker, because validators are wired in code and research is not started
by anything yet.

The overlay lives in this process (`persona.set_overrides`); the crew service gets a snapshot of
the persona with each job and never reads the database.
"""

import re
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.persona import (
    Persona,
    UnknownPersona,
    all_personas,
    builtin_personas,
    set_overrides,
)
from app.db.models import FeatureRow, Mission, PersonaRow, PersonaVersion, PluginRow
from app.skills.registry import SkillRegistry

MAX_SKILLS = 12
MAX_INSTRUCTIONS = 8000
MIN_INSTRUCTIONS = 20
# A persona cannot be removed while a mission that is not finished still has work for it.
ACTIVE_MISSIONS = ("awaiting_approval", "running", "paused", "needs_user")
_ID = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


class PersonaError(ValueError):
    """The change is not allowed; the message says why. `status_code` suits an HTTP answer."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Edit:
    """The fields the user changed; None means unchanged."""

    name: str | None = None
    instructions: str | None = None
    skills: list[str] | None = None
    plugins: list[str] | None = None


def source_of(persona_id: str, rows: dict[str, PersonaRow]) -> str:
    """builtin (as shipped), customized (a built-in one the user edited) or custom (user-made)."""
    if persona_id not in rows:
        return "builtin"
    return "customized" if rows[persona_id].builtin else "custom"


def _snapshot(persona: Persona) -> dict[str, object]:
    return {
        "name": persona.name,
        "kind": persona.kind,
        "instructions": persona.instructions,
        "skills": persona.skills,
        "plugins": persona.plugins,
    }


def _to_persona(row: PersonaRow) -> Persona:
    return Persona(
        id=row.id,
        name=row.name,
        kind=row.kind,  # type: ignore[arg-type]
        instructions=row.instructions,
        skills=list(row.skills or []),
        plugins=list(row.plugins or []),
        version=row.version,
    )


async def _plugin_ids(session: AsyncSession) -> set[str]:
    return set(await session.scalars(select(PluginRow.id)))


async def rows_by_id(session: AsyncSession) -> dict[str, PersonaRow]:
    return {row.id: row for row in await session.scalars(select(PersonaRow))}


async def refresh(session: AsyncSession) -> None:
    """Load the stored personas into this process (at startup and after every change)."""
    set_overrides({row.id: _to_persona(row) for row in (await rows_by_id(session)).values()})


def _check(persona: Persona, registry: SkillRegistry, plugins: set[str]) -> None:
    if not 2 <= len(persona.name.strip()) <= 60:
        raise PersonaError("the name must be 2 to 60 characters")
    text = persona.instructions.strip()
    if not MIN_INSTRUCTIONS <= len(text) <= MAX_INSTRUCTIONS:
        raise PersonaError(
            f"the instructions must be {MIN_INSTRUCTIONS} to {MAX_INSTRUCTIONS} characters"
        )
    if len(persona.skills) > MAX_SKILLS or len(set(persona.skills)) != len(persona.skills):
        raise PersonaError(f"a persona has at most {MAX_SKILLS} different skills")
    _, missing = registry.resolve(persona.skills)
    if missing:
        raise PersonaError(f"no such skill: {', '.join(missing)}")
    if len(set(persona.plugins)) != len(persona.plugins):
        raise PersonaError("a plugin can be attached once")
    if persona.plugins and persona.kind != "worker":
        raise PersonaError("plugins can only be attached to builders (workers) for now")
    unknown = [p for p in persona.plugins if p not in plugins]
    if unknown:
        raise PersonaError(f"no such plugin: {', '.join(unknown)}")


async def _record(session: AsyncSession, persona: Persona) -> None:
    exists = await session.scalar(
        select(PersonaVersion.id).where(
            PersonaVersion.persona_id == persona.id, PersonaVersion.version == persona.version
        )
    )
    if exists is None:
        session.add(
            PersonaVersion(
                persona_id=persona.id, version=persona.version, snapshot=_snapshot(persona)
            )
        )


async def edit(
    session: AsyncSession, persona_id: str, change: Edit, registry: SkillRegistry
) -> Persona:
    """Apply `change` and keep it as a new version; no change, no new version."""
    rows = await rows_by_id(session)
    current = all_personas().get(persona_id)
    if current is None:
        raise PersonaError("persona not found", 404)
    updated = current.model_copy(
        update={
            k: v
            for k, v in {
                "name": change.name.strip() if change.name is not None else None,
                "instructions": change.instructions.strip()
                if change.instructions is not None
                else None,
                "skills": change.skills,
                "plugins": change.plugins,
            }.items()
            if v is not None
        }
    )
    if _snapshot(updated) == _snapshot(current):
        return current
    _check(updated, registry, await _plugin_ids(session))
    await _record(session, current)  # the version being replaced is kept (a built-in's is v1)
    latest = await session.scalar(
        select(func.max(PersonaVersion.version)).where(PersonaVersion.persona_id == persona_id)
    )
    # Versions only go up, even after a reset to the default and a new edit.
    updated = updated.model_copy(update={"version": max(latest or 0, current.version) + 1})
    row = rows.get(persona_id)
    if row is None:
        row = PersonaRow(id=persona_id, builtin=True)
        session.add(row)
    row.name, row.kind = updated.name, updated.kind
    row.instructions, row.skills = updated.instructions, updated.skills
    row.plugins, row.version = updated.plugins, updated.version
    await _record(session, updated)
    await session.flush()
    await refresh(session)
    return updated


async def create(
    session: AsyncSession,
    *,
    persona_id: str,
    name: str,
    instructions: str,
    skills: list[str],
    registry: SkillRegistry,
) -> Persona:
    """A new custom worker persona."""
    if not _ID.match(persona_id):
        raise PersonaError("the id must be lowercase letters, digits, '-' or '_' (2 to 32)")
    if persona_id in all_personas():
        raise PersonaError(f"a persona '{persona_id}' already exists", 409)
    persona = Persona(
        id=persona_id,
        name=name.strip(),
        kind="worker",
        instructions=instructions.strip(),
        skills=skills,
        version=1,
    )
    _check(persona, registry, await _plugin_ids(session))
    session.add(
        PersonaRow(
            id=persona_id,
            name=persona.name,
            kind="worker",
            instructions=persona.instructions,
            skills=persona.skills,
            plugins=[],
            version=1,
            builtin=False,
        )
    )
    await _record(session, persona)
    await session.flush()
    await refresh(session)
    return persona


async def remove(session: AsyncSession, persona_id: str) -> str:
    """Delete a custom persona, or reset an edited built-in one to its default. Returns what
    happened: "deleted" or "reset"."""
    rows = await rows_by_id(session)
    row = rows.get(persona_id)
    if row is None:
        if persona_id in builtin_personas():
            raise PersonaError("this persona is already the default", 409)
        raise PersonaError("persona not found", 404)
    if not row.builtin:
        busy = await session.scalar(
            select(FeatureRow.id)
            .join(Mission, Mission.id == FeatureRow.mission_id)
            .where(FeatureRow.persona_id == persona_id, Mission.status.in_(ACTIVE_MISSIONS))
            .limit(1)
        )
        if busy is not None:
            raise PersonaError("a mission in progress still has work for this persona", 409)
    await session.execute(delete(PersonaRow).where(PersonaRow.id == persona_id))
    await session.flush()
    await refresh(session)
    return "reset" if row.builtin else "deleted"


async def versions(session: AsyncSession, persona_id: str) -> list[PersonaVersion]:
    """Newest first. A built-in persona nobody edited has none (it is at its default)."""
    if persona_id not in all_personas():
        raise UnknownPersona(persona_id)
    return list(
        await session.scalars(
            select(PersonaVersion)
            .where(PersonaVersion.persona_id == persona_id)
            .order_by(PersonaVersion.version.desc())
        )
    )
