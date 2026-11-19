"""Role requirements from `role_requirements.yaml` (PRD §10.4)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

REQUIREMENTS_FILE = Path(__file__).with_name("role_requirements.yaml")
Capability = Literal["reasoning", "coding", "ui", "tool_use"]


class RoleRequirement(BaseModel):
    min: dict[Capability, int] = Field(default_factory=dict)
    min_context: int = 0
    focus: list[Capability]
    critical: bool = False


class Requirements(BaseModel):
    roles: dict[str, RoleRequirement]


@lru_cache(maxsize=1)
def load_requirements(path: Path = REQUIREMENTS_FILE) -> Requirements:
    return Requirements.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
