"""Applying a mission to the user's project, and undoing it (PRD §8.8).

Nothing here runs until the user explicitly applies: agents only ever change the mission
worktree. Apply compares the worktree with the snapshot the mission started from, refuses if the
user changed any of those files since (stale check), writes the files through the workspace path
guard, and optionally records the result as a commit on the user's current branch. Revert
restores the files from a snapshot of the user's project taken just before Apply, and refuses if
the user has edited them since.

All functions are blocking (files and git); call them through a thread pool.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.workspace import git
from app.workspace.files import content_hash
from app.workspace.paths import resolve_in_workspace

# The team's working notes (plan, handoffs, validator reports). The run contract in
# .hex/project.json is always applied: "run it" and the next mission need it (D83).
MISSION_FILES_PREFIX = ".hex/mission/"


class Refused(Exception):
    """An operation the user's project state does not allow; `detail` is shown to the user."""

    def __init__(self, detail: str | dict[str, Any], status_code: int = 409) -> None:
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class Change:
    path: str
    change_type: str  # added | modified | deleted
    target: bytes | None  # the content to write; None for a deletion


def collect_changes(worktree: Path, base: str, *, include_mission_files: bool) -> list[Change]:
    """Everything the mission changed relative to its starting snapshot."""
    changes = []
    for diff in git.diff(worktree, base):
        if diff.path.startswith(MISSION_FILES_PREFIX) and not include_mission_files:
            continue
        target = None
        if diff.change_type != "deleted":
            source = resolve_in_workspace(worktree, diff.path)
            if source.is_symlink() or not source.is_file():
                # A link could point anywhere on the machine; never copy through one.
                raise Refused(f"{diff.path} is not a regular file, so it cannot be applied", 422)
            target = source.read_bytes()
        changes.append(Change(diff.path, diff.change_type, target))
    return changes


def stale_paths(workspace: Path, base: str, changes: list[Change]) -> list[str]:
    """Files the user changed since the snapshot (and that differ from what we would write)."""
    stale = []
    for change in changes:
        destination = resolve_in_workspace(workspace, change.path, for_write=True)
        if destination.exists() and not destination.is_file():
            stale.append(change.path)
            continue
        current = destination.read_bytes() if destination.is_file() else None
        if current == change.target:
            continue  # already in place
        if current != git.file_bytes(workspace, base, change.path):
            stale.append(change.path)
    return stale


def _write(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".hexmind-tmp")
    temporary.write_bytes(data)  # bytes: no newline translation
    os.replace(temporary, destination)


def _remove(workspace: Path, destination: Path) -> None:
    """Delete a file and any directories that were left empty, never the workspace itself."""
    destination.unlink(missing_ok=True)
    root = workspace.resolve()
    parent = destination.parent
    while parent != root and parent.is_relative_to(root) and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def _restore(workspace: Path, commit: str, paths: list[str]) -> None:
    """Put each path back to its content at `commit` (deleting files that did not exist)."""
    for path in paths:
        destination = resolve_in_workspace(workspace, path, for_write=True)
        data = git.file_bytes(workspace, commit, path)
        if data is None:
            _remove(workspace, destination)
        else:
            _write(destination, data)


def _hash_of(workspace: Path, path: str) -> str | None:
    destination = resolve_in_workspace(workspace, path, for_write=True)
    return content_hash(destination.read_bytes()) if destination.is_file() else None


def apply_changes(
    workspace: Path,
    worktree: Path,
    base: str,
    *,
    include_mission_files: bool,
    commit: bool,
    message: str,
) -> dict[str, Any]:
    """Write the mission's changes into the workspace. Returns the apply record."""
    changes = collect_changes(worktree, base, include_mission_files=include_mission_files)
    if not changes:
        raise Refused("the mission changed no files, so there is nothing to apply")
    stale = stale_paths(workspace, base, changes)
    if stale:
        raise Refused(
            {
                "message": "these files changed in your project since the mission started; "
                "nothing was applied",
                "paths": stale,
            }
        )

    before = git.snapshot(workspace)  # the user's exact state, uncommitted work included
    written: list[str] = []
    try:
        for change in changes:
            destination = resolve_in_workspace(workspace, change.path, for_write=True)
            if change.target is None:
                _remove(workspace, destination)
            else:
                _write(destination, change.target)
            written.append(change.path)
    except OSError as exc:
        _restore(workspace, before, written)
        raise Refused(f"could not write {change.path}: {exc}", 500) from exc

    record: dict[str, Any] = {
        "state": "applied",
        "pre_apply_commit": before,
        "commit": None,
        "commit_error": None,
        "include_mission_files": include_mission_files,
        "files": [
            {
                "path": c.path,
                "change_type": c.change_type,
                "hash": content_hash(c.target) if c.target is not None else None,
            }
            for c in changes
        ],
    }
    if commit and git.has_commits(workspace):
        try:
            record["commit"] = git.commit_paths(workspace, [c.path for c in changes], message)
        except git.GitError as exc:  # e.g. a failing hook: the files are applied, uncommitted
            record["commit_error"] = str(exc)
    return record


def revert_changes(workspace: Path, record: dict[str, Any], *, message: str) -> dict[str, Any]:
    """Undo an apply: restore the files from the pre-apply snapshot, unless the user has edited
    them since. Returns the updated record."""
    files = record["files"]
    edited = [f["path"] for f in files if _hash_of(workspace, f["path"]) != f["hash"]]
    if edited:
        raise Refused(
            {
                "message": "these files were edited since the mission was applied; "
                "nothing was reverted",
                "paths": edited,
            }
        )
    paths = [f["path"] for f in files]
    _restore(workspace, record["pre_apply_commit"], paths)
    revert_commit = None
    if record.get("commit") and git.has_commits(workspace):
        try:
            revert_commit = git.commit_paths(workspace, paths, message)
        except git.GitError as exc:
            record = {**record, "commit_error": str(exc)}
    return {**record, "state": "reverted", "revert_commit": revert_commit}
