"""Shared LangGraph plumbing: running a graph with telemetry, and the structured-output guard.

The guard enforces a Pydantic schema on one model answer, so nothing downstream ever sees
invalid output:
  1. valid (fenced JSON is unwrapped)                -> status "valid"
  2. invalid -> one repair call via ProviderRouter   -> status "repaired"
  3. still invalid, or no provider answered          -> a schema-valid fallback, status "fallback"
Every check becomes a `schema_validated` event for the Schema checks view.
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ValidationError
from typing_extensions import TypedDict

from app.agents.chat_model import HexChatModel
from app.events.log import EventType
from app.providers.base import ChatMessage

if TYPE_CHECKING:
    from app.telemetry.hub import TelemetryHub

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")
Status = Literal["valid", "repaired", "fallback"]

_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
MAX_ERROR_CHARS = 300


@dataclass
class StructuredResult(Generic[T]):
    value: T
    status: Status
    errors: list[str] = field(default_factory=list)


def extract_json(text: str) -> str:
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _summarize(exc: ValidationError) -> str:
    return json.dumps(
        [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()[:5]]
    )


def _clip(text: str) -> str:
    return text if len(text) <= MAX_ERROR_CHARS else text[: MAX_ERROR_CHARS - 1] + "…"


async def structured_call(
    model: HexChatModel,
    schema: type[T],
    prompt: str,
    *,
    agent: str,
    fallback: Callable[[list[str]], T],
    telemetry: "TelemetryHub | None",
    task_id: uuid.UUID | None = None,
    user_message: str | None = None,
) -> StructuredResult[T]:
    """One model answer that must match `schema` (see the module docstring)."""
    messages = [SystemMessage(prompt), HumanMessage(user_message or "Answer now.")]
    errors: list[str] = []
    result: StructuredResult[T] | None = None
    try:
        reply = await model.ainvoke(messages, json_schema=schema.model_json_schema())
    except Exception as exc:  # no provider answered: a fallback, never a crashed run
        errors.append(f"provider error: {exc}")
        result = StructuredResult(fallback(errors), "fallback", errors)
    else:
        text = reply.text if isinstance(reply.text, str) else str(reply.content)
        try:
            result = StructuredResult(schema.model_validate_json(extract_json(text)), "valid")
        except ValidationError as exc:
            errors.append(_summarize(exc))
            result = await _repair(model, schema, text, errors, fallback)

    if telemetry is not None:
        await telemetry.record(
            EventType.SCHEMA_VALIDATED,
            task_id=task_id,
            agent_id=agent,
            agent=agent,
            schema_name=schema.__name__,
            status=result.status,
            errors=[_clip(e) for e in result.errors],
        )
    return result


async def _repair(
    model: HexChatModel,
    schema: type[T],
    text: str,
    errors: list[str],
    fallback: Callable[[list[str]], T],
) -> StructuredResult[T]:
    request = model.last_request
    if request is not None:
        repair = request.model_copy(
            update={
                "messages": [
                    *request.messages,
                    ChatMessage(role="assistant", content=text),
                    ChatMessage(
                        role="user",
                        content=f"That answer was invalid: {errors[0]}. "
                        "Reply again with a single valid JSON object only.",
                    ),
                ]
            }
        )
        answer = await model.router.complete(repair, model.ctx)
        if answer.ok and answer.content:
            try:
                value = schema.model_validate_json(extract_json(answer.content))
                return StructuredResult(value, "repaired", errors)
            except ValidationError as exc:
                errors.append(_summarize(exc))
        else:
            errors.append(f"repair call failed: {answer.error}")
    return StructuredResult(fallback(errors), "fallback", errors)


async def run_graph(
    graph: CompiledStateGraph,
    state: dict[str, Any],
    *,
    telemetry: "TelemetryHub | None",
    task_id: uuid.UUID | None = None,
    parent: str | None = None,
    recursion_limit: int | None = None,
    kind: str = "graph",
) -> dict[str, Any]:
    """Run a compiled graph once, in memory (PostgreSQL stays the source of truth), with the
    TelemetryHub's callbacks attached. Returns the final graph state."""
    handler = telemetry.handler(task_id=task_id, parent=parent) if telemetry else None
    config: dict[str, Any] = {
        "callbacks": [handler] if handler else [],
        "metadata": {"hex_graph_kind": kind},
    }
    if recursion_limit is not None:
        config["recursion_limit"] = recursion_limit
    # Each graph is its own invocation: callbacks of a graph this one runs inside (a task's loop
    # inside the run's `execute` node) must not see its events twice.
    outer = var_child_runnable_config.set(None)
    try:
        return await graph.ainvoke(state, config=config)  # type: ignore[arg-type]
    finally:
        var_child_runnable_config.reset(outer)
        if handler is not None:
            await handler.flush()  # every event is written before the caller reads them


class EmptyState(TypedDict, total=False):
    """For graphs that keep their working state in Python objects; Postgres is the source of
    truth."""


async def run_agent(
    name: str,
    work: Callable[[], Awaitable[R]],
    *,
    telemetry: "TelemetryHub | None",
    parent: str | None = None,
    task_id: uuid.UUID | None = None,
    kind: str = "llm",
) -> R:
    """Run `work` as a one-node graph named `name`: the node shows as one agent (under `parent`)
    with its model calls. Returns what `work` returned."""
    box: dict[str, R] = {}

    async def node(_: EmptyState) -> EmptyState:
        box["result"] = await work()
        return {}

    graph = StateGraph(EmptyState)
    graph.add_node(name, node, metadata={"hex_kind": kind})
    graph.add_edge(START, name)
    graph.add_edge(name, END)
    await run_graph(
        graph.compile(name=name),
        {},
        telemetry=telemetry,
        task_id=task_id,
        parent=parent,
        kind="solo",
    )
    return box["result"]
