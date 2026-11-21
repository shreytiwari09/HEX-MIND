"""Open the computer's own terminal inside a project's sandbox (PRD D79).

The person gets a shell in the project folder to run the program themselves, by hand and
interactively (a calculator that asks for numbers, a CLI with flags). The shell runs in a sandbox
container like the app runner's: no capabilities, non-root, read-only root, limits, the project
folder at /work, internet allowed for installs (the user's choice, D71), and no API key or other
secret. Generated code never runs on the computer itself.

The terminal is the operating system's (Terminal on macOS, cmd on Windows, the desktop's terminal
on Linux); H.E.X has no terminal of its own (that needs node-pty, not approved).
"""

import shlex
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from app.preview.cli_runner import cli_plan
from app.preview.guess import NODE_IMAGE, NotAWebApp, guess_contract
from app.sandbox.contract import load_contract
from app.sandbox.image import DockerfileError, ensure_project_image
from app.sandbox.runner import docker_available, ensure_image, hardening_flags

Launch = Callable[[list[str]], object]


class TerminalError(ValueError):
    """The terminal cannot be opened; the message says why in plain words."""


def _launch(argv: list[str]) -> object:
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def tips(folder: Path) -> tuple[str, list[str]]:
    """(the image, what to try first) for this project."""
    try:
        contract = load_contract(folder)
    except ValueError:
        contract = None
    if contract is not None and contract.dockerfile:
        return "", [contract.start] if contract.start else []
    plan = cli_plan(folder)
    if plan is not None:
        found = [plan.install] if plan.install else []
        return plan.image, [*found, f"{plan.command} <arguments>"]
    try:
        guessed = contract if contract is not None and contract.port else guess_contract(folder)
    except NotAWebApp:
        return NODE_IMAGE, []
    steps = [s for s in (guessed.install, guessed.start) if s]
    return guessed.image or NODE_IMAGE, steps


def image_for(folder: Path, allowed_images: list[str]) -> tuple[str, list[str]]:
    image, steps = tips(folder)
    if not image:  # the project's own .hex/Dockerfile
        try:
            return ensure_project_image(folder, allowed_images).tag, steps
        except DockerfileError as exc:
            raise TerminalError(f"the project image could not be built: {exc}") from None
    if image not in allowed_images:
        raise TerminalError(f"image '{image}' is not allowed")
    ensure_image(image)
    return image, steps


def docker_shell(folder: Path, image: str, name: str) -> list[str]:
    return [
        "docker", "run", "-it", "--rm",
        "--name", name,
        "--network", "bridge",
        *hardening_flags(memory="1g", pids="256", tmp_size="1g"),
        "--env", "PS1=sandbox $ ",
        "--mount", f"type=bind,source={folder.resolve()},target=/work",
        "--workdir", "/work",
        image, "sh",
    ]  # fmt: skip


def shell_script(folder: Path, image: str, steps: list[str]) -> str:
    """The script the terminal runs: a short welcome, then the sandboxed shell."""
    lines = [
        f"{folder.name}: a shell inside the H.E.X sandbox (only this project folder is here).",
        *([] if not steps else ["Try:"] + [f"  {s}" for s in steps]),
        "Type exit to close.",
    ]
    echo = "\n".join(f"echo {shlex.quote(line)}" for line in lines)
    command = " ".join(
        shlex.quote(p) for p in docker_shell(folder, image, f"hexmind-term-{uuid.uuid4().hex[:12]}")
    )
    return f"#!/bin/sh\nclear\n{echo}\necho\nexec {command}\n"


def terminal_argv(script: Path, platform: str) -> list[str]:
    if platform == "darwin":
        path = str(script).replace("\\", "\\\\").replace('"', '\\"')
        return [
            "osascript",
            "-e", f'tell application "Terminal" to do script "sh \\"{path}\\""',
            "-e", 'tell application "Terminal" to activate',
        ]  # fmt: skip
    if platform == "win32":
        return ["cmd", "/c", "start", "H.E.X sandbox", "cmd", "/k", "sh", str(script)]
    return ["x-terminal-emulator", "-e", "sh", str(script)]


def open_terminal(
    folder: Path,
    allowed_images: list[str],
    *,
    launch: Launch = _launch,
    platform: str = sys.platform,
) -> list[str]:
    """Open the terminal; returns what to try first. Raises TerminalError."""
    if not folder.is_dir():
        raise TerminalError("the project folder is missing")
    available, reason = docker_available()
    if not available:
        raise TerminalError(f"the sandbox (Docker) is not available: {reason}")
    image, steps = image_for(folder, allowed_images)
    scripts = Path(tempfile.gettempdir()) / "hexmind-terminal"
    scripts.mkdir(exist_ok=True)
    script = scripts / f"{uuid.uuid4().hex}.sh"
    script.write_text(shell_script(folder, image, steps))
    try:
        launch(terminal_argv(script, platform))
    except OSError as exc:
        raise TerminalError(f"the terminal could not be opened: {exc}") from None
    return steps
