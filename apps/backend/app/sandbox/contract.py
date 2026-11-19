"""The run contract: `.hex/project.json` (PRD §9.6).

One machine-readable file says how to install, build, test, typecheck, lint and start a
project. Validators, the quick check, QA and the preview read their commands only from here;
nothing is hardcoded per stack, so any stack works.

The contract is written by an agent (DevOps), so it is untrusted content. It is only ever used to
pick which command runs *inside the sandbox* (no network for test and start, no host access), and
the path guard stops every other agent from rewriting it (see workspace/paths.py).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

CONTRACT_PATH = ".hex/project.json"
DOCKERFILE_PATH = ".hex/Dockerfile"
MAX_BYTES = 20_000
# The checks an agent or validator can run by name.
CHECK_NAMES = ("install", "build", "test", "typecheck", "lint", "acceptance")

NetworkMode = Literal["none", "allowlist"]


class ContractError(ValueError):
    """The contract is missing or invalid; the message says what to fix."""


class NetworkPolicy(BaseModel):
    # Installing dependencies needs the network; testing and starting do not.
    install: NetworkMode = "allowlist"
    test: Literal["none"] = "none"
    start: Literal["none"] = "none"


class RunContract(BaseModel):
    stack: str = Field(min_length=1, max_length=200)
    # A project image built from this file, or a prebuilt allow-listed image.
    dockerfile: str | None = None
    image: str | None = Field(default=None, max_length=200)
    install: str | None = None
    build: str | None = None
    test: str | None = None
    typecheck: str | None = None
    lint: str | None = None
    # Runs the acceptance tests QA writes in tests/acceptance/ (PRD §8.5).
    acceptance: str | None = None
    start: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    healthcheck: str | None = Field(default=None, max_length=200)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

    @field_validator("install", "build", "test", "typecheck", "lint", "acceptance", "start")
    @classmethod
    def _one_line_command(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text or len(text) > 500 or "\n" in text or "\r" in text or "\x00" in text:
            raise ValueError("a command must be one non-empty line of at most 500 characters")
        return text

    @field_validator("dockerfile")
    @classmethod
    def _dockerfile_is_the_known_path(cls, value: str | None) -> str | None:
        if value is not None and value != DOCKERFILE_PATH:
            raise ValueError(f"the Dockerfile must be {DOCKERFILE_PATH}")
        return value

    def checks(self) -> dict[str, str]:
        """Check name -> command, for the checks this project defines."""
        return {name: command for name in CHECK_NAMES if (command := getattr(self, name))}


def load_contract(root: Path) -> RunContract | None:
    """The contract in `root`, None if the project has none, ContractError if it is invalid."""
    path = root / CONTRACT_PATH
    if not path.is_file() or path.is_symlink():
        return None
    if path.stat().st_size > MAX_BYTES:
        raise ContractError(f"{CONTRACT_PATH} is larger than {MAX_BYTES // 1000} KB")
    try:
        return RunContract.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError) as exc:
        detail = (
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
            if isinstance(exc, ValidationError)
            else "it is not valid JSON"
        )
        raise ContractError(f"{CONTRACT_PATH} is invalid: {detail}") from None
