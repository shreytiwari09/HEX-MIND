"""Append-only per-run event log (plan §4.1).

`seq` is per-run and gap-free: it is taken from `runs.last_event_seq` with an UPDATE ... RETURNING
in the caller's transaction, which row-locks the run until commit, so concurrent writers to the
same run are serialized and a rolled-back event does not consume a number.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Run
from app.events.chain import genesis, link, record_of
from app.events.schema import PAYLOADS, EventType

__all__ = ["NOTIFY_CHANNEL", "EventType", "append_event", "list_events"]

NOTIFY_CHANNEL = "hexmind_events"


async def append_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    type: EventType,
    *,
    agent_id: str | None = None,
    task_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentEvent:
    # Validate against the event contract before taking a sequence number.
    validated = PAYLOADS[type].model_validate(payload or {}).model_dump(mode="json")
    seq = (
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(last_event_seq=Run.last_event_seq + 1)
            .returning(Run.last_event_seq)
        )
    ).scalar_one()
    # Chain it to the event before (the run row is locked, so no one else is appending).
    previous = (
        genesis(run_id)
        if seq == 1
        else (
            await session.scalar(
                select(AgentEvent.hash).where(
                    AgentEvent.run_id == run_id, AgentEvent.seq == seq - 1
                )
            )
        )
        or ""
    )
    now = datetime.now(UTC)
    event = AgentEvent(
        run_id=run_id,
        seq=seq,
        type=type.value,
        agent_id=agent_id,
        task_id=task_id,
        payload=validated,
        ts=now,
        prev_hash=previous,
        hash=link(
            previous,
            record_of(
                run_id=run_id,
                seq=seq,
                type=type.value,
                agent_id=agent_id,
                task_id=task_id,
                payload=validated,
                ts=now,
            ),
        ),
    )
    session.add(event)
    await session.flush()
    # Delivered when this transaction commits, to every process listening (the WebSocket
    # stream in the backend, whichever process wrote the event).
    await session.execute(
        text("SELECT pg_notify(:channel, :run_id)"),
        {"channel": NOTIFY_CHANNEL, "run_id": str(run_id)},
    )
    return event


async def list_events(
    session: AsyncSession, run_id: uuid.UUID, *, after_seq: int = 0, limit: int = 1000
) -> list[AgentEvent]:
    result = await session.scalars(
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id, AgentEvent.seq > after_seq)
        .order_by(AgentEvent.seq)
        .limit(limit)
    )
    return list(result)
