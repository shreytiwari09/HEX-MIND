"""TelemetryHub: one sink for every framework callback (plan §7.1, criterion 5).

LangGraph: `handler` returns a LangChain callback handler for one graph invocation; graph and
node starts and ends, model calls and tool calls become events (node_start/node_end, model_start,
model_end, model_error, tool_start, tool_end, tool_error).
CrewAI: `crew_callbacks` returns the crew's step/task callbacks and before/after kickoff hooks.

Each callback becomes (1) a run event (`agent_started`, `agent_finished`, `callback_fired`,
`schema_validated`) and (2) attributes on the current OpenTelemetry span, so the UI's callback
stream, agent grid and schema checks are fed by the callbacks themselves. Telemetry never
changes agent behaviour: every hub callback returns None and swallows its own failures.
"""

import asyncio
import concurrent.futures
import contextlib
import logging
import threading
import time
import uuid
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from opentelemetry import context as otel_context
from opentelemetry import trace

from app.events.log import EventType, append_event
from app.orchestration.services import Services

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("hexmind")

MAX_DETAIL = 300


def _clip(text: Any) -> str:
    text = str(text)
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 1] + "…"


@dataclass
class TelemetryHub:
    services: Services
    run_id: uuid.UUID
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)
    # (task id, invocation id, agent name) -> start times of invocations still open.
    _started: dict[tuple[str, str, str], list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------- recording ----------

    async def record(
        self,
        type: EventType,
        *,
        task_id: uuid.UUID | None = None,
        agent_id: str | None = None,
        **payload: Any,
    ) -> None:
        try:
            async with self.services.sessionmaker.begin() as session:
                await append_event(
                    session, self.run_id, type, task_id=task_id, agent_id=agent_id, payload=payload
                )
        except Exception:  # monitoring must never take a run down
            logger.exception("telemetry: failed to record %s for run %s", type, self.run_id)

    def record_threadsafe(self, type: EventType, **kwargs: Any) -> None:
        """For callbacks that run on a worker thread (CrewAI runs crews in a thread)."""
        self._submit(self.record(type, **kwargs))

    def _submit(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:  # already on the server loop: do not block it
            self.loop.create_task(coro)
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)
        except Exception:
            logger.exception("telemetry: threadsafe record failed for run %s", self.run_id)

    def _start(self, key: tuple[str, str, str]) -> None:
        with self._lock:
            self._started.setdefault(key, []).append(time.monotonic())

    async def abort_open(self, *, task_id: uuid.UUID | None = None, error: str = "") -> None:
        """Agents of a failed task (or, with no task_id, of a failed run) can be left without an
        end callback (a cancelled task, a lost lease), so they would look like they are still
        running. Record them as finished with ok=False; a late end callback is then skipped."""
        with self._lock:
            keys = [
                k
                for k, v in self._started.items()
                if v and (task_id is None or k[0] == str(task_id))
            ]
            opened = {k: self._started.pop(k) for k in keys}
        now = time.monotonic()
        for (task, _, name), starts in opened.items():
            for start in starts:
                await self.record(
                    EventType.AGENT_FINISHED,
                    task_id=uuid.UUID(task) if task else None,
                    agent_id=name,
                    agent=name,
                    framework="langgraph",
                    ok=False,
                    duration_ms=int((now - start) * 1000),
                )
        if opened:
            logger.info("telemetry: closed %d agent(s) after failure: %s", len(opened), error[:200])

    def _finish(self, key: tuple[str, str, str]) -> int | None:
        """Close an open agent; its duration in ms, or None when abort_open already closed it."""
        with self._lock:
            stack = self._started.get(key)
            if not stack:
                return None
            started = stack.pop()
            if not stack:
                del self._started[key]
        return int((time.monotonic() - started) * 1000)

    # ---------- LangGraph ----------

    def handler(
        self, *, task_id: uuid.UUID | None = None, parent: str | None = None
    ) -> "HubCallbackHandler":
        """A LangChain callback handler for one graph invocation. `parent` names the agent this
        graph runs under when it is a separate invocation (a task's reflection loop runs under
        the run's `execute` step)."""
        return HubCallbackHandler(self, task_id=task_id, parent=parent)

    # ---------- CrewAI ----------

    def crew_callbacks(
        self, agent_id: str, *, parent: str, task_id: uuid.UUID | None = None
    ) -> "CrewCallbacks":
        """`parent` is the graph node the crew runs inside (e.g. `plan` or `coder`)."""
        return CrewCallbacks(self, agent_id, parent, task_id)

    @contextlib.contextmanager
    def crew_span(self, agent_id: str) -> Iterator[None]:
        with tracer.start_as_current_span(f"crewai.crew {agent_id}") as span:
            span.set_attributes(
                {
                    "hexmind.run_id": str(self.run_id),
                    "agent.name": agent_id,
                    "agent.framework": "crewai",
                    "agent.kind": "crew",
                }
            )
            yield


@dataclass
class CrewCallbacks:
    """CrewAI hooks for a single-agent crew. They run on the crew's worker thread."""

    hub: TelemetryHub
    agent_id: str
    parent: str
    task_id: uuid.UUID | None
    _started: float = 0.0

    def _fired(self, hook: str, detail: str | None) -> None:
        self.hub.record_threadsafe(
            EventType.CALLBACK_FIRED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            framework="crewai",
            hook=hook,
            agent=self.agent_id,
            detail=_clip(detail) if detail else None,
        )

    def before_kickoff(self, inputs: dict[str, Any] | None) -> dict[str, Any] | None:
        self._started = time.monotonic()
        self.hub.record_threadsafe(
            EventType.AGENT_STARTED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            agent=self.agent_id,
            framework="crewai",
            kind="crew",
            parent=self.parent,
        )
        return inputs

    def after_kickoff(self, output: Any) -> Any:
        self.hub.record_threadsafe(
            EventType.AGENT_FINISHED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            agent=self.agent_id,
            framework="crewai",
            ok=True,
            duration_ms=int((time.monotonic() - self._started) * 1000) if self._started else None,
        )
        return output

    def kickoff_failed(self, error: BaseException) -> None:
        """CrewAI runs no after-kickoff hook when the crew raises; record the failure."""
        self.hub.record_threadsafe(
            EventType.AGENT_FINISHED,
            task_id=self.task_id,
            agent_id=self.agent_id,
            agent=self.agent_id,
            framework="crewai",
            ok=False,
            duration_ms=int((time.monotonic() - self._started) * 1000) if self._started else None,
        )

    def span(self) -> contextlib.AbstractContextManager[None]:
        return self.hub.crew_span(self.agent_id)

    def step_callback(self, step: Any) -> None:
        self._fired("step_callback", describe_step(step))

    def task_callback(self, output: Any) -> None:
        raw = getattr(output, "raw", None) or str(output)
        self._fired("task_callback", f"task done: {raw}")


class HubCallbackHandler(AsyncCallbackHandler):
    """LangGraph callbacks -> run events and span attributes, the same events the UI reads.

    A graph run and each of its nodes become an agent (agent_started / agent_finished); model and
    tool calls inside a node become callback_fired events named after the node. On the hub's loop
    each record is awaited before the node goes on (writing concurrently with the node's own
    transactions can deadlock). When LangChain calls the handler from a helper
    thread with its own loop, the record is handed to the hub's loop instead, chained so events
    keep their order; `flush` waits for those. Every method swallows its own failures:
    monitoring must never change or break a run."""

    raise_error = False
    run_inline = True

    def __init__(self, hub: TelemetryHub, *, task_id: uuid.UUID | None, parent: str | None) -> None:
        self.hub = hub
        self.task_id = task_id
        self.root_parent = parent
        self._lock = threading.Lock()
        self._parents: dict[UUID, UUID | None] = {}  # every run -> its parent run
        self._agents: dict[UUID, str] = {}  # runs that are agents (graph or node) -> name
        self._tool_names: dict[UUID, str] = {}
        self._solo_roots: set[UUID] = set()  # one-node graphs: the node alone is the agent
        self._last: concurrent.futures.Future[None] | None = None
        # OpenTelemetry spans of open agents, model calls and tool calls, current while they run
        # so CrewAI crew spans and A2A trace context nest under them.
        self._spans: dict[UUID, tuple[trace.Span, object]] = {}

    # ----- ordered delivery to the hub's loop -----

    async def _deliver(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not self.hub.loop:
            self._submit(coro)
            return
        last = self._last
        if last is not None:
            try:
                await asyncio.wrap_future(last)
            except Exception:
                pass
        try:
            await coro
        except Exception:
            logger.exception("telemetry: recording a LangGraph event failed")

    def _submit(self, coro: Coroutine[Any, Any, None]) -> None:
        with self._lock:
            previous = self._last

            async def ordered() -> None:
                if previous is not None:
                    try:
                        await asyncio.wrap_future(previous)
                    except Exception:
                        pass
                try:
                    await coro
                except Exception:
                    logger.exception("telemetry: recording a LangGraph event failed")

            self._last = asyncio.run_coroutine_threadsafe(ordered(), self.hub.loop)

    async def flush(self) -> None:
        """Wait until every event handed over so far is written."""
        last = self._last
        if last is not None:
            try:
                await asyncio.wrap_future(last)
            except Exception:
                logger.exception("telemetry: flushing LangGraph events failed")

    # ----- spans -----

    def _open_span(self, run_id: UUID, name: str, **attributes: Any) -> None:
        try:
            span = tracer.start_span(
                name,
                attributes={
                    "hexmind.run_id": str(self.hub.run_id),
                    **{k: v for k, v in attributes.items() if v is not None},
                },
            )
            token = otel_context.attach(trace.set_span_in_context(span))
            self._spans[run_id] = (span, token)
        except Exception:
            logger.exception("telemetry: opening a span failed")

    def _set_span(self, run_id: UUID, **attributes: Any) -> None:
        entry = self._spans.get(run_id)
        if entry is not None:
            entry[0].set_attributes({k: v for k, v in attributes.items() if v is not None})

    def _close_span(self, run_id: UUID, error: BaseException | None = None) -> None:
        entry = self._spans.pop(run_id, None)
        if entry is None:
            return
        span, token = entry
        try:
            if error is not None:
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(trace.Status(trace.StatusCode.ERROR, _clip(error)))
            if trace.get_current_span() is span:  # same context it was attached in
                otel_context.detach(token)  # type: ignore[arg-type]
            span.end()
        except Exception:
            logger.exception("telemetry: closing a span failed")

    # ----- helpers -----

    def _key(self, run_id: UUID, name: str) -> tuple[str, str, str]:
        return (str(self.task_id or ""), str(run_id), name)

    def _agent_of(self, run_id: UUID | None) -> str | None:
        while run_id is not None:
            if run_id in self._agents:
                return self._agents[run_id]
            run_id = self._parents.get(run_id)
        return None

    async def _fired(self, run_id: UUID, hook: str, detail: str | None) -> None:
        agent = self._agent_of(run_id) or "graph"
        await self._deliver(
            self.hub.record(
                EventType.CALLBACK_FIRED,
                task_id=self.task_id,
                agent_id=agent,
                framework="langgraph",
                hook=hook,
                agent=agent,
                detail=_clip(detail) if detail else None,
            )
        )

    # ----- graph and node runs -----

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            is_root = parent_run_id is None or parent_run_id not in self._parents
            self._parents[run_id] = parent_run_id
            metadata = metadata or {}
            name = kwargs.get("name") or (serialized or {}).get("name") or "graph"
            is_node = not is_root and metadata.get("langgraph_node") == name
            if not (is_root or is_node) or "langgraph:hidden" in (tags or []):
                return
            if is_root and metadata.get("hex_graph_kind") == "solo":
                self._solo_roots.add(run_id)
                return
            kind = (
                metadata.get("hex_kind", "step")
                if is_node
                else metadata.get("hex_graph_kind", "graph")
            )
            parent = (
                self.root_parent
                if is_root or parent_run_id in self._solo_roots
                else self._agent_of(parent_run_id)
            )
            self._agents[run_id] = name
            self.hub._start(self._key(run_id, name))
            self._open_span(
                run_id,
                f"invoke_agent {name}",
                **{"agent.name": name, "agent.framework": "langgraph", "agent.kind": kind},
            )
            await self._deliver(
                self.hub.record(
                    EventType.AGENT_STARTED,
                    task_id=self.task_id,
                    agent_id=name,
                    agent=name,
                    framework="langgraph",
                    kind=kind,
                    parent=parent,
                )
            )
        except Exception:
            logger.exception("telemetry: on_chain_start failed")

    async def _finished(self, run_id: UUID, error: BaseException | None) -> None:
        self._close_span(run_id, error)
        try:
            name = self._agents.pop(run_id, None)
            if name is None:
                return
            duration_ms = self.hub._finish(self._key(run_id, name))
            if duration_ms is None:
                return  # already closed as failed by abort_open
            await self._deliver(
                self.hub.record(
                    EventType.AGENT_FINISHED,
                    task_id=self.task_id,
                    agent_id=name,
                    agent=name,
                    framework="langgraph",
                    ok=error is None,
                    duration_ms=duration_ms,
                )
            )
        except Exception:
            logger.exception("telemetry: agent finish failed")

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        await self._finished(run_id, None)

    async def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        await self._finished(run_id, error)

    # ----- model calls -----

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._parents[run_id] = parent_run_id
            tools = len(((kwargs.get("invocation_params") or {}).get("tools")) or [])
            count = sum(len(batch) for batch in messages)
            self._open_span(run_id, "call_llm", **{"agent.name": self._agent_of(parent_run_id)})
            await self._fired(run_id, "model_start", f"{count} message(s), {tools} tool(s)")
        except Exception:
            logger.exception("telemetry: on_chat_model_start failed")

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            message = response.generations[0][0].message
            meta = message.response_metadata or {}
            usage = message.usage_metadata or {}
            self._set_span(
                run_id,
                **{
                    "llm.provider": meta.get("provider"),
                    "llm.model": meta.get("model"),
                    "llm.latency_ms": meta.get("latency_ms"),
                    "llm.input_tokens": usage.get("input_tokens"),
                    "llm.output_tokens": usage.get("output_tokens"),
                    "cost.usd": meta.get("est_cost_usd"),
                },
            )
            self._close_span(run_id)
            detail = f"{meta.get('provider', '?')}/{meta.get('model', '?')}"
            if usage:
                detail += f", {usage.get('input_tokens')}→{usage.get('output_tokens')} tokens"
            calls = [c["name"] for c in message.tool_calls]
            if calls:
                detail += f", calls {', '.join(calls)}"
            await self._fired(run_id, "model_end", detail)
        except Exception:
            logger.exception("telemetry: on_llm_end failed")

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            self._close_span(run_id, error)
            await self._fired(run_id, "model_error", f"{type(error).__name__}: {error}")
        except Exception:
            logger.exception("telemetry: on_llm_error failed")

    # ----- tool calls -----

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._parents[run_id] = parent_run_id
            name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
            self._tool_names[run_id] = name
            self._open_span(run_id, f"execute_tool {name}", **{"tool.name": name})
            args = ", ".join(sorted((inputs or {}).keys()))
            await self._fired(run_id, "tool_start", f"{name}({args})")
        except Exception:
            logger.exception("telemetry: on_tool_start failed")

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            self._close_span(run_id)
            name = self._tool_names.pop(run_id, "tool")
            content = getattr(output, "content", output)
            await self._fired(run_id, "tool_end", f"{name} → {_clip(content)}")
        except Exception:
            logger.exception("telemetry: on_tool_end failed")

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            self._close_span(run_id, error)
            name = self._tool_names.pop(run_id, "tool")
            await self._fired(run_id, "tool_error", f"{name}: {type(error).__name__}: {error}")
        except Exception:
            logger.exception("telemetry: on_tool_error failed")


def describe_step(step: Any) -> str:
    """CrewAI passes AgentAction (a tool use), ToolResult or AgentFinish objects."""
    kind = type(step).__name__
    tool = getattr(step, "tool", None)
    if tool:
        return f"{kind}: {tool}"
    for attr in ("output", "result", "text"):
        value = getattr(step, attr, None)
        if value:
            return f"{kind}: {value}"
    return kind
