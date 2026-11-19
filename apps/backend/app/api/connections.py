"""Model connections and their keys (PRD §12.4, §10.2).

Keys arrive in a request body, go straight to the OS keychain, and are never returned: every
response lists keys by label only.
"""

import uuid
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from app.api.deps import ServicesDep, SessionDep
from app.db.models import Connection
from app.providers import registry
from app.providers.presets import PRESETS
from app.providers.probe import ProbeResult
from app.providers.registry import RegistryError
from app.providers.secrets import KeyStoreError

router = APIRouter(prefix="/connections", tags=["connections"])
types_router = APIRouter(prefix="/provider-types", tags=["connections"])


class ProviderTypeOut(BaseModel):
    type: str
    label: str
    base_url: str | None
    requires_key: bool
    local: bool


class KeyOut(BaseModel):
    id: uuid.UUID
    label: str
    position: int
    disabled: bool


class TestOut(BaseModel):
    ok: bool | None
    error: str | None
    tested_at: datetime | None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    name: str
    provider_type: str
    base_url: str
    extra_headers: dict[str, Any]
    enabled: bool
    requires_key: bool
    keys: list[KeyOut]
    models: list[str]
    last_test: TestOut


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    provider_type: str
    base_url: str | None = Field(default=None, max_length=300)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    # SecretStr so the value is masked in validation errors and reprs.
    api_key: SecretStr | None = None
    key_label: str = Field(default="key 1", max_length=64)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None


class KeyCreate(BaseModel):
    api_key: SecretStr = Field(min_length=1)
    label: str = Field(default="", max_length=64)


class ConnectionResult(BaseModel):
    connection: ConnectionOut
    test: ProbeResult | None


def _refuse(exc: RegistryError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


def _store_failed(exc: KeyStoreError) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


async def _out(session: SessionDep, connection: Connection) -> ConnectionOut:
    keys = await registry.keys_of(session, connection.id)
    preset = PRESETS[connection.provider_type]
    return ConnectionOut(
        id=connection.id,
        name=connection.name,
        provider_type=connection.provider_type,
        base_url=connection.base_url,
        extra_headers=connection.extra_headers,
        enabled=connection.enabled,
        requires_key=preset.requires_key,
        keys=[
            KeyOut(id=k.id, label=k.label, position=k.position, disabled=k.disabled) for k in keys
        ],
        models=connection.models,
        last_test=TestOut(
            ok=connection.last_test_ok,
            error=connection.last_test_error,
            tested_at=connection.last_tested_at,
        ),
    )


async def _http(services: ServicesDep):  # type: ignore[no-untyped-def]
    """The client connection tests use; a fresh short-lived one unless tests injected theirs."""
    if services.connection_http is not None:
        return services.connection_http
    return httpx.AsyncClient(timeout=15.0, follow_redirects=False)


async def _close(services: ServicesDep, http: httpx.AsyncClient) -> None:
    if http is not services.connection_http:
        await http.aclose()


@types_router.get("", response_model=list[ProviderTypeOut])
async def provider_types() -> list[ProviderTypeOut]:
    return [
        ProviderTypeOut(
            type=p.type,
            label=p.label,
            base_url=p.base_url,
            requires_key=p.requires_key,
            local=p.local,
        )
        for p in PRESETS.values()
    ]


@router.get("", response_model=list[ConnectionOut])
async def list_connections(session: SessionDep) -> list[ConnectionOut]:
    return [await _out(session, c) for c in await registry.list_connections(session)]


@router.post("", response_model=ConnectionResult, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate, session: SessionDep, services: ServicesDep
) -> ConnectionResult:
    """Add a connection, test it, and list the models it can reach. A key the provider rejects
    is refused and nothing is saved."""
    http = await _http(services)
    try:
        connection, result = await registry.create_connection(
            session,
            services.keystore,
            http,
            name=body.name,
            provider_type=body.provider_type,
            base_url=body.base_url,
            extra_headers=body.extra_headers,
            api_key=body.api_key.get_secret_value() if body.api_key else None,
            key_label=body.key_label,
        )
    except RegistryError as exc:
        raise _refuse(exc) from None
    except KeyStoreError as exc:
        raise _store_failed(exc) from None
    finally:
        await _close(services, http)
    return ConnectionResult(connection=await _out(session, connection), test=result)


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: uuid.UUID, session: SessionDep) -> ConnectionOut:
    try:
        return await _out(session, await registry.get_connection(session, connection_id))
    except RegistryError as exc:
        raise _refuse(exc) from None


@router.put("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: uuid.UUID, body: ConnectionUpdate, session: SessionDep
) -> ConnectionOut:
    try:
        connection = await registry.get_connection(session, connection_id)
    except RegistryError as exc:
        raise _refuse(exc) from None
    if body.name is not None and body.name != connection.name:
        taken = await registry.list_connections(session)
        if any(c.name == body.name for c in taken):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"a connection named {body.name!r} exists"
            )
        connection.name = body.name
    if body.enabled is not None:
        connection.enabled = body.enabled
    await session.flush()
    return await _out(session, connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, session: SessionDep, services: ServicesDep
) -> None:
    try:
        connection = await registry.get_connection(session, connection_id)
        await registry.delete_connection(session, services.keystore, connection)
    except RegistryError as exc:
        raise _refuse(exc) from None
    except KeyStoreError as exc:
        raise _store_failed(exc) from None


@router.post("/{connection_id}/test", response_model=ConnectionResult)
async def test_connection(
    connection_id: uuid.UUID, session: SessionDep, services: ServicesDep
) -> ConnectionResult:
    try:
        connection = await registry.get_connection(session, connection_id)
    except RegistryError as exc:
        raise _refuse(exc) from None
    http = await _http(services)
    try:
        result = await registry.check_connection(session, services.keystore, http, connection)
    except KeyStoreError as exc:
        raise _store_failed(exc) from None
    finally:
        await _close(services, http)
    return ConnectionResult(connection=await _out(session, connection), test=result)


@router.post(
    "/{connection_id}/keys", response_model=ConnectionResult, status_code=status.HTTP_201_CREATED
)
async def add_key(
    connection_id: uuid.UUID, body: KeyCreate, session: SessionDep, services: ServicesDep
) -> ConnectionResult:
    """Add a key to the connection's pool. A key the provider rejects is refused."""
    http = await _http(services)
    try:
        connection = await registry.get_connection(session, connection_id)
        existing = await registry.keys_of(session, connection.id)
        label = body.label or f"key {len(existing) + 1}"
        _, result = await registry.add_key(
            session,
            services.keystore,
            http,
            connection,
            api_key=body.api_key.get_secret_value(),
            label=label,
        )
    except RegistryError as exc:
        raise _refuse(exc) from None
    except KeyStoreError as exc:
        raise _store_failed(exc) from None
    finally:
        await _close(services, http)
    return ConnectionResult(connection=await _out(session, connection), test=result)


@router.delete("/{connection_id}/keys/{key_id}", response_model=ConnectionOut)
async def remove_key(
    connection_id: uuid.UUID, key_id: uuid.UUID, session: SessionDep, services: ServicesDep
) -> ConnectionOut:
    try:
        connection = await registry.get_connection(session, connection_id)
        await registry.remove_key(session, services.keystore, connection, key_id)
    except RegistryError as exc:
        raise _refuse(exc) from None
    except KeyStoreError as exc:
        raise _store_failed(exc) from None
    return await _out(session, connection)
