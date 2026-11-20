"""Serving a call along a persona's route: key pools and the fallback chain (PRD §10.2, §10.6).

For each target of the route, in order:

1. Take the connection's keys that are not cooling down, in pool order.
2. Call the provider with the first key. On a rate limit, exhausted quota or rejected key, that
   key cools down (for `Retry-After` when the provider sends it) and the next key takes over, with
   a `key_rotated` event. A rate limit rotates at once when a spare key exists instead of waiting.
3. When the connection has no usable key left, or the provider fails some other way (the same
   failure would repeat on any key), fall back to the next target, with a `provider_fallback`
   event.

Rate limits are often per account, so two keys from one account usually share a limit: a pool is
for keys the user deliberately added, and falling back to another provider is the default. Every
attempt is a row in `llm_calls`, with the connection and key *label*, never the key.
"""

import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Connection, ConnectionKey
from app.events.log import EventType, append_event
from app.providers.anthropic import AnthropicAdapter
from app.providers.base import ErrorKind, LLMRequest, LLMResult, ProviderAdapter
from app.providers.ollama import OllamaAdapter
from app.providers.openai_compat import OpenAICompatAdapter
from app.providers.presets import ProviderPreset, preset_for
from app.providers.pricing import Pricing
from app.providers.privacy import privacy_for
from app.providers.secrets import KeyStore, KeyStoreError

if TYPE_CHECKING:
    from app.providers.router import CallContext, ProviderRouter, _Attempt

KEY_ERRORS: frozenset[ErrorKind] = frozenset({"rate_limit", "quota", "auth"})


