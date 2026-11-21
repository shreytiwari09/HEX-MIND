"""The files a builder will need, put in its first prompt.

Without this a builder starts every feature by reading its target files one tool call at a time,
and every one of those steps re-sends the whole conversation (live run: ~25 steps and ~50,000
input tokens to write one 60-line file). The same paths go through the same guards as the
`read_file` tool: inside the worktree only, never `.env*`, never H.E.X Mind's own `.hex/`
folder, and what comes back is redacted and screened for injection like any file an agent reads.
Small caps keep the prompt small; the agent can still read anything else itself.
"""

from pathlib import Path

from app.context.redact import is_secret_file, redact
from app.guardrails.injection import mark
from app.workspace.paths import PathViolation, resolve_in_workspace, to_relative

MAX_FILES = 4
MAX_FILE_CHARS = 2500
MAX_TOTAL_CHARS = 6000


def preload_files(worktree: Path, paths: list[str]) -> str:
    """`=== path ===` blocks for the first existing, readable text files in `paths` (in the order
    given, no repeats), or an empty string."""
    blocks: list[str] = []
    seen: set[str] = set()
    used = 0
    for rel in paths:
        if len(blocks) >= MAX_FILES or used >= MAX_TOTAL_CHARS:
            break
        try:
            target = resolve_in_workspace(worktree, rel, agent=True)
            name = to_relative(worktree, target)
            if name in seen or name.startswith(".hex/") or is_secret_file(name):
                continue
            if not target.is_file():
                continue
            raw = target.read_bytes()[: MAX_FILE_CHARS * 4]
            text = raw.decode("utf-8")
        except (PathViolation, OSError, UnicodeDecodeError, ValueError):
            continue  # missing, outside the worktree, not text: simply not preloaded
        seen.add(name)
        room = min(MAX_FILE_CHARS, MAX_TOTAL_CHARS - used)
        cut = len(text) > room
        text = text[:room]
        used += len(text)
        blocks.append(
            f"=== {name} ===\n{mark(redact(text), 'file')}" + ("\n[file cut]" if cut else "")
        )
    return "\n\n".join(blocks)
