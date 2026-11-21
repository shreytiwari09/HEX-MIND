"""Run a built project so the user can open it in a browser (PRD D71).

The project's own run contract says how: `install` (optional), `start` and `port`. The app runs in
a sandbox container with the usual hardening (no capabilities, non-root, read-only root, limits),
the project folder mounted at /work, and **internet allowed** (the user's choice, like apps built
with Claude). Its port is published on 127.0.0.1 only: reachable from this computer's browser,
never from the network. No API key or other secret is passed in. One app per project at a time.

The link is given only once the app answers on that port, so a link is never shown for an app
that is not running.
"""

import asyncio
import socket
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

from app.preview.guess import NotAWebApp, guess_contract, not_a_web_app_message
from app.sandbox.contract import load_contract
from app.sandbox.image import DockerfileError, ensure_project_image
from app.sandbox.runner import docker_available, ensure_image, hardening_flags

LABEL = "hexmind.app=1"
NAME_PREFIX = "hexmind-app-"
START_TIMEOUT_S = 240  # installs (npm, pip) run first
LOG_TAIL_LINES = 120

Status = Literal["starting", "running", "failed", "stopped"]
Run = Callable[..., subprocess.CompletedProcess]


class AppError(ValueError):
    """The app cannot be started; the message says why in plain words."""


@dataclass
class RunningApp:
    project_id: str
    folder: str
    container: str
    port: int
    host_port: int
    url: str
    status: Status = "starting"
    error: str | None = None
    started_at: float = field(default_factory=time.time)


def free_port(preferred: int | None) -> int:
    """The app's own port on this computer when it is free, otherwise any free port."""
    for candidate in ([preferred] if preferred else []) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise AppError("no free port on this computer")


def app_command(
    *, image: str, folder: Path, container: str, script: str, port: int, host_port: int
) -> list[str]:
    """`docker run -d` for the app. Internet allowed (bridge network); the port only on
    127.0.0.1; a bigger /tmp than checks get, because installs cache there."""
    return [
        "docker", "run", "-d",
        "--name", container,
        "--label", LABEL,
        "--network", "bridge",
        "--publish", f"127.0.0.1:{host_port}:{port}",
        *hardening_flags(memory="1g", pids="256", tmp_size="1g"),
        "--env", f"PORT={port}",
        "--env", "HOST=0.0.0.0",
        "--mount", f"type=bind,source={folder.resolve()},target=/work",
        "--workdir", "/work",
        image,
        "sh", "-c", script,
    ]  # fmt: skip


def start_script(install: str | None, start: str) -> str:
    return f"{install} && {start}" if install else start


class AppRunner:
    """The apps the user started, one per project. Docker is reached through `run` (a
    subprocess.run stand-in in tests) and the health check through `http`."""

    def __init__(
        self,
        allowed_images: list[str],
        *,
        run: Run = subprocess.run,
        http_factory: Callable[[], httpx.AsyncClient] | None = None,
        start_timeout_s: float = START_TIMEOUT_S,
        poll_s: float = 1.0,
    ) -> None:
        self._images = allowed_images
        self._run = run
        self._http = http_factory or (lambda: httpx.AsyncClient(timeout=3.0))
        self._timeout = start_timeout_s
        self._poll = poll_s
        self._apps: dict[str, RunningApp] = {}

    @property
    def images(self) -> list[str]:
        """The sandbox images apps (and the project terminal) may use."""
        return list(self._images)

    def get(self, project_id: str) -> RunningApp | None:
        return self._apps.get(project_id)

    def prepare(self, project_id: str, folder: Path) -> tuple[list[str], RunningApp]:
        """Check the project can be run and build the command. Raises AppError."""
        try:
            contract = load_contract(folder)
        except ValueError as exc:
            raise AppError(str(exc)) from None
        if contract is None or not contract.port:
            # no run contract, or one for a program without a port: work it out from the files
            try:
                contract = guess_contract(folder)
            except NotAWebApp as exc:
                start = contract.start if contract is not None else None
                raise AppError(
                    not_a_web_app_message(folder, start) if start else str(exc)
                ) from None
        if not contract.start or not contract.port:
            raise AppError(not_a_web_app_message(folder))
        available, reason = docker_available()
        if not available:
            raise AppError(f"the sandbox (Docker) is not available: {reason}")
        if contract.dockerfile:
            try:
                image = ensure_project_image(folder, self._images).tag
            except DockerfileError as exc:
                raise AppError(f"the project image could not be built: {exc}") from None
        else:
            image = contract.image or "node:22-alpine"
            if image not in self._images:
                raise AppError(f"image '{image}' is not allowed")
            ensure_image(image)
        host_port = free_port(contract.port)
        container = f"{NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        path = (contract.healthcheck or "/").strip() or "/"
        url = f"http://localhost:{host_port}"
        app = RunningApp(
            project_id=project_id,
            folder=str(folder),
            container=container,
            port=contract.port,
            host_port=host_port,
            url=url if path == "/" else url + path,
        )
        command = app_command(
            image=image,
            folder=folder,
            container=container,
            script=start_script(contract.install, contract.start),
            port=contract.port,
            host_port=host_port,
        )
        return command, app

    async def start(self, project_id: str, folder: Path) -> RunningApp:
        """Stop this project's app if one runs, start the new one, and wait until it answers."""
        await self.stop(project_id)
        command, app = await asyncio.to_thread(self.prepare, project_id, folder)
        result = await asyncio.to_thread(
            self._run, command, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[-400:]
            raise AppError(f"docker could not start the app: {detail}")
        self._apps[project_id] = app
        await self._wait(app)
        return app

    async def _wait(self, app: RunningApp) -> None:
        deadline = time.monotonic() + self._timeout
        probe = f"http://127.0.0.1:{app.host_port}/"
        async with self._http() as client:
            while time.monotonic() < deadline:
                if not await asyncio.to_thread(self._running, app.container):
                    app.status, app.error = "failed", "the app stopped while starting"
                    return
                try:
                    response = await client.get(probe)
                    if response.status_code < 500:
                        app.status = "running"
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(self._poll)
        app.status = "failed"
        app.error = f"the app did not answer on port {app.port} within {int(self._timeout)} s"

    def _running(self, container: str) -> bool:
        result = self._run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True, text=True, timeout=30,
        )  # fmt: skip
        return result.returncode == 0 and result.stdout.strip() == "true"

    def logs(self, project_id: str) -> str:
        app = self._apps.get(project_id)
        if app is None:
            return ""
        result = self._run(
            ["docker", "logs", "--tail", str(LOG_TAIL_LINES), app.container],
            capture_output=True, text=True, timeout=30,
        )  # fmt: skip
        return ((result.stdout or "") + (result.stderr or ""))[-8000:]

    async def stop(self, project_id: str) -> bool:
        app = self._apps.pop(project_id, None)
        if app is None:
            return False
        await asyncio.to_thread(
            self._run, ["docker", "rm", "-f", app.container], capture_output=True, timeout=60
        )
        app.status = "stopped"
        return True

    async def stop_all(self) -> None:
        for project_id in list(self._apps):
            await self.stop(project_id)
