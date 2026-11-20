"""Traces (PRD §14.2): a run's OpenTelemetry spans as a tree, from the stored spans."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Mission, Run, TraceSpan

router = APIRouter(prefix="/traces", tags=["traces"])
MAX_SPANS = 3000


class SpanOut(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str  # agent | model | tool | crew | a2a | sandbox | other
    depth: int
    offset_ms: float  # from the start of the first span
    duration_ms: float
    status: str
    status_message: str | None
    attributes: dict[str, Any]


class TraceOut(BaseModel):
    run_id: uuid.UUID
    spans: list[SpanOut]
    traces: int
    duration_ms: float
    truncated: bool


def kind_of(name: str, attributes: dict[str, Any]) -> str:
    lowered = name.lower()
    if lowered.startswith("crewai.crew") or attributes.get("agent.kind") == "crew":
        return "crew"
    if lowered.startswith(("invoke_agent", "agent_run")) or "agent" in lowered.split()[0]:
        return "agent"
    if (
        "call_llm" in lowered
        or "generate_content" in lowered
        or "gen_ai.request.model" in attributes
    ):
        return "model"
    if lowered.startswith(("execute_tool", "tool")):
        return "tool"
    if "a2a" in lowered or "send_message" in lowered:
        return "a2a"
    if "sandbox" in lowered or lowered.startswith("check"):
        return "sandbox"
    return "other"


@router.get("", response_model=TraceOut)
async def get_trace(
    session: SessionDep,
    run_id: uuid.UUID | None = None,
    mission_id: uuid.UUID | None = None,
    limit: int = Query(default=MAX_SPANS, ge=1, le=MAX_SPANS),
) -> TraceOut:
    """Every span of the traces a run took part in, as a tree (children after their parent,
    in start order)."""
    if mission_id is not None:
        mission = await session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
        run_id = mission.run_id
    if run_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "give a run_id or mission_id")
    if await session.get(Run, run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")

    trace_ids = list(
        await session.scalars(
            select(TraceSpan.trace_id).where(TraceSpan.run_id == run_id).distinct()
        )
    )
    if not trace_ids:
        return TraceOut(run_id=run_id, spans=[], traces=0, duration_ms=0, truncated=False)
    rows = list(
        await session.scalars(
            select(TraceSpan)
            .where(TraceSpan.trace_id.in_(trace_ids))
            .order_by(TraceSpan.start_ns, TraceSpan.end_ns.desc())
            .limit(limit + 1)
        )
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    origin = min(r.start_ns for r in rows)
    end = max(r.end_ns for r in rows)
    by_id = {(r.trace_id, r.span_id): r for r in rows}

    def depth_of(row: TraceSpan) -> int:
        depth, seen = 0, set()
        while row.parent_span_id and (row.trace_id, row.parent_span_id) in by_id:
            key = (row.trace_id, row.parent_span_id)
            if key in seen:  # a cycle can only come from bad data: stop
                break
            seen.add(key)
            row = by_id[key]
            depth += 1
        return depth

    # Tree order: a parent is followed by its children, each trace in start order.
    children: dict[tuple[str, str | None], list[TraceSpan]] = {}
    for row in rows:
        parent = row.parent_span_id if (row.trace_id, row.parent_span_id) in by_id else None
        children.setdefault((row.trace_id, parent), []).append(row)
    ordered: list[TraceSpan] = []

    def walk(trace_id: str, parent: str | None) -> None:
        for row in children.get((trace_id, parent), []):
            ordered.append(row)
            walk(trace_id, row.span_id)

    for trace_id in dict.fromkeys(r.trace_id for r in rows):
        walk(trace_id, None)
    return TraceOut(
        run_id=run_id,
        spans=[
            SpanOut(
                trace_id=r.trace_id,
                span_id=r.span_id,
                parent_span_id=r.parent_span_id,
                name=r.name,
                kind=kind_of(r.name, r.attributes),
                depth=depth_of(r),
                offset_ms=(r.start_ns - origin) / 1e6,
                duration_ms=(r.end_ns - r.start_ns) / 1e6,
                status=r.status,
                status_message=r.status_message,
                attributes=r.attributes,
            )
            for r in ordered
        ],
        traces=len(trace_ids),
        duration_ms=(end - origin) / 1e6,
        truncated=truncated,
    )
