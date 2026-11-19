"""Which models each persona uses (PRD §10.4): storing assignments and turning one into a route.

A persona's assignment names a primary (connection, model), an ordered fallback chain, and an
escalation model. Until the Auto assigner (a later P4 step) exists, assignments are set by the
user; `set_by` records that. A persona with no assignment keeps using the global provider order.
"""

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Connection, ModelAssignment
from app.providers.routing import Route, Target

MAX_FALLBACKS = 5


class ModelRef(BaseModel):
    connection_id: uuid.UUID
    model: str = Field(min_length=1, max_length=128)


class AssignmentIn(BaseModel):
    primary: ModelRef
    fallbacks: list[ModelRef] = Field(default_factory=list, max_length=MAX_FALLBACKS)
    escalate: ModelRef | None = None


class AssignmentError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


async def _check(session: AsyncSession, ref: ModelRef, what: str) -> Connection:
    connection = await session.get(Connection, ref.connection_id)
    if connection is None:
        raise AssignmentError(f"the {what} connection does not exist")
    if not connection.enabled:
        raise AssignmentError(f"the {what} connection {connection.name!r} is disabled")
    # An empty model list means the connection was never tested successfully: allow any name.
    if connection.models and ref.model not in connection.models:
        raise AssignmentError(f"{connection.name!r} does not list the model {ref.model!r}")
    return connection


async def set_assignment(
    session: AsyncSession,
    persona_id: str,
    body: AssignmentIn,
    *,
    set_by: str = "user",
    reason: str | None = None,
) -> ModelAssignment:
    await _check(session, body.primary, "primary")
    for ref in body.fallbacks:
        await _check(session, ref, "fallback")
    if body.escalate is not None:
        await _check(session, body.escalate, "escalation")
    row = await session.scalar(
        select(ModelAssignment).where(ModelAssignment.persona_id == persona_id)
    )
    if row is None:
        row = ModelAssignment(persona_id=persona_id)
        session.add(row)
    row.primary_connection_id = body.primary.connection_id
    row.primary_model = body.primary.model
    row.fallbacks = [_dump(r) for r in body.fallbacks]
    row.escalate = _dump(body.escalate) if body.escalate else None
    row.set_by = set_by
    row.reason = reason
    await session.flush()
    await session.refresh(row)  # `updated_at` is set by the database on every update
    return row


def _dump(ref: ModelRef) -> dict[str, Any]:
    return {"connection_id": str(ref.connection_id), "model": ref.model}


async def route_for(
    session: AsyncSession, persona_id: str, *, escalate: bool = False
) -> Route | None:
    """The persona's route (primary, then fallbacks), or None if it has no assignment. With
    `escalate`, the escalation model goes first and the normal route follows as its fallback
    (so a persona with no escalation model gets its normal route)."""
    row = await session.scalar(
        select(ModelAssignment).where(ModelAssignment.persona_id == persona_id)
    )
    if row is None:
        return None
    targets = [Target(row.primary_connection_id, row.primary_model)]
    targets += [
        Target(uuid.UUID(item["connection_id"]), item["model"]) for item in row.fallbacks or []
    ]
    if escalate and row.escalate:
        stronger = Target(uuid.UUID(row.escalate["connection_id"]), row.escalate["model"])
        targets = [stronger, *[t for t in targets if t != stronger]]
    return Route(tuple(targets), persona_id=persona_id)


async def has_escalation(session: AsyncSession, persona_id: str) -> bool:
    row = await session.scalar(
        select(ModelAssignment).where(ModelAssignment.persona_id == persona_id)
    )
    return row is not None and row.escalate is not None