class RouteExecutor:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        keystore: KeyStore,
        pricing: Pricing,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        rate_limit_cooldown_s: float = 30.0,
        quota_cooldown_s: float = 300.0,
        auth_cooldown_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
        ollama_num_ctx: int = 8192,
        ollama_timeout_s: float = 600.0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._keystore = keystore
        self._pricing = pricing
        self._transport = transport
        self._cooldowns = {
            "rate_limit": rate_limit_cooldown_s,
            "quota": quota_cooldown_s,
            "auth": auth_cooldown_s,
        }
        self._clock = clock
        self._ollama = (ollama_num_ctx, ollama_timeout_s)
        # key id -> (monotonic time it is usable again, why)
        self._cooling: dict[uuid.UUID, tuple[float, str]] = {}
        self._adapters: dict[tuple[object, ...], ProviderAdapter] = {}

    # ---------- state (shown in the Models & Keys screen) ----------

    def cooling_keys(self) -> dict[uuid.UUID, tuple[int, str]]:
        """Key id -> (seconds left, why) for keys currently cooling down."""
        now = self._clock()
        return {
            key_id: (round(until - now), why)
            for key_id, (until, why) in self._cooling.items()
            if until > now
        }

    def _cool(self, key: ConnectionKey, kind: ErrorKind, retry_after: float | None) -> None:
        seconds = retry_after if retry_after and retry_after > 0 else self._cooldowns[kind]
        self._cooling[key.id] = (self._clock() + seconds, kind.replace("_", " "))

    async def aclose(self) -> None:
        for adapter in self._adapters.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        self._adapters.clear()

    # ---------- serving a call ----------

    async def complete(
        self, router: "ProviderRouter", request: LLMRequest, ctx: "CallContext"
    ) -> LLMResult:
        route = ctx.route
        assert route is not None
        previous: tuple[str, str] | None = None
        first_failed: str | None = None
        last: _Attempt | None = None
        skipped: list[str] = []

        privacy = await privacy_for(self._sessionmaker, ctx.run_id)
        for target in route.targets:
            connection, keys = await self._load(target.connection_id)
            if connection is None or not connection.enabled:
                skipped.append("connection removed or disabled")
                continue
            preset = preset_for(connection.provider_type)
            if not privacy.allows_connection(connection.id, local=preset.local):
                skipped.append(f"{connection.name}: {privacy.why_blocked()}")
                continue
            now = self._clock()
            usable = [
                k for k in keys if not k.disabled and self._cooling.get(k.id, (0.0, ""))[0] <= now
            ]
            candidates: list[ConnectionKey | None] = list(usable) if preset.requires_key else [None]
            if not candidates:
                why = self._why_unusable(keys, now)
                skipped.append(f"{connection.name}: {why}")
                first_failed = first_failed or connection.name
                previous = (connection.name, why)
                continue
            if previous is not None:
                await self._emit_fallback(ctx, previous[0], connection.name, previous[1])
            last = await self._try_target(
                router, request, ctx, connection, preset, candidates, target.model, first_failed
            )
            if last.result.ok:
                return last.result
            first_failed = first_failed or connection.name
            previous = (connection.name, f"{last.kind or 'error'}: {last.result.error}")

        if last is not None:
            return last.result
        error = "no usable model on this route" + (f" ({'; '.join(skipped)})" if skipped else "")
        result = LLMResult(
            provider="none",
            model="none",
            content=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            est_cost_usd=None,
            attempts=0,
            error=error,
        )
        await router._log(request, result, ctx)
        return result

    async def _try_target(
        self,
        router: "ProviderRouter",
        request: LLMRequest,
        ctx: "CallContext",
        connection: Connection,
        preset: ProviderPreset,
        candidates: "list[ConnectionKey | None]",
        model: str,
        first_failed: str | None,
    ) -> "_Attempt":
        last: _Attempt | None = None
        for index, key in enumerate(candidates):
            spare = candidates[index + 1] if index + 1 < len(candidates) else None
            adapter = await self._adapter(connection, preset, key, model)
            if adapter is None:  # the secret is missing from the key store
                self._cool(key, "auth", None)  # type: ignore[arg-type]
                if spare is not None:
                    await self._emit_rotation(
                        ctx, connection, key, spare, "missing from the key store"
                    )
                    continue
                return last or await self._missing_key(router, request, ctx, connection, model, key)
            # With a spare key a rate limit rotates immediately instead of backing off.
            last = await router._attempt(
                adapter, request, ctx, first_failed, max_attempts=1 if spare is not None else None
            )
            if last.result.ok or key is None or last.kind not in KEY_ERRORS:
                return last
            assert last.kind is not None
            self._cool(key, last.kind, last.retry_after)
            if spare is None:
                return last
            await self._emit_rotation(ctx, connection, key, spare, last.kind.replace("_", " "))
        assert last is not None
        return last

    async def _missing_key(
        self,
        router: "ProviderRouter",
        request: LLMRequest,
        ctx: "CallContext",
        connection: Connection,
        model: str,
        key: "ConnectionKey | None",
    ) -> "_Attempt":
        from app.providers.router import _Attempt

        result = LLMResult(
            provider=connection.name,
            model=model,
            content=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            est_cost_usd=None,
            attempts=0,
            error=f"{connection.name}: the key is missing from the key store",
            connection_id=connection.id,
            key_label=key.label if key else None,
        )
        await router._log(request, result, ctx)
        return _Attempt(result, "auth", None)

    def _why_unusable(self, keys: list[ConnectionKey], now: float) -> str:
        enabled = [k for k in keys if not k.disabled]
        if not enabled:
            return "no usable key"
        reasons = {self._cooling[k.id][1] for k in enabled if k.id in self._cooling}
        return "every key is cooling down" + (f" ({', '.join(sorted(reasons))})" if reasons else "")

    # ---------- adapters and data ----------

    async def _load(
        self, connection_id: uuid.UUID
    ) -> tuple[Connection | None, list[ConnectionKey]]:
        async with self._sessionmaker() as session:
            connection = await session.get(Connection, connection_id)
            if connection is None:
                return None, []
            keys = list(
                await session.scalars(
                    select(ConnectionKey)
                    .where(ConnectionKey.connection_id == connection_id)
                    .order_by(ConnectionKey.position, ConnectionKey.created_at)
                )
            )
            return connection, keys

    async def _adapter(
        self,
        connection: Connection,
        preset: ProviderPreset,
        key: "ConnectionKey | None",
        model: str,
    ) -> ProviderAdapter | None:
        cache_key = (connection.id, connection.updated_at, key.id if key else None, model)
        cached = self._adapters.get(cache_key)
        if cached is not None:
            return cached
        secret: str | None = None
        if key is not None:
            try:
                secret = await run_in_threadpool(self._keystore.get, key.key_ref)
            except KeyStoreError:
                secret = None
            if secret is None:
                return None
        adapter: ProviderAdapter
        if preset.adapter == "anthropic":
            adapter = AnthropicAdapter(
                name=connection.name,
                base_url=connection.base_url,
                api_key=secret,
                model=model,
                pricing=self._pricing,
                extra_headers=connection.extra_headers,
                pricing_name=preset.type,
                transport=self._transport,
            )
        elif preset.adapter == "ollama":
            adapter = OllamaAdapter(
                connection.base_url,
                model,
                num_ctx=self._ollama[0],
                timeout_s=self._ollama[1],
                transport=self._transport,
            )
            adapter.name = connection.name
        else:
            adapter = OpenAICompatAdapter(
                name=connection.name,
                base_url=connection.base_url,
                api_key=secret,
                model=model,
                pricing=self._pricing,
                transport=self._transport,
                requires_thought_signatures=preset.thought_signatures,
                extra_headers=connection.extra_headers,
                pricing_name=preset.type,
                requires_key=preset.requires_key,
            )
        adapter.connection_id = connection.id  # type: ignore[attr-defined]
        adapter.key_label = key.label if key else None  # type: ignore[attr-defined]
        self._adapters[cache_key] = adapter
        return adapter

    # ---------- events ----------

    async def _emit_rotation(
        self,
        ctx: "CallContext",
        connection: Connection,
        source: "ConnectionKey | None",
        target: ConnectionKey,
        reason: str,
    ) -> None:
        if ctx.run_id is None:
            return
        async with self._sessionmaker.begin() as session:
            await append_event(
                session,
                ctx.run_id,
                EventType.KEY_ROTATED,
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                payload={
                    "connection": connection.name,
                    "from_key": source.label if source else "-",
                    "to_key": target.label,
                    "reason": reason,
                },
            )

    async def _emit_fallback(
        self, ctx: "CallContext", source: str, target: str, reason: str
    ) -> None:
        if ctx.run_id is None:
            return
        async with self._sessionmaker.begin() as session:
            await append_event(
                session,
                ctx.run_id,
                EventType.PROVIDER_FALLBACK,
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                payload={"from_provider": source, "to_provider": target, "reason": reason[:300]},
            )
