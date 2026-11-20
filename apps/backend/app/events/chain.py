"""The tamper-evident audit chain over the event log (PRD §14.2).

Every event of a run carries `prev_hash` and `hash`, where

    hash = sha256(prev_hash + canonical(record))

and `record` is the event's own fields (run, sequence number, type, agent, task, payload and
timestamp). The first event of a run chains from a fixed genesis hash derived from the run id.
Change, remove or reorder any stored event and every hash after it stops matching, so
`verify_run` finds the first point where the log is not what was written.

What the chain can and cannot show: it proves the log is internally consistent. Someone with
write access to the database who recomputes every later hash could still rewrite history, so a
**head hash** is exposed (`GET /api/audit/head`) for the user to keep somewhere else; `verify_run`
accepts it and then also detects a truncated log or a rewritten one.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Run


def genesis(run_id: uuid.UUID) -> str:
    return hashlib.sha256(f"hexmind-genesis:{run_id}".encode()).hexdigest()


def canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stamp(ts: datetime) -> str:
    """One spelling of a timestamp whatever time zone the database reports it in."""
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


def record_of(
    *,
    run_id: uuid.UUID,
    seq: int,
    type: str,
    agent_id: str | None,
    task_id: uuid.UUID | None,
    payload: dict[str, Any],
    ts: datetime,
) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "seq": seq,
        "type": type,
        "agent_id": agent_id,
        "task_id": str(task_id) if task_id else None,
        "payload": payload,
        "ts": _stamp(ts),
    }


def link(prev_hash: str, record: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(record)).encode()).hexdigest()


def hash_of_event(event: AgentEvent) -> str:
    """The hash an event should have, from its stored fields and its stored `prev_hash`."""
    return link(
        event.prev_hash or "",
        record_of(
            run_id=event.run_id,
            seq=event.seq,
            type=event.type,
            agent_id=event.agent_id,
            task_id=event.task_id,
            payload=event.payload,
            ts=event.ts,
        ),
    )


@dataclass(frozen=True)
class Break:
    seq: int | None
    reason: str


@dataclass(frozen=True)
class RunAudit:
    run_id: uuid.UUID
    events: int
    head: str | None  # the hash of the last event
    legacy: int  # events written before the chain existed (not covered)
    broken: Break | None

    @property
    def ok(self) -> bool:
        return self.broken is None


async def verify_run(
    session: AsyncSession, run_id: uuid.UUID, *, expected_head: str | None = None
) -> RunAudit:
    """Recompute the chain of one run from its stored events."""
    run = await session.get(Run, run_id)
    if run is None:
        return RunAudit(run_id, 0, None, 0, Break(None, "the run does not exist"))
    events = list(
        await session.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
        )
    )
    previous = genesis(run_id)
    legacy = 0
    head: str | None = None
    expected_seq = 1
    for event in events:
        if event.seq != expected_seq:
            return RunAudit(
                run_id,
                len(events),
                head,
                legacy,
                Break(event.seq, f"event {expected_seq} is missing"),
            )
        expected_seq += 1
        if event.hash is None:  # written before the chain existed
            legacy += 1
            continue
        if (event.prev_hash or "") != previous:
            return RunAudit(
                run_id, len(events), head, legacy,
                Break(event.seq, "it does not follow the event before it"),
            )  # fmt: skip
        if hash_of_event(event) != event.hash:
            return RunAudit(
                run_id, len(events), head, legacy,
                Break(event.seq, "its content was changed after it was written"),
            )  # fmt: skip
        previous = head = event.hash
    if run.last_event_seq != len(events):
        return RunAudit(
            run_id, len(events), head, legacy,
            Break(len(events) + 1, "events at the end of the log are missing"),
        )  # fmt: skip
    if expected_head is not None and expected_head != head:
        return RunAudit(
            run_id, len(events), head, legacy,
            Break(None, "the log does not end where you recorded it did"),
        )  # fmt: skip
    return RunAudit(run_id, len(events), head, legacy, None)
