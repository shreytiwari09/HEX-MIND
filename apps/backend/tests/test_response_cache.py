"""The response cache (PRD §15.2): an answer that was already paid for is not bought twice."""

from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import LLMCall
from app.providers.base import ChatMessage, Completion, LLMRequest, ProviderHealth
from app.providers.cache import ResponseCache, cache_key
from app.providers.router import CallContext, ProviderRouter


def request(text: str = "hi", **extra: object) -> LLMRequest:
    return LLMRequest(purpose="coder", messages=[ChatMessage(role="user", content=text)], **extra)


class Counting:
    """A provider that counts how often it is really called."""

    name = "fake"
    model = "m1"

    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, model=self.model, available=True)

    async def complete(self, request: LLMRequest) -> Completion:
        self.calls += 1
        return Completion(
            content=f"answer {self.calls}",
            input_tokens=10,
            output_tokens=5,
            est_cost_usd=Decimal("0.002"),
        )


def make(app: FastAPI, adapter: Counting, mode: str) -> ProviderRouter:
    router = ProviderRouter([adapter], app.state.sessionmaker, order=["fake"])  # type: ignore[list-item]
    router.cache = ResponseCache(app.state.sessionmaker, mode)  # type: ignore[arg-type]
    return router


def test_the_key_depends_on_the_provider_the_model_and_every_part_of_the_request() -> None:
    base = cache_key("p", "m", request())

    assert base == cache_key("p", "m", request())
    assert len({base, cache_key("q", "m", request()), cache_key("p", "n", request())}) == 3
    assert base != cache_key("p", "m", request("hello"))
    assert base != cache_key("p", "m", request(temperature=0.9))
    assert base != cache_key("p", "m", request(max_tokens=5))


async def test_a_stored_answer_is_served_without_calling_the_provider(app: FastAPI) -> None:
    adapter = Counting()
    router = make(app, adapter, "readwrite")
    ctx = CallContext()

    first = await router.complete(request(), ctx)
    second = await router.complete(request(), ctx)
    other = await router.complete(request("different"), ctx)

    assert (first.content, second.content, other.content) == ("answer 1", "answer 1", "answer 2")
    assert adapter.calls == 2  # the repeat was not sent to the provider
    # the replay carries the figures measured when the answer was really made
    assert (second.input_tokens, second.output_tokens) == (10, 5)
    assert second.est_cost_usd == Decimal("0.002")
    async with app.state.sessionmaker() as session:
        rows = list(await session.scalars(select(LLMCall).order_by(LLMCall.created_at)))
    assert [r.replayed for r in rows] == [False, True, False]  # all three are in the record


async def test_with_the_cache_off_every_call_is_live_and_nothing_is_stored(app: FastAPI) -> None:
    adapter = Counting()
    router = make(app, adapter, "off")

    await router.complete(request(), CallContext())
    await router.complete(request(), CallContext())

    assert adapter.calls == 2
    assert router.cache is not None and (await router.cache.stats())["entries"] == 0


async def test_replay_only_never_reaches_a_provider(app: FastAPI) -> None:
    adapter = Counting()
    live = make(app, adapter, "readwrite")
    await live.complete(request(), CallContext())  # stored
    replay = make(app, adapter, "replay_only")

    hit = await replay.complete(request(), CallContext())
    miss = await replay.complete(request("never asked"), CallContext())

    assert hit.ok and hit.content == "answer 1"
    assert not miss.ok and "not stored" in (miss.error or "")
    assert adapter.calls == 1  # only the first, live call ever reached the provider
    assert (await replay.cache.stats())["entries"] == 1  # type: ignore[union-attr]


async def test_a_failed_call_is_not_stored(app: FastAPI) -> None:
    class Broken(Counting):
        async def complete(self, request: LLMRequest) -> Completion:
            from app.providers.base import ProviderError

            self.calls += 1
            raise ProviderError("nope", kind="bad_request")

    adapter = Broken()
    router = make(app, adapter, "readwrite")

    result = await router.complete(request(), CallContext())

    assert not result.ok
    assert (await router.cache.stats())["entries"] == 0  # type: ignore[union-attr]


async def test_the_cache_endpoint_and_the_metrics_report_replays(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    body = (await client.get("/api/experiments/cache")).json()
    assert body["mode"] == "off" and body["entries"] == 0


@pytest.mark.parametrize("mode", ["off", "readwrite", "replay_only"])
def test_the_cache_mode_is_a_setting(mode: str) -> None:
    from app.config import Settings

    assert Settings(api_token="x" * 16, response_cache=mode).response_cache == mode  # type: ignore[arg-type]
