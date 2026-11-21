"""Run a command-line project from the chat and show its output (PRD D78).

A calculator that runs as `node index.js 2 + 3` has no page to open, so "run it" runs the program
in the sandbox instead and the chat shows what it printed; "run 2 + 3" passes those arguments.
The arguments are quoted one by one (never read by the shell), the program gets no input and a
time limit, and the network is off except for installing the project's own packages through the
usual allow-list proxy.
"""

import asyncio
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from app.preview.guess import NODE_IMAGE, PYTHON_IMAGE, NotAWebApp, guess_contract, terminal_command
from app.sandbox.contract import load_contract
from app.sandbox.runner import CheckOutcome, run_check

RUN_TIMEOUT_S = 60
INSTALL_RUN_TIMEOUT_S = 600
VENV = "/tmp/venv"  # inside the container: a .venv made on this computer would not run there


@dataclass(frozen=True)
class CliPlan:
    image: str
    command: str  # what the person would type, shown in the chat
    install: str | None  # run first, with registry access only


def _contract_start(root: Path) -> tuple[str | None, str | None, bool]:
    """(start, image, has a port) from .hex/project.json, when it is there and valid."""
    try:
        contract = load_contract(root)
    except ValueError:
        return None, None, False
    if contract is None:
        return None, None, False
    return contract.start, contract.image, bool(contract.port)


def cli_plan(root: Path) -> CliPlan | None:
    """How to run this project as a command-line program, or None when it is a web app (it gets
    a link instead) or nothing says how to run it."""
    start, image, has_port = _contract_start(root)
    if has_port:
        return None
    try:
        guess_contract(root)
        return None  # a web app
    except NotAWebApp:
        pass
    command = start or terminal_command(root)
    if not command:
        return None
    if command.split()[0] in ("node", "npm", "npx"):
        install = None
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            package = {}
        if isinstance(package, dict) and package.get("dependencies"):
            if not (root / "node_modules").is_dir():
                install = "npm install --no-audit --no-fund --omit=dev"
        return CliPlan(image=image or NODE_IMAGE, command=command, install=install)
    if command.split()[0] in ("python", "python3"):
        install = None
        if (root / "requirements.txt").is_file():
            install = f"python -m venv {VENV} && {VENV}/bin/pip install -q -r requirements.txt"
        return CliPlan(image=image or PYTHON_IMAGE, command=command, install=install)
    return None


def with_arguments(command: str, args: str) -> str:
    """The command with the person's arguments added, each quoted so the shell reads none of
    them (`2 * 3` stays three arguments; `; rm -rf /` is just text)."""
    try:
        parts = shlex.split(args)
    except ValueError:
        parts = args.split()
    if not parts:
        return command
    quoted = " ".join(shlex.quote(p) for p in parts)
    if command.startswith("npm start") or command.startswith("npm run "):
        return f"{command} --silent -- {quoted}"
    return f"{command} {quoted}"


def container_script(plan: CliPlan, args: str) -> str:
    command = with_arguments(plan.command, args)
    if plan.install and plan.install.startswith("python -m venv"):
        first, rest = command.split(maxsplit=1)
        if first in ("python", "python3"):
            command = f"{VENV}/bin/python {rest}"
    # no input: a program that asks a question gets end-of-input instead of hanging
    return (
        f"{plan.install} >/dev/null && {command} </dev/null"
        if plan.install
        else (f"{command} </dev/null")
    )


async def run_cli(root: Path, plan: CliPlan, args: str) -> CheckOutcome:
    return await asyncio.to_thread(
        run_check,
        name="run",
        command=container_script(plan, args),
        image=plan.image,
        worktree=root,
        timeout_s=INSTALL_RUN_TIMEOUT_S if plan.install else RUN_TIMEOUT_S,
        network="allowlist" if plan.install else "none",
    )


def cli_reply(plan: CliPlan, args: str, outcome: CheckOutcome) -> str:
    shown = with_arguments(plan.command, args)
    output = outcome.output_tail.strip() or "(it printed nothing)"
    if outcome.error:
        head = f"I ran `{shown}` in the sandbox, but {outcome.error}."
    else:
        seconds = outcome.duration_ms / 1000
        head = f"Ran `{shown}` in the sandbox (exit code {outcome.exit_code}, {seconds:.1f} s):"
    tip = (
        "This is a command-line program, so it runs here instead of in a browser. "
        "To try other input, type `run` and what you would give it, for example `run 2 + 3`."
    )
    return f"{head}\n\n```\n{output}\n```\n\n{tip}"
