"""The audit trail (PRD §14.2): the event log with its hash chain, and a check that it is intact."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import AgentEvent, Mission, Run
from app.events import chain

router = APIRouter(prefix="/audit", tags=["audit"])


class BreakOut(BaseModel):
    seq: int | None
    reason: str


class RunAuditOut(BaseModel):
    run_id: uuid.UUID
    ok: bool
    events: int
    head: str | None  # hash of the last event: keep it somewhere safe to detect later rewrites
    legacy: int  # events from before the chain existed, which it does not cover
    broken: BreakOut | None


class VerifyOut(BaseModel):
    ok: bool
    runs: list[RunAuditOut]


class AuditEventOut(BaseModel):
    seq: int
    type: str
    agent_id: str | None
    payload: dict  # type: ignore[type-arg]
    ts: datetime
    prev_hash: str | None
    hash: str | None


def _out(audit: chain.RunAudit) -> RunAuditOut:
    return RunAuditOut(
        run_id=audit.run_id,
        ok=audit.ok,
        events=audit.events,
        head=audit.head,
        legacy=audit.legacy,
        broken=BreakOut(seq=audit.broken.seq, reason=audit.broken.reason) if audit.broken else None,
    )


async def _run_ids(
    session: SessionDep, run_id: uuid.UUID | None, mission_id: uuid.UUID | None
) -> list[uuid.UUID]:
    if mission_id is not None:
        mission = await session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
        return [mission.run_id]
    if run_id is not None:
        if await session.get(Run, run_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
        return [run_id]
    return list(await session.scalars(select(Run.id).order_by(Run.created_at)))


@router.get("/verify", response_model=VerifyOut)
async def verify(
    session: SessionDep,
    run_id: uuid.UUID | None = None,
    mission_id: uuid.UUID | None = None,
    expected_head: str | None = Query(default=None, min_length=64, max_length=64),
) -> VerifyOut:
    """Recompute the hash chain of one run, one mission's run, or every run. With
    `expected_head` (the head you recorded earlier) a rewritten or truncated log is caught too."""
    if expected_head is not None and run_id is None and mission_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "expected_head needs a run")
    ids = await _run_ids(session, run_id, mission_id)
    audits = [await chain.verify_run(session, rid, expected_head=expected_head) for rid in ids]
    return VerifyOut(ok=all(a.ok for a in audits), runs=[_out(a) for a in audits])


@router.get("/head", response_model=RunAuditOut)
async def head(
    session: SessionDep, run_id: uuid.UUID | None = None, mission_id: uuid.UUID | None = None
) -> RunAuditOut:
    """The current head hash of a run, to record outside this database."""
    if run_id is None and mission_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "give a run_id or mission_id")
    ids = await _run_ids(session, run_id, mission_id)
    return _out(await chain.verify_run(session, ids[0]))


@router.get("/events", response_model=list[AuditEventOut])
async def events(
    session: SessionDep,
    run_id: uuid.UUID | None = None,
    mission_id: uuid.UUID | None = None,
    after_seq: int = 0,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[AuditEventOut]:
    if run_id is None and mission_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "give a run_id or mission_id")
    ids = await _run_ids(session, run_id, mission_id)
    rows = await session.scalars(
        select(AgentEvent)
        .where(AgentEvent.run_id == ids[0], AgentEvent.seq > after_seq)
        .order_by(AgentEvent.seq)
        .limit(limit)
    )
    return [
        AuditEventOut(
            seq=e.seq,
            type=e.type,
            agent_id=e.agent_id,
            payload=e.payload,
            ts=e.ts,
            prev_hash=e.prev_hash,
            hash=e.hash,
        )
        for e in rows
    ]
