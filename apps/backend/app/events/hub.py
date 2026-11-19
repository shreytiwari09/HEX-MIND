"""Wakes event streams when a run gets new events (PRD §12.4, decision D4: push, not polling).

`append_event` calls `pg_notify` in the writer's transaction, so every process that writes
events (the backend, the CrewAI crew service) wakes every listener once the event is committed.
The hub holds one dedicated Postgres connection that LISTENs and sets an `asyncio.Event` for each
stream subscribed to that run. Streams read the events themselves, ordered by `seq`; the wake-up
only says "look again". A slow safety poll covers a lost connection, so a stream never stalls.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Iterator

import asyncpg

from app.events.log import NOTIFY_CHANNEL

logger = logging.getLogger(__name__)


class EventHub:
    def __init__(self, database_url: str) -> None:
        self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._connection: asyncpg.Connection | None = None
        self._waiters: dict[uuid.UUID, set[asyncio.Event]] = {}
        self._lock = asyncio.Lock()

    async def ensure_started(self) -> None:
        """Connect and LISTEN (again, if the connection was lost). Never raises: without the
        connection, streams fall back to their safety poll."""
        async with self._lock:
            if self._connection is not None and not self._connection.is_closed():
                return
            try:
                self._connection = await asyncpg.connect(self._dsn)
                await self._connection.add_listener(NOTIFY_CHANNEL, self._on_notify)
            except (OSError, asyncpg.PostgresError) as exc:
                logger.warning("event hub could not listen: %s", exc)
                self._connection = None

    def _on_notify(self, connection: object, pid: int, channel: str, payload: str) -> None:
        try:
            run_id = uuid.UUID(payload)
        except ValueError:
            return
        for waiter in self._waiters.get(run_id, ()):
            waiter.set()

    @contextlib.contextmanager
    def subscribe(self, run_id: uuid.UUID) -> Iterator[asyncio.Event]:
        """An event that is set whenever `run_id` has new events. Clear it, then read, then
        wait on it: a notification that arrives in between is never lost."""
        waiter = asyncio.Event()
        self._waiters.setdefault(run_id, set()).add(waiter)
        try:
            yield waiter
        finally:
            waiters = self._waiters.get(run_id)
            if waiters is not None:
                waiters.discard(waiter)
                if not waiters:
                    del self._waiters[run_id]

    async def stop(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None and not connection.is_closed():
            with contextlib.suppress(Exception):
                await connection.close(timeout=5)
