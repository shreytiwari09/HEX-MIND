"""The response cache for replays (PRD §15.2): an exact-match store of model answers.

A call is keyed by the provider, the model and the exact request (the same bytes the audit trail
hashes). With the cache on, a call whose key is stored is answered from the store and no provider
is called; a call that is not stored goes live and its answer is stored. The point is
reproducibility and cost: an experiment can be repeated, or a stopped sweep continued, without
paying again for what was already answered.

- `off` (default): no lookups, nothing stored.
- `readwrite`: use a stored answer when there is one, otherwise call and store.
- `replay_only`: use stored answers only; a call that is not stored fails (`bad_request`), so a
  replay can never spend money by accident.

A replayed call is a row in `llm_calls` marked `replayed`, carrying the tokens, price and latency
measured when it was really made, so a replayed run reports the same figures as the original.
Only successful answers are stored. The request text is not stored, only its hash; the answer is.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ResponseCacheRow
from app.providers.base import Completion, LLMRequest

CacheMode = Literal["off", "readwrite", "replay_only"]


def cache_key(provider: str, model: str, request: LLMRequest) -> str:
    """sha256 over the provider, the model and exactly what is sent to the model."""
    body = f"{provider}\n{model}\n{request.model_dump_json(exclude_none=True)}"
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class Stored:
    completion: Completion
    latency_ms: int


class ResponseCache:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], mode: CacheMode) -> None:
        self._sessionmaker = sessionmaker
        self.mode: CacheMode = mode

    @property
    def active(self) -> bool:
        return self.mode != "off"

    async def get(self, key: str) -> Stored | None:
        async with self._sessionmaker() as session:
            row = await session.get(ResponseCacheRow, key)
        if row is None:
            return None
        completion = Completion.model_validate(row.completion)
        if row.est_cost_usd is not None:
            completion.est_cost_usd = Decimal(row.est_cost_usd)
        return Stored(completion, row.latency_ms)

    async def put(
        self, key: str, provider: str, model: str, completion: Completion, latency_ms: int
    ) -> None:
        if self.mode != "readwrite":
            return
        values = {
            "key": key,
            "provider": provider,
            "model": model,
            "completion": completion.model_dump(mode="json", exclude={"est_cost_usd"}),
            "est_cost_usd": completion.est_cost_usd,
            "latency_ms": latency_ms,
        }
        async with self._sessionmaker.begin() as session:
            await session.execute(
                insert(ResponseCacheRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["key"])
            )

    async def stats(self) -> dict[str, int]:
        async with self._sessionmaker() as session:
            entries = await session.scalar(select(func.count()).select_from(ResponseCacheRow))
        return {"entries": int(entries or 0)}

    async def clear(self) -> int:
        async with self._sessionmaker.begin() as session:
            return (await session.execute(delete(ResponseCacheRow))).rowcount or 0
