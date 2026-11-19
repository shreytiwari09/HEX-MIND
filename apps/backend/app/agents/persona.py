"""Personas: the dev team as data (PRD §7, §11.1).

A persona is a profile, not code. Every job builds a fresh agent from one persona (see
`agents.build.build_agent`); personas share the same worker or validator code underneath.

Built-in personas are YAML files in `agents/personas/`. User-created personas (stored in
Postgres, versioned) arrive in P6. `model` is the persona's model assignment; resolving it to a
real connection and model is P4, so until then every call goes through the ProviderRouter's
global provider order. `skills` and `plugins` are names that the P6 registries resolve; nothing
loads them yet.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.providers.base import Purpose

PERSONAS_DIR = Path(__file__).parent / "personas"

PersonaKind = Literal["orchestrator", "worker", "validator", "research"]

# The ProviderRouter's policy is keyed by purpose; until P4 a persona uses its kind's purpose.
PURPOSE_BY_KIND: dict[PersonaKind, Purpose] = {
    "orchestrator": "planner",
    "worker": "coder",
    "validator": "reviewer",
    "research": "planner",
}


class UnknownPersona(KeyError):
    pass


class ModelAssignment(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    primary: str | None = None  # e.g. "openrouter:google/gemini-3.5-pro" when manual
    fallback: list[str] = Field(default_factory=list)
    escalate: str | None = None


class Persona(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    name: str
    kind: PersonaKind
    model: ModelAssignment = Field(default_factory=ModelAssignment)
    skills: list[str] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)
    instructions: str = Field(min_length=20)
    budget_usd: float | None = None
    version: int = 1  # every edit creates a new version (provenance)

    @property
    def purpose(self) -> Purpose:
        return PURPOSE_BY_KIND[self.kind]


def load_persona_file(path: Path) -> Persona:
    persona = Persona.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if persona.id != path.stem:
        raise ValueError(f"{path.name}: persona id {persona.id!r} must match the file name")
    return persona


@lru_cache(maxsize=1)
def builtin_personas() -> dict[str, Persona]:
    personas = [load_persona_file(path) for path in sorted(PERSONAS_DIR.glob("*.yaml"))]
    return {persona.id: persona for persona in personas}


def get_persona(persona_id: str) -> Persona:
    try:
        return builtin_personas()[persona_id]
    except KeyError:
        raise UnknownPersona(persona_id) from None
