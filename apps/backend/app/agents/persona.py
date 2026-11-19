"""Personas: the dev team as data (PRD §7, §11.1).

A persona is a profile, not code. Every job builds a fresh agent from one persona (see
`agents.build.build_agent`); personas share the same worker or validator code underneath.

Built-in personas are YAML files in `agents/personas/`. A user can edit a built-in persona or
create a custom one (stored in Postgres, every edit a new version, see `agents/store.py`); the
stored ones overlay the built-in ones in this process (`set_overrides`). The crew service does not
read the database: each job it gets carries a snapshot of its persona. `model` is the persona's
model assignment (resolved in P4 from `model_assignments`). `skills` are names the skill registry
resolves (`skills/registry.py`); `plugins` are for the plugin manager.
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


_overrides: dict[str, Persona] = {}


def set_overrides(personas: dict[str, Persona]) -> None:
    """The user's edited and custom personas, from the database (set at startup and after every
    change). They take precedence over the built-in ones with the same id."""
    global _overrides
    _overrides = dict(personas)


def all_personas() -> dict[str, Persona]:
    """Every persona now: the built-in ones, with the user's edits and custom ones on top."""
    return {**builtin_personas(), **_overrides}


def get_persona(persona_id: str) -> Persona:
    try:
        return all_personas()[persona_id]
    except KeyError:
        raise UnknownPersona(persona_id) from None
