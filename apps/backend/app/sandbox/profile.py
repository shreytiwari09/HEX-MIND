"""Project profile: which checks the sandbox may run for a project (plan §6, §7).

Read from `.hexmind/profile.yaml` in the **user's workspace** (never the agent worktree, which
agents could edit). Without a profile, one is detected from the project files. Agents choose a
check by name; they never supply a command line.

    image: node:22-alpine
    checks:
      test: node --test
      lint: npx eslint .
"""

import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.sandbox.contract import CONTRACT_PATH, RunContract, load_contract

PROFILE_PATH = ".hexmind/profile.yaml"
_CHECK_NAME = r"^[a-z][a-z0-9_-]{0,31}$"


class ProfileError(ValueError):
    pass


class Profile(BaseModel):
    image: str
    checks: dict[str, str] = Field(default_factory=dict)
    source: str = "detected"
    # Build the image from the project's `.hex/Dockerfile` (the contract names it); `image` is
    # then only the fallback.
    dockerfile: bool = False
    # Which checks may reach package registries through the allowlist proxy (the contract's
    # `network.install`); every other check has no network.
    network_checks: tuple[str, ...] = ()

    def network_for(self, name: str) -> Literal["none", "allowlist"]:
        return "allowlist" if name in self.network_checks else "none"

    def command(self, name: str) -> str:
        if name not in self.checks:
            raise ProfileError(
                f"unknown check '{name}'; available: {', '.join(self.checks) or 'none'}"
            )
        return self.checks[name]


class _ProfileFile(BaseModel):
    image: str
    checks: dict[str, str]


NODE_ACCEPTANCE = "node --test 'tests/acceptance/**/*.test.{js,mjs,cjs}'"
_ACCEPTANCE_DIR = "tests/acceptance"


def node_acceptance(worktree: Path, contract: RunContract) -> dict[str, str]:
    """An `acceptance` check for a contract that leaves it out, only when QA's tests exist and the
    project's own tests use Node's built-in runner, which then also runs QA's tests. Any other
    runner gets nothing: QA reports the missing check instead of running the wrong tool."""
    tests = worktree / _ACCEPTANCE_DIR
    if contract.acceptance or not tests.is_dir() or not any(tests.rglob("*.test.*")):
        return {}
    command = contract.test or ""
    if command in ("npm test", "npm t", "npm run test"):
        try:
            scripts = json.loads((worktree / "package.json").read_text(encoding="utf-8"))
            command = str(scripts.get("scripts", {}).get("test", ""))
        except (OSError, ValueError, AttributeError):
            return {}
    if command == "node --test" or command.startswith("node --test "):
        return {"acceptance": NODE_ACCEPTANCE}
    return {}


def load_profile(workspace: Path, worktree: Path, allowed_images: list[str]) -> Profile:
    """The checks a project defines, from the first of: the run contract `.hex/project.json`
    (PRD §9.6), the user's explicit `.hexmind/profile.yaml`, or what is detected from the
    worktree's files (a new project may only gain its package.json during the run)."""
    contract = load_contract(worktree)  # raises ContractError (a ValueError) when invalid
    if contract is not None:
        image = contract.image or detect_profile(worktree).image
        if image not in allowed_images:
            raise ProfileError(
                f"image '{image}' is not allowed; allowed: {', '.join(allowed_images)}"
            )
        return Profile(
            image=image,
            checks={**node_acceptance(worktree, contract), **contract.checks()},
            source=CONTRACT_PATH,
            dockerfile=contract.dockerfile is not None,
            network_checks=("install",) if contract.network.install == "allowlist" else (),
        )
    path = workspace / PROFILE_PATH
    if path.exists():
        try:
            data = _ProfileFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ProfileError(f"invalid {PROFILE_PATH}: {exc}") from exc

        bad = [name for name in data.checks if not re.match(_CHECK_NAME, name)]
        if bad:
            raise ProfileError(f"invalid check names: {', '.join(bad)}")
        profile = Profile(image=data.image, checks=data.checks, source=PROFILE_PATH)
    else:
        profile = detect_profile(worktree)
    if profile.image not in allowed_images:
        raise ProfileError(
            f"image '{profile.image}' is not allowed; allowed: {', '.join(allowed_images)}"
        )
    return profile


def detect_profile(root: Path) -> Profile:
    package = root / "package.json"
    if package.exists():
        checks = {"test": "node --test"}
        try:
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        # Only scripts that run without installed dependencies are usable offline; a project
        # that needs `npm ci` must declare its checks in a profile (dependency installs are a
        # separate, approved step).
        if isinstance(scripts.get("test"), str) and scripts["test"].startswith("node "):
            checks["test"] = "npm test --silent"
        return Profile(image="node:22-alpine", checks=checks)
    if any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        return Profile(image="python:3.11-slim", checks={"test": "python -m unittest discover -q"})
    # Empty or unknown project: default to Node (the demo stack) with the built-in test runner.
    return Profile(image="node:22-alpine", checks={"test": "node --test"})
