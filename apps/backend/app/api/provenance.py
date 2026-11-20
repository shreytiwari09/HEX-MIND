"""Provenance of a mission's changed files (PRD §14.2)."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.db.models import Mission
from app.missions import provenance

router = APIRouter(prefix="/missions", tags=["provenance"])


@router.get("/{mission_id}/provenance")
async def get_provenance(
    mission_id: uuid.UUID,
    session: SessionDep,
    path: str | None = Query(default=None, max_length=500),
    format: Literal["json", "prov"] = "json",
) -> dict[str, Any]:
    """Where each changed file came from: feature, persona version, skills, model calls, the
    validators that checked it and the approval, each with its place in the audit chain. With
    `path`, only that file (404 if the mission did not change it); `format=prov` is W3C
    PROV-JSON."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    document = await provenance.build(session, mission)
    if path is not None:
        files = [f for f in document["files"] if f["path"] == path]
        if not files:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "the mission did not change that file")
        document["files"] = files
    return provenance.to_prov(document) if format == "prov" else document
