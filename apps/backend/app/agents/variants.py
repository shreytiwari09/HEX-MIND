"""Prompt and skill variants (PRD §11.5, §15 E5): named sets of changes to personas, so different
configurations of the same team can be run and compared.

A variant changes, per persona, its **instructions** and/or its **skills** (including turning
all of them off with an empty list). It cannot change a persona's kind, tools, plugins or
model: only what the persona is told. A mission runs under at most one variant, chosen when it is
scoped or created; the variant id is recorded on the mission, on every handoff and on every model
call, so results can be grouped by configuration afterwards.

A variant is applied on top of the persona as it is now (including the user's edits), never stored
into it.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.persona import Persona, all_personas
from app.db.models import Mission, PromptVariantRow
from app.skills.registry import SkillRegistry

_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
MAX_PERSONAS = 12
MIN_INSTRUCTIONS, MAX_INSTRUCTIONS, MAX_SKILLS = 20, 8000, 12


class VariantError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


class PersonaOverride(BaseModel):
    """What a variant changes for one persona; None leaves it as it is."""

    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS)
    skills: list[str] | None = Field(default=None, max_length=MAX_SKILLS)  # [] turns skills off


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    description: str
    personas: dict[str, PersonaOverride]


def to_variant(row: PromptVariantRow) -> Variant:
    return Variant(
        id=row.id,
        name=row.name,
        description=row.description,
        personas={k: PersonaOverride.model_validate(v) for k, v in (row.overrides or {}).items()},
    )


def apply(persona: Persona, variant: Variant | None) -> Persona:
    """`persona` as it is under `variant` (unchanged if the variant does not touch it)."""
    override = variant.personas.get(persona.id) if variant else None
    if override is None:
        return persona
    changes: dict[str, object] = {}
    if override.instructions is not None:
        changes["instructions"] = override.instructions.strip()
    if override.skills is not None:
        changes["skills"] = list(dict.fromkeys(override.skills))
    return persona.model_copy(update=changes)


def validate(
    variant_id: str, name: str, personas: dict[str, PersonaOverride], registry: SkillRegistry
) -> None:
    if not _ID.match(variant_id):
        raise VariantError("the id must be lowercase letters, digits and '-' (2 to 32)")
    if not 2 <= len(name.strip()) <= 80:
        raise VariantError("the name must be 2 to 80 characters")
    if not personas or len(personas) > MAX_PERSONAS:
        raise VariantError(f"a variant changes 1 to {MAX_PERSONAS} personas")
    known = all_personas()
    for persona_id, override in personas.items():
        if persona_id not in known:
            raise VariantError(f"no such persona: {persona_id}")
        if override.instructions is None and override.skills is None:
            raise VariantError(f"{persona_id}: change its instructions or its skills")
        if override.instructions is not None and not (
            MIN_INSTRUCTIONS <= len(override.instructions.strip()) <= MAX_INSTRUCTIONS
        ):
            raise VariantError(
                f"{persona_id}: the instructions must be {MIN_INSTRUCTIONS} to "
                f"{MAX_INSTRUCTIONS} characters"
            )
        if override.skills is not None:
            _, missing = registry.resolve(override.skills)
            if missing:
                raise VariantError(f"{persona_id}: no such skill: {', '.join(missing)}")


async def get(session: AsyncSession, variant_id: str | None) -> Variant | None:
    """The variant, None when `variant_id` is None; raises VariantError if it does not exist."""
    if variant_id is None:
        return None
    row = await session.get(PromptVariantRow, variant_id)
    if row is None:
        raise VariantError(f"no such variant: {variant_id}", 404)
    return to_variant(row)


async def all_rows(session: AsyncSession) -> list[PromptVariantRow]:
    return list(await session.scalars(select(PromptVariantRow).order_by(PromptVariantRow.id)))


async def missions_using(session: AsyncSession, variant_id: str) -> int:
    rows = await session.scalars(select(Mission.id).where(Mission.variant_id == variant_id))
    return len(list(rows))
