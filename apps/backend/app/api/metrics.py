"""Metrics for a mission or all of a project's missions (PRD §14.3)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.db.models import Mission, Project
from app.metrics import service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
async def get_metrics(
    session: SessionDep, project_id: uuid.UUID | None = None, mission_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Cost, tokens, latency, retries, escalations, fallbacks, key rotations, guardrail triggers and
    validator catch rate, from stored data. Figures that cannot be measured are `null`."""
    if mission_id is None and project_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "give a project_id or mission_id")
    if mission_id is not None and await session.get(Mission, mission_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    if mission_id is None and await session.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    scope = await service.scope_for(session, project_id=project_id, mission_id=mission_id)
    return await service.compute(session, scope)
