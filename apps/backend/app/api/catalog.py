"""The model catalog (PRD §12.4): what each connection can reach, and the facts known about it."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ServicesDep, SessionDep
from app.catalog.modelsdev import CatalogError
from app.catalog.service import CatalogEntry, CatalogStatus

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("", response_model=list[CatalogEntry])
async def list_catalog(
    session: SessionDep, services: ServicesDep, connection_id: uuid.UUID | None = None
) -> list[CatalogEntry]:
    assert services.catalog is not None
    return await services.catalog.entries(session, str(connection_id) if connection_id else None)


@router.get("/status", response_model=CatalogStatus)
async def catalog_status(services: ServicesDep) -> CatalogStatus:
    assert services.catalog is not None
    return services.catalog.status()


@router.post("/refresh", response_model=CatalogStatus)
async def refresh_catalog(services: ServicesDep) -> CatalogStatus:
    """Download the models.dev catalog now. Offline, the cached copy keeps working."""
    assert services.catalog is not None
    try:
        return await services.catalog.refresh()
    except CatalogError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
