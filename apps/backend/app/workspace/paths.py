"""Workspace path guard: the single place that turns a client-supplied relative path into a
filesystem path. Every file operation must go through `resolve_in_workspace`.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath

# Windows device names are reserved regardless of extension (e.g. "nul.txt").
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Never writable through the editor API, even inside the workspace.
_WRITE_PROTECTED_DIRS = frozenset({".git"})
# H.E.X Mind's own files (the run contract, the mission folder). Agents can read them but not
# write them, except the exact files a persona is given (DevOps writes the run contract), because
# a worker that could rewrite the checks, the plan or the handoffs could make its own work pass.
_AGENT_READ_ONLY_TOP_DIRS = frozenset({".hex"})
# QA's acceptance tests (PRD §8.5): builders can read them but cannot edit them, so a builder
# cannot make its own work pass. Only a persona given this prefix as its sole write area (QA).
ACCEPTANCE_DIR = "tests/acceptance"
# Agents additionally may not touch the project profile (it defines which commands the
# sandbox runs), dependencies, or secrets.
_AGENT_PROTECTED_DIRS = _WRITE_PROTECTED_DIRS | {".hexmind", "node_modules"}


class PathViolation(ValueError):
    """The requested path is invalid or escapes the workspace."""


def normalize_relative(rel: str) -> PurePosixPath:
    """Validate a workspace-relative path and return it in POSIX form ("" means the root)."""
    if "\x00" in rel:
        raise PathViolation("path contains a NUL byte")
    win = PureWindowsPath(rel)
    if win.drive or win.root or rel.startswith(("/", "\\")):
        raise PathViolation("path must be relative to the workspace")

    parts: list[str] = []
    for part in rel.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathViolation("path must not contain '..'")
        if ":" in part:
            raise PathViolation("path must not contain ':' (drive or alternate data stream)")
        if part != part.rstrip(" ."):
            raise PathViolation("path segments must not end with a space or dot")
        if part.split(".")[0].upper() in _RESERVED_NAMES:
            raise PathViolation(f"'{part}' is a reserved device name")
        parts.append(part)
    return PurePosixPath(*parts)


def resolve_in_workspace(
    root: Path,
    rel: str,
    *,
    for_write: bool = False,
    agent: bool = False,
    agent_writable: frozenset[str] = frozenset(),
    agent_write_only: tuple[str, ...] = (),
) -> Path:
    """Resolve `rel` under `root`, following symlinks, and reject anything outside it.

    `agent=True` applies the stricter policy used for agent tool calls (reads and writes).
    `agent_writable` lists exact paths an agent may write inside otherwise read-only areas.
    `agent_write_only`, when set, confines an agent's writes to those folders (QA writes only
    `tests/acceptance/`); without it, `tests/acceptance/` is read-only for agents.
    """
    normalized = normalize_relative(rel)
    lowered = [part.lower() for part in normalized.parts]
    if agent:
        if any(part in _AGENT_PROTECTED_DIRS for part in lowered):
            raise PathViolation(f"'{normalized}' is not accessible to agents")
        if lowered and lowered[-1].startswith(".env"):
            raise PathViolation(f"'{normalized}' may contain secrets")
    if for_write and any(part in _WRITE_PROTECTED_DIRS for part in lowered):
        raise PathViolation(f"'{normalized}' is write-protected")
    if (
        agent
        and for_write
        and lowered[:1]
        and lowered[0] in _AGENT_READ_ONLY_TOP_DIRS
        and normalized.as_posix() not in agent_writable
    ):
        raise PathViolation(f"'{normalized}' is managed by H.E.X Mind and is read-only for agents")

    if agent and for_write:
        posix = normalized.as_posix().lower()
        in_acceptance = posix == ACCEPTANCE_DIR or posix.startswith(ACCEPTANCE_DIR + "/")
        if agent_write_only:
            allowed = any(
                posix == p.rstrip("/").lower() or posix.startswith(p.rstrip("/").lower() + "/")
                for p in agent_write_only
            )
            if not allowed:
                raise PathViolation(
                    f"'{normalized}' is outside the folders you may write: "
                    + ", ".join(agent_write_only)
                )
        elif in_acceptance:
            raise PathViolation(
                f"'{normalized}' is an acceptance test: only QA writes those, so work cannot "
                "be made to pass by editing them"
            )

    root_real = root.resolve(strict=True)
    candidate = (root_real.joinpath(*normalized.parts)).resolve(strict=False)
    if candidate != root_real and not candidate.is_relative_to(root_real):
        raise PathViolation("path resolves outside the workspace")
    return candidate


def to_relative(root: Path, path: Path) -> str:
    """POSIX-style path of `path` relative to the resolved workspace root."""
    return path.relative_to(root.resolve()).as_posix()
