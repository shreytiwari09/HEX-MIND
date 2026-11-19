"""The connection registry: provider connections and their key pools (PRD §10.2).

Database rows say which connections and keys exist; the secrets themselves live only in the key
store. Nothing here returns, logs or raises with a secret.
"""

import uuid
from datetime import UTC, datetime

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Connection, ConnectionKey
from app.providers.presets import preset_for
from app.providers.probe import ProbeResult, probe, validate_base_url, validate_headers
from app.providers.secrets import KeyStore

MAX_KEYS = 20


class RegistryError(ValueError):
    """The request cannot be done; the message is safe to show the user."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def key_ref(connection_id: uuid.UUID, key_id: uuid.UUID) -> str:
    return f"connection-{connection_id}-{key_id}"


async def list_connections(session: AsyncSession) -> list[Connection]:
    return list(await session.scalars(select(Connection).order_by(Connection.created_at)))


async def keys_of(session: AsyncSession, connection_id: uuid.UUID) -> list[ConnectionKey]:
    return list(
        await session.scalars(
            select(ConnectionKey)
            .where(ConnectionKey.connection_id == connection_id)
            .order_by(ConnectionKey.position, ConnectionKey.created_at)
        )
    )


async def get_connection(session: AsyncSession, connection_id: uuid.UUID) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise RegistryError("connection not found", 404)
    return connection


async def secret_for(keystore: KeyStore, key: ConnectionKey) -> str | None:
    """The key's secret, for the router to call a provider with. Never expose the result."""
    return await run_in_threadpool(keystore.get, key.key_ref)


async def create_connection(
    session: AsyncSession,
    keystore: KeyStore,
    http: httpx.AsyncClient,
    *,
    name: str,
    provider_type: str,
    base_url: str | None,
    extra_headers: dict[str, str],
    api_key: str | None,
    key_label: str = "key 1",
) -> tuple[Connection, ProbeResult | None]:
    """Add a connection and, if a key was given, test it and store it in the key store.

    A key the provider rejects is not stored. A connection whose test failed for another reason
    (unreachable, wrong URL) is still created, so the user can correct it."""
    try:
        preset = preset_for(provider_type)
    except ValueError as exc:
        raise RegistryError(str(exc)) from None
    url = base_url or preset.base_url
    if not url:
        raise RegistryError("this provider type needs a base URL")
    try:
        url = validate_base_url(url, has_key=bool(api_key))
        headers = validate_headers(extra_headers)
    except ValueError as exc:
        raise RegistryError(str(exc)) from None
    if await session.scalar(select(Connection.id).where(Connection.name == name)):
        raise RegistryError(f"a connection named {name!r} already exists", 409)

    connection = Connection(
        name=name, provider_type=provider_type, base_url=url, extra_headers=headers
    )
    session.add(connection)
    await session.flush()
    result = await _test_and_record(session, keystore, http, connection, api_key)
    if api_key and result.auth_rejected:
        raise RegistryError("the provider rejected this key, so it was not saved")
    if api_key:
        await _store_key(session, keystore, connection, api_key, key_label, position=0)
    return connection, result


async def add_key(
    session: AsyncSession,
    keystore: KeyStore,
    http: httpx.AsyncClient,
    connection: Connection,
    *,
    api_key: str,
    label: str,
) -> tuple[ConnectionKey, ProbeResult]:
    count = await session.scalar(
        select(func.count())
        .select_from(ConnectionKey)
        .where(ConnectionKey.connection_id == connection.id)
    )
    if (count or 0) >= MAX_KEYS:
        raise RegistryError(f"a connection can hold at most {MAX_KEYS} keys")
    preset = preset_for(connection.provider_type)
    try:
        validate_base_url(connection.base_url, has_key=True)
    except ValueError as exc:
        raise RegistryError(str(exc)) from None
    result = await probe(preset, connection.base_url, api_key, connection.extra_headers, http)
    if result.auth_rejected:
        raise RegistryError("the provider rejected this key, so it was not saved")
    key = await _store_key(session, keystore, connection, api_key, label, position=count or 0)
    return key, result


async def _store_key(
    session: AsyncSession,
    keystore: KeyStore,
    connection: Connection,
    api_key: str,
    label: str,
    *,
    position: int,
) -> ConnectionKey:
    key = ConnectionKey(
        id=uuid.uuid4(), connection_id=connection.id, label=label, position=position
    )
    key.key_ref = key_ref(connection.id, key.id)
    session.add(key)
    await session.flush()
    # If the key store refuses, the exception rolls back the row above.
    await run_in_threadpool(keystore.set, key.key_ref, api_key)
    return key


async def remove_key(
    session: AsyncSession, keystore: KeyStore, connection: Connection, key_id: uuid.UUID
) -> None:
    key = await session.get(ConnectionKey, key_id)
    if key is None or key.connection_id != connection.id:
        raise RegistryError("key not found", 404)
    ref = key.key_ref
    await session.delete(key)
    await session.flush()
    await run_in_threadpool(keystore.delete, ref)


async def delete_connection(
    session: AsyncSession, keystore: KeyStore, connection: Connection
) -> None:
    refs = [k.key_ref for k in await keys_of(session, connection.id)]
    await session.delete(connection)  # key rows cascade
    await session.flush()
    for ref in refs:
        await run_in_threadpool(keystore.delete, ref)


async def check_connection(
    session: AsyncSession, keystore: KeyStore, http: httpx.AsyncClient, connection: Connection
) -> ProbeResult:
    """Test with the first enabled key (or none, for a local provider) and record the result."""
    preset = preset_for(connection.provider_type)
    secret: str | None = None
    for key in await keys_of(session, connection.id):
        if not key.disabled:
            secret = await secret_for(keystore, key)
            break
    if preset.requires_key and secret is None:
        result = ProbeResult(ok=False, error="this connection has no usable key")
        await _record(session, connection, result)
        return result
    return await _test_and_record(session, keystore, http, connection, secret)


async def _test_and_record(
    session: AsyncSession,
    keystore: KeyStore,
    http: httpx.AsyncClient,
    connection: Connection,
    api_key: str | None,
) -> ProbeResult:
    preset = preset_for(connection.provider_type)
    result = await probe(preset, connection.base_url, api_key, connection.extra_headers, http)
    await _record(session, connection, result)
    return result


async def _record(session: AsyncSession, connection: Connection, result: ProbeResult) -> None:
    connection.last_test_ok = result.ok
    connection.last_tested_at = datetime.now(UTC)
    connection.last_test_error = result.error
    if result.ok:
        connection.models = result.models
    await session.flush()
