"""The model catalog: what each connection can reach, with price, context window, capabilities
and curated quality tiers (PRD §10.3).

Three sources are merged per (connection, model): the connection's own live model list (the truth
about what is reachable), the models.dev catalog (price, context, capabilities), and the curated
profiles. A field with no source stays unknown (None); nothing is invented.
"""

import re
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import modelsdev
from app.catalog.measured import model_stats
from app.catalog.modelsdev import CatalogData, CatalogError, CatalogModel
from app.catalog.profiles import Tiers, load_profiles
from app.db.models import Connection, LLMCall
from app.providers.presets import PRESETS

REFRESH_AFTER_S = 24 * 3600


class CatalogEntry(BaseModel):
    connection_id: str
    connection_name: str
    provider_type: str
    model: str
    name: str
    local: bool
    context_window: int | None
    max_output: int | None
    input_per_mtok: Decimal | None
    output_per_mtok: Decimal | None
    tool_call: bool | None
    reasoning: bool | None
    structured_output: bool | None
    deprecated: bool
    # Curated estimates (None when no profile matches the model).
    tiers: Tiers | None
    edit_format: str | None
    quirks: list[str]
    # Where the facts came from, so the UI can say what is unknown.
    in_models_dev: bool
    has_profile: bool
    # Free to call: a `:free` model id (OpenRouter-style aggregators), a local model, or a known
    # price of zero. Not a guess from the provider's name.
    free: bool = False
    # From this account's own call log: "works" (its last call answered), "refused" (the provider
    # refused it: HTTP 401, 402 or 403, e.g. no plan for a paid model), or "unknown".
    access: Literal["works", "refused", "unknown"] = "unknown"
    # Measured on this account (D71): calls, how many answered, the median time of an answer,
    # and the provider's stated per-minute / per-day token limits.
    calls: int = 0
    ok_calls: int = 0
    median_latency_ms: int | None = None
    tpm_limit: int | None = None
    tpd_limit: int | None = None


class CatalogStatus(BaseModel):
    fetched_at: float | None
    age_s: int | None
    models: int
    stale: bool
    profiles_reviewed: str
    profiles_evidence: str


class CatalogService:
    def __init__(
        self,
        directory: Path,
        *,
        http_factory: Callable[[], httpx.AsyncClient] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._directory = directory
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(timeout=30.0))
        self._clock = clock
        self._data: CatalogData | None = None
        self._mtime: float | None = None

    # ---------- data ----------

    def _current(self) -> CatalogData | None:
        """The cache, reloaded if another process (the backend or the crew service) rewrote it."""
        path = self._directory / modelsdev.CACHE_NAME
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return self._data
        if self._data is None or mtime != self._mtime:
            loaded = modelsdev.load_cache(self._directory)
            if loaded is not None:
                self._data, self._mtime = loaded, mtime
        return self._data

    def status(self) -> CatalogStatus:
        data = self._current()
        book = load_profiles()
        age = None if data is None else max(0, round(self._clock() - data.fetched_at))
        return CatalogStatus(
            fetched_at=data.fetched_at if data else None,
            age_s=age,
            models=data.count() if data else 0,
            stale=age is None or age > REFRESH_AFTER_S,
            profiles_reviewed=book.last_reviewed,
            profiles_evidence=book.evidence,
        )

    async def refresh(self) -> CatalogStatus:
        """Fetch the catalog. On failure the old cache stays in use and CatalogError is raised."""
        http = self._http_factory()
        try:
            data = await modelsdev.fetch(http)
        finally:
            await http.aclose()
        data.fetched_at = self._clock()  # one clock for stamping and for measuring age
        modelsdev.save_cache(self._directory, data)
        self._data = data
        self._mtime = (self._directory / modelsdev.CACHE_NAME).stat().st_mtime
        return self.status()

    async def refresh_if_stale(self) -> None:
        """Background refresh at startup. Never raises: offline, the cache is used as it is."""
        if self.status().stale:
            try:
                await self.refresh()
            except CatalogError:
                pass

    def lookup(self, provider_type: str, model: str) -> CatalogModel | None:
        data = self._current()
        return data.find(provider_type, model) if data else None

    def price(self, provider_type: str, model: str) -> tuple[Decimal, Decimal] | None:
        """(input, output) USD per million tokens, if the catalog knows both."""
        found = self.lookup(provider_type, model)
        if found and found.input_per_mtok is not None and found.output_per_mtok is not None:
            return found.input_per_mtok, found.output_per_mtok
        return None

    # ---------- entries ----------

    async def entries(
        self, session: AsyncSession, connection_id: str | None = None
    ) -> list[CatalogEntry]:
        query = select(Connection).where(Connection.enabled.is_(True)).order_by(Connection.name)
        entries: list[CatalogEntry] = []
        access = await access_from_calls(session)
        stats = await model_stats(session)
        for connection in await session.scalars(query):
            if connection_id is not None and str(connection.id) != connection_id:
                continue
            preset = PRESETS[connection.provider_type]
            for model in connection.models:
                entry = self._entry(connection, preset.local, model)
                entry.access = access.get((str(connection.id), model), "unknown")
                measured = stats.get((connection.provider_type, model))
                if measured is not None:
                    entry.calls, entry.ok_calls = measured.calls, measured.ok
                    entry.median_latency_ms = measured.median_latency_ms
                    entry.tpm_limit, entry.tpd_limit = measured.tpm_limit, measured.tpd_limit
                entries.append(entry)
        return entries

    def _entry(self, connection: Connection, local: bool, model: str) -> CatalogEntry:
        known = self.lookup(connection.provider_type, model)
        profile = load_profiles().find(model)
        return CatalogEntry(
            connection_id=str(connection.id),
            connection_name=connection.name,
            provider_type=connection.provider_type,
            model=model,
            name=known.name if known else model,
            local=local,
            context_window=known.context_window if known else None,
            max_output=known.max_output if known else None,
            input_per_mtok=known.input_per_mtok if known else None,
            output_per_mtok=known.output_per_mtok if known else None,
            tool_call=known.tool_call if known else None,
            reasoning=known.reasoning if known else None,
            structured_output=known.structured_output if known else None,
            deprecated=bool(known and known.status == "deprecated"),
            tiers=profile.tiers if profile else None,
            edit_format=profile.edit_format if profile else None,
            quirks=profile.quirks if profile else [],
            in_models_dev=known is not None,
            has_profile=profile is not None,
            free=model.endswith(":free")
            or local
            or (known is not None and known.input_per_mtok == 0 and known.output_per_mtok == 0),
        )


# A provider refusing the account, not the request: no key, a bad key, or no plan for this model.
_REFUSED = re.compile(r"HTTP (?:401|402|403)\b")


async def access_from_calls(session: AsyncSession) -> dict[tuple[str, str], str]:
    """(connection id, model) -> "works" or "refused", from the latest logged call of each pair.
    Measured from this account's own calls; a pair never called is absent ("unknown")."""
    rows = await session.execute(
        select(LLMCall.connection_id, LLMCall.model, LLMCall.error)
        .where(LLMCall.connection_id.is_not(None))
        .order_by(LLMCall.created_at.desc())
        .limit(5000)
    )
    out: dict[tuple[str, str], str] = {}
    for connection_id, model, error in rows:
        key = (str(connection_id), model)
        if key in out:
            continue  # an older call; the latest one decides
        if error is None:
            out[key] = "works"
        elif _REFUSED.search(error):
            out[key] = "refused"
        # any other failure (timeout, rate limit, server error) says nothing about access
    return out
