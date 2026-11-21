"""Opening the computer's terminal inside a project's sandbox (PRD D79)."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.chat.service import app_command
from app.preview import terminal
from app.sandbox.runner import docker_available

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


def calculator(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"scripts": {"start": "node index.js"}}))
    (root / "index.js").write_text("console.log(1)\n")
    return root


def test_the_shell_runs_in_a_hardened_sandbox_with_only_the_project_folder(tmp_path: Path) -> None:
    argv = terminal.docker_shell(tmp_path, "node:22-alpine", "hexmind-term-x")

    assert argv[:4] == ["docker", "run", "-it", "--rm"]
    for flag in ("--read-only", "--cap-drop", "--user", "--memory", "--pids-limit"):
        assert flag in argv
    mounts = [argv[i + 1] for i, part in enumerate(argv) if part == "--mount"]
    assert mounts == [f"type=bind,source={tmp_path.resolve()},target=/work"]
    assert not any("KEY" in part or "TOKEN" in part for part in argv)  # no secrets passed
    assert argv[-2:] == ["node:22-alpine", "sh"]


def test_a_command_line_project_says_how_to_run_it(tmp_path: Path) -> None:
    image, steps = terminal.tips(calculator(tmp_path))

    assert image == "node:22-alpine" and steps == ["node index.js <arguments>"]
    script = terminal.shell_script(tmp_path, image, steps)
    assert script.startswith("#!/bin/sh") and "exec docker run -it" in script
    assert "node index.js <arguments>" in script


def test_a_web_app_suggests_its_install_and_start(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import streamlit as st\n")

    image, steps = terminal.tips(tmp_path)

    assert image == "python:3.11-slim" and "streamlit run app.py" in steps[-1]


@pytest.mark.parametrize(
    ("platform", "first"),
    [("darwin", "osascript"), ("win32", "cmd"), ("linux", "x-terminal-emulator")],
)
def test_each_system_opens_its_own_terminal(platform: str, first: str) -> None:
    argv = terminal.terminal_argv(Path("/tmp/hexmind-terminal/a.sh"), platform)

    assert argv[0] == first and any("a.sh" in part for part in argv)


@pytest.mark.parametrize(
    ("message", "command"),
    [("open terminal", "terminal"), ("Open a terminal", "terminal"),
     ("please open the shell", "terminal"), ("open it", "run"),
     ("open the terminal and run the tests", None)],
)  # fmt: skip
def test_open_terminal_is_a_chat_command(message: str, command: str | None) -> None:
    assert app_command(message) == command


@needs_docker
async def test_open_terminal_in_chat_opens_it_with_no_model_call(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[list[str]] = []
    real = terminal.open_terminal
    monkeypatch.setattr(
        terminal, "open_terminal",
        lambda folder, images: real(folder, images, launch=opened.append, platform="darwin"),
    )  # fmt: skip
    folder = calculator(tmp_path / "calc")
    proj = (await client.post("/api/projects", json={"workspace_path": str(folder)})).json()
    chat = (await client.post(f"/api/projects/{proj['id']}/conversations", json={})).json()

    reply = (
        await client.post(
            f"/api/conversations/{chat['id']}/messages",
            json={"content": "open terminal", "mode": "auto"},
        )
    ).json()["assistant_message"]

    assert reply["metadata"] == {"kind": "app", "status": "terminal"}
    assert "Opened a terminal" in reply["content"] and "node index.js" in reply["content"]
    assert len(opened) == 1 and opened[0][0] == "osascript"
