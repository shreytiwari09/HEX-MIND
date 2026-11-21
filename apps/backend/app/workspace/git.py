"""Git operations for safe agent edits (plan §5).

Agents never write to the user's working tree. Each run gets a worktree created from a
snapshot commit of the user's current state; the diff between that snapshot and the worktree
is what the user reviews.

All functions are blocking (plain subprocess) so they work under any asyncio event loop; call
them through a thread pool from async code.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AUTHOR = ["-c", "user.name=H.E.X Mind", "-c", "user.email=hexmind@localhost"]
# Installed dependencies and caches (node_modules, .venv, ...) live in a mission worktree after an
# `install` check, but are not part of the work: they are never committed, diffed or applied.
EXCLUDES = ["-c", f"core.excludesFile={Path(__file__).with_name('worktree_excludes.txt')}"]


class GitError(RuntimeError):
    pass


def _git(
    cwd: Path, *args: str, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:500]}")
    return result


def is_repo(root: Path) -> bool:
    result = _git(root, "rev-parse", "--show-toplevel", check=False)
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve()


def init_repo(root: Path) -> str:
    """Initialize a repository with one commit containing the current files."""
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, *AUTHOR, "commit", "-q", "--allow-empty", "-m", "Initial commit (H.E.X Mind)")
    return head(root)


def head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def has_commits(root: Path) -> bool:
    return _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def snapshot(root: Path) -> str:
    """Commit object for the user's current working state, including uncommitted and untracked
    (not ignored) files, without touching their index, working tree or branches."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if has_commits(root):
            _git(root, "read-tree", "HEAD", env=env)
        _git(root, "add", "-A", env=env)
        tree = _git(root, "write-tree", env=env).stdout.strip()
    parents = ["-p", head(root)] if has_commits(root) else []
    if parents and tree == _git(root, "rev-parse", "HEAD^{tree}").stdout.strip():
        return head(root)  # clean working tree: the snapshot is HEAD itself
    message = "H.E.X Mind snapshot"
    return _git(root, *AUTHOR, "commit-tree", tree, *parents, "-m", message).stdout.strip()


def create_worktree(root: Path, base: str, path: Path, branch: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "-b", branch, str(path), base)
    return path


def checkout_commit(root: Path, commit: str, path: Path) -> Path:
    """A temporary detached worktree at `commit` (to re-apply a mission from its commit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "--detach", str(path), commit)
    return path


def remove_worktree(root: Path, path: Path) -> None:
    _git(root, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    _git(root, "worktree", "prune", check=False)


_NO_HEX = ":(exclude).hex"


def commit_diff(worktree: Path, commit: str) -> str:
    """The unified diff a commit made, without the mission's own `.hex/` files."""
    return _git(worktree, "show", "--no-renames", "--format=", commit, "--", ".", _NO_HEX).stdout


def range_diff(worktree: Path, base: str, head: str) -> str:
    """The unified diff between two commits, without `.hex/`."""
    return _git(worktree, "diff", "--no-renames", base, head, "--", ".", _NO_HEX).stdout


def parent_of(worktree: Path, commit: str) -> str | None:
    result = _git(worktree, "rev-parse", "--verify", "-q", f"{commit}^", check=False)
    return result.stdout.strip() or None


def file_bytes(root: Path, commit: str, path: str) -> bytes | None:
    """Exact file bytes at a commit (binary-safe), or None if it does not exist there."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True, timeout=120
    )
    return result.stdout if result.returncode == 0 else None


def commit_paths(root: Path, paths: list[str], message: str) -> str:
    """Commit only `paths` on the current branch, leaving everything else the user has staged
    or changed alone. Returns the new commit."""
    _git(root, "add", "-A", "--", *paths)
    _git(root, *AUTHOR, "commit", "-q", "-m", message, "--", *paths)
    return head(root)


def commit_all(worktree: Path, message: str) -> str:
    """Commit everything in the worktree (a checkpoint) and return the new commit."""
    _git(worktree, *EXCLUDES, "add", "-A")
    _git(worktree, *AUTHOR, "commit", "-q", "--allow-empty", "-m", message)
    return head(worktree)


def is_dirty(worktree: Path) -> bool:
    return bool(_git(worktree, *EXCLUDES, "status", "--porcelain").stdout.strip())


def reset_to(worktree: Path, commit: str) -> None:
    """Discard every uncommitted change and untracked file, back to `commit`."""
    _git(worktree, "reset", "-q", "--hard", commit)
    _git(worktree, *EXCLUDES, "clean", "-fdq")


def delete_branch(root: Path, branch: str) -> None:
    """Delete a branch (its worktree must already be removed)."""
    _git(root, "branch", "-D", branch, check=False)


@dataclass(frozen=True)
class FileDiff:
    path: str
    change_type: Literal["added", "modified", "deleted"]
    diff: str


_STATUS = {"A": "added", "M": "modified", "D": "deleted", "T": "modified"}


def diff(worktree: Path, base: str) -> list[FileDiff]:
    """Changes in the worktree (committed or not, tracked or new) relative to `base`."""
    _git(worktree, *EXCLUDES, "add", "-A")
    names = _git(worktree, "diff", "--cached", "--no-renames", "--name-status", "-z", base).stdout
    fields = [f for f in names.split("\0") if f]
    changes: list[FileDiff] = []
    for status, path in zip(fields[0::2], fields[1::2], strict=True):
        text = _git(worktree, "diff", "--cached", "--no-renames", base, "--", path).stdout
        changes.append(FileDiff(path, _STATUS.get(status[0], "modified"), text))  # type: ignore[arg-type]
    return changes


def diff_commits(root: Path, base: str, commit: str) -> list[FileDiff]:
    """Changes between two commits (an applied mission once its worktree is gone)."""
    names = _git(root, "diff", "--no-renames", "--name-status", "-z", base, commit).stdout
    fields = [f for f in names.split("\0") if f]
    changes: list[FileDiff] = []
    for status, path in zip(fields[0::2], fields[1::2], strict=True):
        text = _git(root, "diff", "--no-renames", base, commit, "--", path).stdout
        changes.append(FileDiff(path, _STATUS.get(status[0], "modified"), text))  # type: ignore[arg-type]
    return changes


def show_file(root: Path, commit: str, path: str) -> str | None:
    """File contents at a commit, or None if it does not exist there."""
    result = _git(root, "show", f"{commit}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None


def status_lines(worktree: Path) -> list[str]:
    """`git status --porcelain` for the worktree, without the mission's own `.hex/` files and
    without installed dependencies."""
    out = _git(worktree, *EXCLUDES, "status", "--porcelain", "--", ".", _NO_HEX).stdout
    return [line for line in out.splitlines() if line.strip()]


def working_diff(worktree: Path, path: str = "") -> str:
    """Uncommitted changes to tracked files against HEAD (what this feature changed so far),
    optionally for one path. New files are listed by `status_lines`, not shown here."""
    spec = [path] if path else ["."]
    return _git(worktree, *EXCLUDES, "diff", "HEAD", "--no-renames", "--", *spec, _NO_HEX).stdout


def log_lines(worktree: Path, count: int) -> list[str]:
    """The newest `count` commits as `<sha> <subject>`, no authors or dates."""
    result = _git(worktree, "log", f"-n{count}", "--format=%h %s", check=False)
    if result.returncode != 0 and "not a git repository" in result.stderr:
        raise GitError(result.stderr.strip()[:300])
    return result.stdout.splitlines()  # empty for a repository with no commits yet
