"""Running a built project and giving a link (PRD D71)."""

import json
import socket
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import Message
from app.preview.app_runner import AppError, AppRunner, app_command, free_port, start_script
from app.sandbox.runner import docker_available

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

SERVER_JS = (
    "require('http').createServer((q, s) => s.end('hello from the calculator'))"
    ".listen(process.env.PORT || 3000, '0.0.0.0')\n"
)


def project(root: Path, **contract: object) -> Path:
    (root / ".hex").mkdir(parents=True, exist_ok=True)
    data = {"stack": "node", "image": "node:22-alpine", "test": "node --test", **contract}
    (root / ".hex" / "project.json").write_text(json.dumps(data))
    (root / "server.js").write_text(SERVER_JS)
    return root


def test_the_container_is_hardened_and_reachable_only_from_this_computer(tmp_path: Path) -> None:
    command = app_command(
        image="node:22-alpine", folder=tmp_path, container="hexmind-app-x",
        script="npm install && node server.js", port=3000, host_port=41234,
    )  # fmt: skip

    assert command[command.index("--publish") + 1] == "127.0.0.1:41234:3000"
    assert command[command.index("--network") + 1] == "bridge"  # internet allowed (D71)
    for flag in ("--read-only", "--cap-drop", "--user", "--memory", "--pids-limit"):
        assert flag in command
    assert not any("KEY" in part or "TOKEN" in part for part in command)  # no secrets passed
    assert command[-3:] == ["sh", "-c", "npm install && node server.js"]


def test_install_runs_before_start_only_when_there_is_one() -> None:
    assert start_script("npm install", "node server.js") == "npm install && node server.js"
    assert start_script(None, "node server.js") == "node server.js"


def test_a_busy_port_is_replaced_by_a_free_one() -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert free_port(taken) != taken
    assert free_port(None) > 0


@pytest.mark.parametrize(
    ("contract", "message"),
    [
        (None, "command-line program, not a web app"),
        ({"start": "node server.js"}, "terminal from the project folder: `node server.js`"),
        ({"port": 3000}, "command-line program, not a web app"),
    ],
)
def test_a_project_that_is_not_an_app_says_why(
    tmp_path: Path, contract: dict | None, message: str
) -> None:
    if contract is not None:
        project(tmp_path, **contract)

    with pytest.raises(AppError, match=message):
        AppRunner(["node:22-alpine"]).prepare("p", tmp_path)


class FakeDocker:
    """subprocess.run for docker: the container starts, then is running or has exited."""

    def __init__(self, running: bool = True) -> None:
        self.running, self.calls = running, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        out = "true" if argv[:2] == ["docker", "inspect"] and self.running else "false"
        if argv[:2] == ["docker", "logs"]:
            out = "Error: Cannot find module 'server.js'"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def runner(docker: FakeDocker, answer: int | None) -> AppRunner:
    def respond(request: httpx.Request) -> httpx.Response:
        if answer is None:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(answer)

    return AppRunner(
        ["node:22-alpine"], run=docker,
        http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        start_timeout_s=0.3, poll_s=0.05,
    )  # fmt: skip


@pytest.fixture
def no_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.preview.app_runner.docker_available", lambda: (True, None))
    monkeypatch.setattr("app.preview.app_runner.ensure_image", lambda image: None)


async def test_the_link_is_given_only_once_the_app_answers(tmp_path: Path, no_pull) -> None:
    folder = project(tmp_path, start="node server.js", port=3000, install="npm install")
    docker = FakeDocker()

    app = await runner(docker, 200).start("p", folder)

    assert app.status == "running" and app.url.startswith("http://localhost:")
    assert docker.calls[0][:3] == ["docker", "run", "-d"]


@pytest.mark.parametrize(
    ("running", "answer", "error"),
    [
        (False, None, "stopped while starting"),  # crashed
        (True, None, "did not answer on port 3000"),  # never listened
    ],
)
async def test_an_app_that_never_answers_gets_no_link(
    tmp_path: Path, no_pull, running: bool, answer: int | None, error: str
) -> None:
    folder = project(tmp_path, start="node server.js", port=3000)

    app = await runner(FakeDocker(running), answer).start("p", folder)

    assert app.status == "failed" and error in (app.error or "")


async def test_starting_again_replaces_the_running_app_and_stop_removes_it(
    tmp_path: Path, no_pull
) -> None:
    folder = project(tmp_path, start="node server.js", port=3000)
    docker = FakeDocker()
    apps = runner(docker, 200)

    first = await apps.start("p", folder)
    await apps.start("p", folder)
    assert ["docker", "rm", "-f", first.container] in docker.calls  # one app per project

    assert await apps.stop("p") is True and apps.get("p") is None
    assert await apps.stop("p") is False


@needs_docker
async def test_a_real_app_runs_and_its_link_works_and_is_posted_in_the_chat(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    folder = project(tmp_path / "calc", start="node server.js", port=3000)
    proj = (await client.post("/api/projects", json={"workspace_path": str(folder)})).json()
    chat = (await client.post(f"/api/projects/{proj['id']}/conversations", json={})).json()
    try:
        response = await client.post(
            f"/api/projects/{proj['id']}/app", json={"conversation_id": chat["id"]}
        )
        body = response.json()
        assert response.status_code == 200, body
        assert body["status"] == "running" and body["url"].startswith("http://localhost:")

        async with httpx.AsyncClient() as browser:
            page = await browser.get(body["url"].replace("localhost", "127.0.0.1"))
        assert page.text == "hello from the calculator"

        async with app.state.sessionmaker() as session:
            [posted] = list(await session.scalars(select(Message)))
        assert body["url"] in posted.content and posted.meta["kind"] == "app"
    finally:
        stopped = await client.delete(f"/api/projects/{proj['id']}/app")
    assert stopped.json()["status"] == "stopped"
    assert (await client.get(f"/api/projects/{proj['id']}/app")).json()["status"] == "none"


@pytest.mark.parametrize(
    ("message", "command"),
    [
        ("run it", "run"),
        ("Run the app", "run"),
        ("start my app!", "run"),
        ("open it", "run"),
        ("please run it", "run"),
        ("stop the app", "stop"),
        ("Stop", "stop"),
        # anything longer is a normal question or request for the PM
        ("run the tests and tell me what failed", None),
        ("how do I run it?", None),
        ("stop adding features", None),
        ("open src/calc.js", None),
    ],
)
def test_only_the_short_run_and_stop_commands_skip_the_pm(
    message: str, command: str | None
) -> None:
    from app.chat.service import app_command as chat_command

    assert chat_command(message) == command


@needs_docker
async def test_saying_run_it_in_chat_gives_the_link_without_a_model_call(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    from app.db.models import LLMCall

    folder = project(tmp_path / "calc", start="node server.js", port=3000)
    proj = (await client.post("/api/projects", json={"workspace_path": str(folder)})).json()
    chat = (await client.post(f"/api/projects/{proj['id']}/conversations", json={})).json()
    send = f"/api/conversations/{chat['id']}/messages"
    try:
        reply = (await client.post(send, json={"content": "run it", "mode": "auto"})).json()
        message = reply["assistant_message"]
        assert message["metadata"]["kind"] == "app" and message["metadata"]["status"] == "running"
        assert message["metadata"]["url"] in message["content"]
    finally:
        stop = (await client.post(send, json={"content": "stop the app", "mode": "auto"})).json()
    assert stop["assistant_message"]["content"] == "Stopped the app."
    async with app.state.sessionmaker() as session:
        assert list(await session.scalars(select(LLMCall))) == []  # no model was asked
