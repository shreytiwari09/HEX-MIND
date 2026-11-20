"""Persisting traces in Postgres so they render offline (PRD §14.2).

OpenTelemetry spans are created in two processes (the backend and the CrewAI crew service). This
span processor writes every finished span to the `trace_spans` table, from a background thread so
that tracing never slows an agent down and a database hiccup never breaks one: a span that cannot
be written is dropped (and counted), never retried forever.

**What is stored is sanitised.** ADK can attach whole prompts and responses to its spans; those
must not land in a table (the audit trail proves what was sent with hashes, not by keeping the
text). So only attributes with an allow-listed name are kept, content-bearing names are refused
even inside an allowed prefix, string values are redacted for secrets and cut short.
"""

import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import StatusCode

from app.context.redact import redact

logger = logging.getLogger(__name__)

QUEUE_SIZE = 20_000
BATCH = 100
FLUSH_S = 0.5
MAX_VALUE_CHARS = 300
MAX_ATTRIBUTES = 60
ALLOWED_PREFIXES = ("hexmind.", "agent.", "gen_ai.", "tool.", "a2a.", "check.", "sandbox.")
# Attribute names that carry content (prompts, responses, tool arguments and results) are refused
# even under an allowed prefix: the last part of the name says what it holds.
_CONTENT = (
    "prompt", "completion", "content", "message", "input", "output", "arguments", "args",
    "response", "request", "result", "instruction", "text", "body",
)  # fmt: skip
_CONTENT_SEGMENTS = {"prompt", "completion", "messages"}


def is_content(key: str) -> bool:
    segments = key.lower().split(".")
    if _CONTENT_SEGMENTS & set(segments):
        return True
    return any(word in segments[-1] for word in _CONTENT)


def clean_attributes(attributes: Any) -> dict[str, Any]:
    """The attributes that may be stored: allow-listed names, no content, redacted and short."""
    kept: dict[str, Any] = {}
    for key, value in dict(attributes or {}).items():
        lowered = str(key).lower()
        if not lowered.startswith(ALLOWED_PREFIXES):
            continue
        if is_content(lowered) and not (
            lowered.startswith("gen_ai.usage.") or lowered.endswith(("_id", ".id"))
        ):
            continue  # counters and ids are not content
        if isinstance(value, str):
            value = redact(value)[:MAX_VALUE_CHARS]
        elif isinstance(value, (list, tuple)):
            value = [redact(v)[:MAX_VALUE_CHARS] if isinstance(v, str) else v for v in value][:20]
        elif not isinstance(value, (bool, int, float)) and value is not None:
            value = redact(str(value))[:MAX_VALUE_CHARS]
        kept[str(key)] = value
        if len(kept) >= MAX_ATTRIBUTES:
            break
    return kept


def row_of(span: ReadableSpan) -> tuple[Any, ...] | None:
    context = span.get_span_context()
    if context is None or span.start_time is None or span.end_time is None:
        return None
    parent = span.parent.span_id if span.parent else None
    attributes = clean_attributes(span.attributes)
    run_id: uuid.UUID | None = None
    try:
        run_id = uuid.UUID(str((span.attributes or {}).get("hexmind.run_id")))
    except ValueError:
        pass
    status = span.status.status_code
    return (
        format(context.trace_id, "032x"),
        format(context.span_id, "016x"),
        format(parent, "016x") if parent else None,
        span.name[:200],
        span.start_time,
        span.end_time,
        {StatusCode.OK: "ok", StatusCode.ERROR: "error"}.get(status, "unset"),
        redact(span.status.description or "")[:MAX_VALUE_CHARS] or None,
        json.dumps(attributes),
        run_id,
    )


INSERT = """
INSERT INTO trace_spans
    (trace_id, span_id, parent_span_id, name, start_ns, end_ns, status, status_message,
     attributes, run_id, started_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
ON CONFLICT (trace_id, span_id) DO NOTHING
"""


class PostgresSpanProcessor(SpanProcessor):
    """Writes finished spans to Postgres from a background thread."""

    def __init__(self, database_url: str) -> None:
        self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._queue: queue.Queue[tuple[Any, ...] | None] = queue.Queue(QUEUE_SIZE)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._pending = 0
        self._done = threading.Condition()
        self.dropped = 0
        self.written = 0

    # ---------- the OpenTelemetry interface ----------

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        row = row_of(span)
        if row is None:
            return
        self._start()
        try:
            self._queue.put_nowait(row)
        except queue.Full:
            self.dropped += 1
            return
        with self._done:
            self._pending += 1

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Wait until everything queued so far has been written (or dropped)."""
        deadline = time.monotonic() + timeout_millis / 1000
        with self._done:
            while self._pending > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._done.wait(remaining)
        return True

    def shutdown(self) -> None:
        self.force_flush(5000)
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=5)

    # ---------- the writer ----------

    def _start(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="span-store", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        asyncio.run(self._write_loop())

    async def _write_loop(self) -> None:
        connection: asyncpg.Connection | None = None
        loop = asyncio.get_running_loop()
        stop = False
        while not stop:
            batch: list[tuple[Any, ...]] = []
            first = await loop.run_in_executor(None, self._next, FLUSH_S)
            if first is None:
                continue
            if first == "stop":
                break
            batch.append(first)
            while len(batch) < BATCH:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    stop = True
                    break
                batch.append(item)
            try:
                if connection is None or connection.is_closed():
                    connection = await asyncpg.connect(self._dsn, timeout=5)
                await connection.executemany(INSERT, [self._params(r) for r in batch])
                self.written += len(batch)
            except Exception as exc:  # a span is diagnostics: never let it break anything
                self.dropped += len(batch)
                logger.debug("could not store %d span(s): %s", len(batch), exc)
                if connection is not None:
                    try:
                        await connection.close()
                    except Exception:  # noqa: BLE001, S110
                        pass
                    connection = None
            finally:
                with self._done:
                    self._pending = max(0, self._pending - len(batch))
                    self._done.notify_all()
        if connection is not None:
            await connection.close()

    def _next(self, timeout: float) -> Any:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return "stop" if item is None else item

    @staticmethod
    def _params(row: tuple[Any, ...]) -> tuple[Any, ...]:
        trace_id, span_id, parent, name, start_ns, end_ns, status, message, attributes, run_id = row
        started = datetime.fromtimestamp(start_ns / 1e9, tz=UTC)
        return (
            trace_id,
            span_id,
            parent,
            name,
            start_ns,
            end_ns,
            status,
            message,
            attributes,
            run_id,
            started,
        )
