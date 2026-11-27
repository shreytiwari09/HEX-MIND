"""The orchestrator side of A2A: calling the CrewAI crews with the `a2a-sdk` client (A2A is an
open protocol; no agent framework is needed on this side), and running the crew service process
in development.
"""

import asyncio
import logging
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from a2a.client import A2ACardResolver, A2AClientTimeoutError, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, Task, TextPart

from app.a2a.protocol import (
    ROLES,
    CrewRequest,
    CrewRole,
    agent_name,
    card_path,
    current_trace_id,
    request_metadata,
)
from app.config import Settings
from app.events.log import EventType
from app.telemetry.hub import TelemetryHub

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]


class CrewCallFailed(RuntimeError):
    pass


class CrewCallTimedOut(CrewCallFailed):
    """No answer within the timeout. The work may still be running on the crew service."""


def _timed_out(exc: BaseException | None) -> bool:
    while exc is not None:
        if isinstance(exc, (httpx.TimeoutException, TimeoutError, A2AClientTimeoutError)):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def a2a_http_client(settings: Settings, **kwargs: Any) -> httpx.AsyncClient:
    """HTTP client for the crew service; tests pass an ASGI transport."""
    return httpx.AsyncClient(
        base_url=settings.crew_service_url,
        headers={"Authorization": f"Bearer {settings.api_token}"},
        timeout=settings.a2a_timeout_s,
        **kwargs,
    )


async def _send(
    role: CrewRole,
    *,
    settings: Settings,
    http: httpx.AsyncClient,
    request: CrewRequest,
    prompt: str,
) -> tuple[str, Task | None, str | None]:
    """One A2A `message/send` to a crew: read its Agent Card, send `prompt` with the request
    metadata (run/task/worktree and trace context), and wait for the finished task.
    Returns the result text, the A2A task and any error text."""
    card = await A2ACardResolver(
        httpx_client=http,
        base_url=settings.crew_service_url.rstrip("/"),
        agent_card_path=card_path(role),
    ).get_agent_card()
    client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)
    message = Message(
        role=Role.user, message_id=uuid.uuid4().hex, parts=[Part(root=TextPart(text=prompt))]
    )
    task: Task | None = None
    async for event in client.send_message(message, request_metadata=request_metadata(request)):
        if isinstance(event, tuple) and isinstance(event[0], Task):
            task = event[0]
        elif isinstance(event, Message):  # a direct reply without a task
            return _text(event.parts), None, None
    if task is None:
        return "", None, "no task in the reply"
    text = "\n".join(_text(a.parts) for a in task.artifacts or []).strip()
    error = _text(task.status.message.parts) if task.status.message else None
    return text, task, error


def _text(parts: list[Part]) -> str:
    return "\n".join(p.root.text for p in parts if isinstance(p.root, TextPart)).strip()


async def call_crew(
    role: CrewRole,
    *,
    hub: TelemetryHub,
    http: httpx.AsyncClient,
    settings: Settings,
    prompt: str,
    request: CrewRequest,
    parent: str,
) -> str:
    """Send `prompt` to a crew over A2A and return its result text. Both ends of the exchange
    are recorded as `a2a_message` events joined by `exchange_id`."""
    name = agent_name(role)

    async def note(direction: str, state: str | None, **extra: Any) -> None:
        await hub.record(
            EventType.A2A_MESSAGE,
            task_id=request.task_id,
            agent_id=name,
            direction=direction,
            side="client",
            agent="orchestrator",
            peer=name,
            exchange_id=str(request.exchange_id),
            task_state=state,
            **extra,
        )

    async def agent_event(type: EventType, **extra: Any) -> None:
        await hub.record(
            type, task_id=request.task_id, agent_id=name, agent=name, framework="langgraph", **extra
        )

    started = time.monotonic()
    await agent_event(EventType.AGENT_STARTED, kind="remote_a2a", parent=parent)
    await note("sent", None, trace_id=current_trace_id(), summary=prompt[:200])
    try:
        text, task, error = await _send(
            role, settings=settings, http=http, request=request, prompt=prompt
        )
    except Exception as exc:
        duration = int((time.monotonic() - started) * 1000)
        await note("received", "failed", summary=f"{type(exc).__name__}: {exc}"[:300])
        await agent_event(EventType.AGENT_FINISHED, ok=False, duration_ms=duration)
        if _timed_out(exc):
            raise CrewCallTimedOut(f"{name} did not answer in time: {exc}"[:500]) from exc
        raise CrewCallFailed(f"{name} A2A call failed: {exc}") from exc
    duration = int((time.monotonic() - started) * 1000)
    state = task.status.state.value if task is not None else ("failed" if error else "completed")
    if state == "completed" and not text:
        state, error = "failed", "empty reply"
    await note(
        "received",
        state,
        a2a_task_id=task.id if task is not None else None,
        context_id=task.context_id if task is not None else None,
        duration_ms=duration,
        summary=(error or text or "(empty reply)")[:300],
    )
    await agent_event(EventType.AGENT_FINISHED, ok=state == "completed", duration_ms=duration)
    if state != "completed":
        raise CrewCallFailed(f"{name} A2A task {state}: {error or text or 'no result'}"[:500])
    return text


async def call_crew_with_resend(*, resends: int, **kwargs: Any) -> str:
    """`call_crew`, sending the same request again when it times out (messaging coordination,
    PRD §9.8). The request keeps its `exchange_id`, which is the idempotency key: the crew
    service answers a repeat from the work already done or still in flight, so a resend never
    does the work twice."""
    for attempt in range(resends + 1):
        try:
            return await call_crew(**kwargs)
        except CrewCallTimedOut:
            if attempt == resends:
                raise
            logger.warning("no answer from the crew; sending the request again (%s)", attempt + 1)
    raise AssertionError("unreachable")


async def agent_cards(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """The crews' Agent Cards as served (for the A2A explorer)."""
    cards = []
    for role in ROLES:
        try:
            response = await http.get(card_path(role))
            response.raise_for_status()
            cards.append({"role": role, "reachable": True, "card": response.json()})
        except httpx.HTTPError as exc:
            cards.append({"role": role, "reachable": False, "error": str(exc), "card": None})
    return cards


class CrewServiceProcess:
    """Starts `python -m app.a2a` next to the backend in development (plan §11 runs it as its
    own Cloud Run service instead)."""

    def __init__(self, settings: Settings, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self.settings = settings
        self._popen = popen
        self.process: Any = None

    async def start(self, http: httpx.AsyncClient, timeout_s: float = 60) -> bool:
        if await self._ready(http):
            logger.info("crew service already running at %s", self.settings.crew_service_url)
            return True
        self.process = self._popen([sys.executable, "-m", "app.a2a"], cwd=BACKEND_DIR)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                logger.error("crew service exited with code %s", self.process.returncode)
                return False
            if await self._ready(http):
                return True
            await asyncio.sleep(0.5)
        logger.error("crew service did not become ready in %ss", timeout_s)
        return False

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    async def _ready(self, http: httpx.AsyncClient) -> bool:
        try:
            return (await http.get(card_path("planner"), timeout=2)).status_code == 200
        except httpx.HTTPError:
            return False
