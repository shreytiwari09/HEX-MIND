"""Publish a project to GitHub with the user's own GitHub CLI login (PRD D84).

H.E.X never sees a GitHub token: it runs `gh`, which the user signed in to themselves
(`gh auth login`). Nothing is published unless the user asked for this repository name and
visibility, and the checks GitHub itself would trip over pass first: no tracked secret files or
keys, no file over GitHub's 100 MB limit, and no existing `origin` remote to overwrite.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.context.redact import find_secrets, is_secret_file

NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
GITHUB_FILE_LIMIT = 100 * 1024 * 1024
_KEY_KINDS = {"a provider API key", "a GitHub token", "an AWS access key", "a private key"}
_TEXT_LIMIT = 2_000_000


class PublishError(ValueError):
    """Publishing cannot go ahead; the message says why and what to do, in plain words."""


@dataclass(frozen=True)
class GhStatus:
    installed: bool
    logged_in: bool
    account: str | None


def _run(
    args: list[str], cwd: Path | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def gh_status() -> GhStatus:
    if shutil.which("gh") is None:
        return GhStatus(False, False, None)
    result = _run(["gh", "auth", "status", "--hostname", "github.com"])
    text = result.stdout + result.stderr
    account = re.search(r"account (\S+)", text)
    return GhStatus(True, result.returncode == 0, account.group(1) if account else None)


def tracked_files(root: Path) -> list[str]:
    result = _run(["git", "ls-files", "-z"], cwd=root)
    if result.returncode != 0:
        raise PublishError("this folder is not a Git repository yet: initialize Git first")
    return [p for p in result.stdout.split("\0") if p]


def problems(root: Path) -> list[str]:
    """What would make publishing unsafe or fail, as plain sentences (never a secret's value)."""
    found: list[str] = []
    for rel in tracked_files(root):
        path = root / rel
        name = Path(rel).name
        if is_secret_file(rel) and name != ".env.example":
            found.append(
                f"{rel} looks like a secrets file: remove it from git "
                f"(git rm --cached {rel}) and list it in .gitignore"
            )
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > GITHUB_FILE_LIMIT:
            found.append(f"{rel} is {size // (1024 * 1024)} MB; GitHub refuses files over 100 MB")
            continue
        if size > _TEXT_LIMIT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        kinds = [k for k in find_secrets(text) if k in _KEY_KINDS]
        if kinds:
            found.append(
                f"{rel} seems to contain {', '.join(kinds)}: "
                "move it to .env and read it from the environment"
            )
    return found


def existing_remote(root: Path) -> str | None:
    result = _run(["git", "remote", "get-url", "origin"], cwd=root)
    return result.stdout.strip() or None if result.returncode == 0 else None


def publish(root: Path, name: str, *, private: bool = True) -> str:
    """Create the GitHub repository and push. Returns its URL. Raises PublishError."""
    if not NAME.match(name):
        raise PublishError(
            "use letters, numbers, dots, dashes or underscores for the repository name"
        )
    status = gh_status()
    if not status.installed:
        raise PublishError(
            "the GitHub CLI is not installed: get it from https://cli.github.com, "
            "then run `gh auth login`"
        )
    if not status.logged_in:
        raise PublishError(
            "the GitHub CLI is not signed in: run `gh auth login` in a terminal, then try again"
        )
    if remote := existing_remote(root):
        raise PublishError(
            f"this project already has a GitHub remote ({remote}); push with `git push`"
        )
    if found := problems(root):
        raise PublishError("fix these first: " + "; ".join(found[:5]))
    result = _run(
        ["gh", "repo", "create", name, "--private" if private else "--public",
         f"--source={root}", "--remote=origin", "--push"],
        cwd=root, timeout=300,
    )  # fmt: skip
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise PublishError(f"GitHub refused: {detail[-1] if detail else 'no reason given'}")
    url = re.search(r"https://github\.com/\S+", result.stdout + result.stderr)
    return url.group(0).rstrip(".") if url else (existing_remote(root) or "")
