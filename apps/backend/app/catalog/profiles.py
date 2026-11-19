"""Curated model profiles from `model_profiles.yaml` (PRD §10.3, §10.8)."""

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PROFILES_FILE = Path(__file__).with_name("model_profiles.yaml")
EditFormat = Literal["search_replace", "fenced", "whole_file"]


class Tiers(BaseModel):
    reasoning: int = Field(ge=1, le=5)
    coding: int = Field(ge=1, le=5)
    ui: int = Field(ge=1, le=5)
    tool_use: int = Field(ge=1, le=5)


class ModelProfile(BaseModel):
    match: str
    tiers: Tiers
    edit_format: EditFormat = "search_replace"
    quirks: list[str] = []


class ProfileBook(BaseModel):
    last_reviewed: str
    evidence: str
    profiles: list[ModelProfile]

    def find(self, model_id: str) -> ModelProfile | None:
        lowered = model_id.lower()
        names = {lowered, lowered.rsplit("/", 1)[-1].removeprefix("models/")}
        for profile in self.profiles:
            if any(fnmatchcase(name, profile.match) for name in names):
                return profile
        return None


@lru_cache(maxsize=1)
def load_profiles(path: Path = PROFILES_FILE) -> ProfileBook:
    return ProfileBook.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
