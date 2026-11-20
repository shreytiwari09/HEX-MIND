"""MCP workspace server (stdio). Started by the backend once per run, bound to the run's worktree.

    python -m app.mcp_server --root <worktree> --workspace <user workspace> \
        --allowed-images node:22-alpine,python:3.11-slim --check-timeout 120
"""

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.guardrails.injection import mark
from app.mcp_server.tools import ToolError, WorkspaceTools
from app.skills.registry import SkillRegistry


def build_server(tools: WorkspaceTools) -> FastMCP:
    server = FastMCP("hexmind-workspace")

    def guarded(fn):
        def call(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ToolError as exc:
                return f"ERROR: {exc}"

        call.__name__ = fn.__name__
        call.__doc__ = fn.__doc__
        return call

    @server.tool()
    def list_files(path: str = "") -> str:
        """List workspace files (optionally under a directory), one relative path per line."""
        return guarded(tools.list_files)(path)

    @server.tool()
    def read_file(path: str) -> str:
        """Read a UTF-8 text file from the workspace."""
        text = guarded(tools.read_file)(path)
        # File contents are untrusted input; a suspicious file is labelled as data (the file
        # itself is never changed, and replace_in_file does not go through here).
        return text if text.startswith("ERROR:") else mark(text, f"file '{path}'")

    @server.tool()
    def search_code(query: str) -> str:
        """Case-insensitive text search across workspace files; returns path:line: text."""
        return guarded(tools.search_code)(query)

    @server.tool()
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file with the full new content."""
        return guarded(tools.write_file)(path, content)

    @server.tool()
    def replace_in_file(path: str, old: str, new: str) -> str:
        """Replace one exact, unique occurrence of `old` with `new` in a file."""
        return guarded(tools.replace_in_file)(path, old, new)

    @server.tool()
    def delete_file(path: str) -> str:
        """Delete one file from the workspace."""
        return guarded(tools.delete_file)(path)

    @server.tool()
    def move_file(source: str, destination: str) -> str:
        """Move or rename a file; the destination must not exist."""
        return guarded(tools.move_file)(source, destination)

    @server.tool()
    def git_status() -> str:
        """Changed and new files since the last commit (read-only)."""
        return guarded(tools.git_status)()

    @server.tool()
    def git_diff(path: str = "") -> str:
        """Uncommitted changes to tracked files, optionally for one path (read-only)."""
        return guarded(tools.git_diff)(path)

    @server.tool()
    def git_log(count: int = 10) -> str:
        """The newest commits, one `sha subject` per line (read-only)."""
        return guarded(tools.git_log)(count)

    @server.tool()
    def list_features() -> str:
        """Every feature of the mission: id | milestone | persona | status | title."""
        return guarded(tools.list_features)()

    @server.tool()
    def get_feature_context(feature_id: str = "") -> str:
        """A feature's spec, its validation criteria and earlier handoffs (default: the
        feature in progress)."""
        return guarded(tools.get_feature_context)(feature_id)

    @server.tool()
    def load_skill(name: str, file: str = "") -> str:
        """The full instructions of one of your skills (or one of its files)."""
        return guarded(tools.load_skill)(name, file)

    @server.tool()
    def list_checks() -> str:
        """List the project's checks (name: command), as defined by its run contract."""
        return guarded(tools.list_checks)()

    @server.tool()
    def run_check(name: str) -> str:
        """Run a named project check (for example `test`) in the sandbox; returns JSON."""
        return guarded(tools.run_check)(name)

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--allowed-images", required=True)
    parser.add_argument("--check-timeout", type=int, default=120)
    parser.add_argument("--writable", default="", help="exact extra paths agents may write")
    parser.add_argument("--write-only", default="", help="confine writes to these folders")
    parser.add_argument("--skills", default="", help="names of the skills the agent may load")
    parser.add_argument("--coordination", default="blackboard", choices=["blackboard", "messaging"])
    parser.add_argument("--skills-dir", default="", help="the user's skills folder")
    args = parser.parse_args()
    tools = WorkspaceTools(
        args.root,
        workspace=args.workspace,
        allowed_images=args.allowed_images.split(","),
        check_timeout_s=args.check_timeout,
        writable_extra=frozenset(p for p in args.writable.split(",") if p),
        write_only=tuple(p for p in args.write_only.split(",") if p),
        skills=SkillRegistry(Path(args.skills_dir) if args.skills_dir else None),
        allowed_skills=tuple(s for s in args.skills.split(",") if s),
        coordination=args.coordination,
    )
    build_server(tools).run("stdio")


if __name__ == "__main__":
    main()
