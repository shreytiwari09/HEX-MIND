"""The model catalog: models.dev parsing, the offline cache, curated profiles, the merged view per
connection, and cost estimates for models the hand-kept price table does not list."""

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.catalog import modelsdev
from app.catalog.modelsdev import CatalogData, CatalogError, parse
from app.catalog.profiles import load_profiles
from app.catalog.service import CatalogService
from app.db.models import Connection, ConnectionKey, LLMCall
from app.providers.base import ChatMessage, LLMRequest
from app.providers.pricing import Pricing
from app.providers.registry import key_ref
from app.providers.routed import RouteExecutor
from app.providers.router import CallContext
from app.providers.routing import Route, Target


def model(model_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": extra.pop("name", model_id.upper()),
        "tool_call": True,
        "reasoning": False,
        "limit": {"context": 200_000, "output": 8_000},
        "cost": {"input": 3, "output": 15, "cache_read": 0.3},
        **extra,
    }


# Shaped like https://models.dev/api.json (checked against the real file), trimmed.
CATALOG: dict[str, Any] = {
    "anthropic": {
        "id": "anthropic",
        "models": {
            "claude-sonnet-4-5": model(
                "claude-sonnet-4-5", name="Claude Sonnet 4.5", status="deprecated"
            ),
            "claude-opus-5-5": model("claude-opus-5-5", cost={"input": 4, "output": 20}),
        },
    },
    "openai": {
        "id": "openai",
        "models": {"gpt-5": model("gpt-5", cost={"input": 1.25, "output": 10})},
    },
    "google": {"id": "google", "models": {"gemini-3.5-pro": model("gemini-3.5-pro")}},
    "openrouter": {
        "id": "openrouter",
        "models": {"anthropic/claude-sonnet-5-5": model("anthropic/claude-sonnet-5-5")},
    },
    "some-other-provider": {"id": "x", "models": {"m": model("m")}},  # not one we map
}


def serve(payload: Any = None, status: int = 200, body: bytes | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and not request.content  # a plain GET: nothing is sent
        assert "authorization" not in request.headers
        if body is not None:
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=CATALOG if payload is None else payload)

    return handler


def service(tmp_path: Path, handler, clock=lambda: 1_000_000.0) -> CatalogService:
    return CatalogService(
        tmp_path / "catalog",
        http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def test_only_supported_providers_are_kept_and_malformed_rows_are_skipped() -> None:
    payload = {
        **CATALOG,
        "groq": {
            "models": {
                "ok": model("ok", cost={"input": "0.5", "output": 1}),
                "no-id": {"name": "x"},
                "bad-type": "not a dict",
                "bad-cost": model("bad-cost", cost={"input": -1, "output": "free"}),
                "bad-limit": model("bad-limit", limit={"context": True, "output": "big"}),
            }
        },
    }

    parsed = parse(payload)

    assert set(parsed) == {"anthropic", "openai", "google", "openrouter", "groq"}
    assert set(parsed["groq"]) == {"ok", "bad-cost", "bad-limit"}
    assert parsed["groq"]["ok"].input_per_mtok == Decimal("0.5")
    assert parsed["groq"]["bad-cost"].input_per_mtok is None  # negative: unknown, not guessed
    assert parsed["groq"]["bad-cost"].output_per_mtok is None
    assert parsed["groq"]["bad-limit"].context_window is None  # a bool is not a number
    sonnet = parsed["anthropic"]["claude-sonnet-4-5"]
    assert (sonnet.name, sonnet.status, sonnet.context_window) == (
        "Claude Sonnet 4.5",
        "deprecated",
        200_000,
    )
    with pytest.raises(CatalogError):
        parse(["not", "an", "object"])


def test_models_are_found_under_the_ids_providers_actually_use() -> None:
    data = CatalogData(fetched_at=0, models=parse(CATALOG))

    assert data.find("anthropic", "claude-opus-5-5").id == "claude-opus-5-5"
    assert data.find("anthropic", "claude-sonnet-4-5-20250929").id == "claude-sonnet-4-5"  # dated
    assert data.find("anthropic", "claude-opus-5-5-latest").id == "claude-opus-5-5"
    assert data.find("google", "models/gemini-3.5-pro").id == "gemini-3.5-pro"  # Google prefix
    assert data.find("openrouter", "anthropic/claude-sonnet-5-5") is not None
    assert data.find("openai", "claude-opus-5-5") is None  # not that provider's model
    assert data.find("ollama", "llama3") is None and data.find("custom", "gpt-5") is None


def test_profiles_match_in_order_and_an_unknown_model_has_none() -> None:
    book = load_profiles()

    assert book.evidence == "estimate"  # curated, not measured, and the file says so
    assert book.find("gpt-5-mini").match == "gpt-5*mini*"  # before the general gpt-5*
    assert book.find("gpt-5").match == "gpt-5*"
    assert book.find("anthropic/claude-sonnet-5-5").match == "claude-sonnet*"  # OpenRouter prefix
    assert book.find("models/gemini-3.5-pro").edit_format == "fenced"
    assert "thought signatures" in book.find("gemini-3.5-flash").quirks[0]
    assert book.find("qwen2.5-coder:7b").edit_format == "whole_file"
    assert book.find("some-model-nobody-profiled") is None
    assert all(1 <= p.tiers.coding <= 5 for p in book.profiles)


async def test_fetch_failures_are_reported_in_plain_words(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    for handler, message in [
        (serve(status=503), "HTTP 503"),
        (serve(body=b"<html>"), "did not return JSON"),
        (serve(payload={"anthropic": {"models": {}}}), "no models"),
        (refuse, "could not reach models.dev"),
        (slow, "did not answer in time"),
    ]:
        with pytest.raises(CatalogError, match=message):
            await service(tmp_path, handler).refresh()
    assert not (tmp_path / "catalog").exists()  # a failed fetch writes nothing


async def test_an_oversized_download_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modelsdev, "MAX_BYTES", 50)

    with pytest.raises(CatalogError, match="larger than expected"):
        await service(tmp_path, serve()).refresh()


async def test_refresh_saves_a_cache_that_other_processes_and_offline_runs_use(
    tmp_path: Path,
) -> None:
    online = service(tmp_path, serve())
    status = await online.refresh()

    assert (status.models, status.stale, status.age_s) == (5, False, 0)
    assert (tmp_path / "catalog" / "models.dev.json").is_file()

    # A different process (the crew service) reads the same file without any network.
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    other = service(tmp_path, offline)
    assert other.price("openai", "gpt-5") == (Decimal("1.25"), Decimal("10"))
    # A failed refresh keeps the cache that is there.
    with pytest.raises(CatalogError):
        await other.refresh()
    assert other.price("openai", "gpt-5") is not None
    await other.refresh_if_stale()  # fresh, so it does not even try, and never raises


async def test_a_stale_cache_is_refreshed_in_the_background_and_a_damaged_one_ignored(
    tmp_path: Path,
) -> None:
    now = [1_000_000.0]
    svc = service(tmp_path, serve(), clock=lambda: now[0])
    assert svc.status().models == 0 and svc.status().stale is True  # nothing cached yet
    await svc.refresh_if_stale()
    assert svc.status().models == 5

    now[0] += 25 * 3600
    assert svc.status().stale is True
    await svc.refresh_if_stale()
    assert svc.status().stale is False

    (tmp_path / "catalog" / "models.dev.json").write_text("{ not json", encoding="utf-8")
    fresh_process = service(tmp_path, serve(status=503), clock=lambda: now[0])
    assert fresh_process.price("openai", "gpt-5") is None  # damaged: treated as no cache
    await fresh_process.refresh_if_stale()  # offline and damaged: still never raises


async def _connection(
    app: FastAPI, name: str, provider_type: str, models: list[str], **extra: Any
) -> Connection:
    async with app.state.sessionmaker.begin() as session:
        connection = Connection(
            name=name,
            provider_type=provider_type,
            base_url="https://x.example/v1",
            models=models,
            **extra,
        )
        session.add(connection)
        await session.flush()
        return connection


async def test_the_catalog_view_merges_what_each_connection_reaches_with_what_is_known(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.services.catalog = service(app.state.settings.data_dir, serve())
    await app.state.services.catalog.refresh()
    claude = await _connection(
        app,
        "Claude",
        "anthropic",
        ["claude-opus-5-5", "claude-sonnet-4-5-20250929", "claude-mystery-1"],
    )
    local = await _connection(app, "Local", "ollama", ["qwen2.5-coder:7b"])
    await _connection(app, "Off", "openai", ["gpt-5"], enabled=False)
    await _connection(app, "Untested", "groq", [])

    entries = (await client.get("/api/catalog")).json()

    by_model = {(e["connection_name"], e["model"]): e for e in entries}
    assert set(by_model) == {
        ("Claude", "claude-opus-5-5"),
        ("Claude", "claude-sonnet-4-5-20250929"),
        ("Claude", "claude-mystery-1"),
        ("Local", "qwen2.5-coder:7b"),
    }  # a disabled connection and one that was never tested contribute nothing
    opus = by_model[("Claude", "claude-opus-5-5")]
    assert (opus["input_per_mtok"], opus["output_per_mtok"]) == ("4", "20")
    assert (opus["context_window"], opus["tool_call"], opus["in_models_dev"]) == (
        200_000,
        True,
        True,
    )
    assert (
        opus["tiers"] == {"reasoning": 5, "coding": 5, "ui": 4, "tool_use": 5}
        and opus["has_profile"]
    )
    assert by_model[("Claude", "claude-sonnet-4-5-20250929")]["deprecated"] is True
    # A model nobody has data on stays unknown: no price, no context, no tiers.
    mystery = by_model[("Claude", "claude-mystery-1")]
    assert mystery["input_per_mtok"] is None and mystery["context_window"] is None
    assert mystery["in_models_dev"] is False
    # A local model has no API price; its profile still tells how to edit with it.
    qwen = by_model[("Local", "qwen2.5-coder:7b")]
    assert qwen["local"] is True and qwen["input_per_mtok"] is None
    assert (qwen["edit_format"], qwen["has_profile"], qwen["in_models_dev"]) == (
        "whole_file",
        True,
        False,
    )

    only = (await client.get("/api/catalog", params={"connection_id": str(local.id)})).json()
    assert [e["connection_name"] for e in only] == ["Local"] and claude.id


async def test_status_and_refresh_endpoints(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.services.catalog = service(app.state.settings.data_dir, serve())

    before = (await client.get("/api/catalog/status")).json()
    assert (before["models"], before["stale"], before["fetched_at"]) == (0, True, None)
    assert before["profiles_evidence"] == "estimate"

    after = await client.post("/api/catalog/refresh")
    assert (
        after.status_code == 200 and after.json()["models"] == 5 and after.json()["stale"] is False
    )

    app.state.services.catalog = service(app.state.settings.data_dir, serve(status=500))
    failed = await client.post("/api/catalog/refresh")
    assert failed.status_code == 502 and "HTTP 500" in failed.json()["detail"]
    assert (await client.get("/api/catalog/status")).json()["models"] == 5  # the cache survived


async def test_a_model_missing_from_the_price_table_is_priced_from_the_catalog(
    app: FastAPI, tmp_path: Path
) -> None:
    catalog = service(tmp_path, serve())
    await catalog.refresh()
    pricing = Pricing({"models": {"openai/gpt-5": {"input_per_mtok": 99, "output_per_mtok": 99}}})
    pricing.fallback = catalog.price

    assert pricing.cost("openai", "gpt-5", 1_000_000, 1_000_000) == Decimal(198)  # the table wins
    assert pricing.cost("anthropic", "claude-opus-5-5", 1_000_000, 500_000) == Decimal(
        14
    )  # catalog
    assert pricing.cost("anthropic", "claude-mystery-1", 10, 10) is None  # unknown: never guessed
    assert pricing.cost("anthropic", "claude-opus-5-5", None, 5) is None


async def test_a_routed_call_records_a_cost_from_the_catalog(app: FastAPI, tmp_path: Path) -> None:
    catalog = service(tmp_path, serve())
    await catalog.refresh()
    pricing = Pricing({})
    pricing.fallback = catalog.price

    def provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 100_000},
            },
        )

    router = app.state.services.providers
    router.executor = RouteExecutor(
        app.state.sessionmaker,
        app.state.services.keystore,
        pricing,
        transport=httpx.MockTransport(provider),
    )
    async with app.state.sessionmaker.begin() as session:
        connection = Connection(
            name="OpenAI", provider_type="openai", base_url="https://api.openai.com/v1"
        )
        session.add(connection)
        await session.flush()
        key = ConnectionKey(id=uuid.uuid4(), connection_id=connection.id, label="key 1", position=0)
        key.key_ref = key_ref(connection.id, key.id)
        session.add(key)
        app.state.services.keystore.set(key.key_ref, "sk-test-0123456789abcdef")

    result = await router.complete(
        LLMRequest(purpose="coder", messages=[ChatMessage(role="user", content="hi")]),
        CallContext(route=Route((Target(connection.id, "gpt-5"),))),
    )

    # gpt-5 is $1.25 in / $10 out per million: 1M in + 0.1M out.
    assert result.est_cost_usd == Decimal("2.25")
    async with app.state.sessionmaker() as session:
        [call] = list(await session.scalars(select(LLMCall)))
    assert call.est_cost_usd == Decimal("2.250000") and json


async def test_each_model_shows_whether_it_is_free_and_what_this_account_saw_when_calling_it(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Measured from the account's own call log, never guessed (PRD D69)."""
    app.state.services.catalog = service(app.state.settings.data_dir, serve())
    harbor = await _connection(
        app, "Harbor", "custom", ["paid-model", "deepseek:free", "used", "flaky", "untried"]
    )

    def call(model: str, error: str | None) -> LLMCall:
        return LLMCall(
            purpose="coder", provider="Harbor", model=model, latency_ms=5,
            connection_id=harbor.id, error=error,
        )  # fmt: skip

    async with app.state.sessionmaker.begin() as session:
        session.add(call("paid-model", "Harbor HTTP 402: No active plan was found"))
        session.add(call("used", "Harbor HTTP 402: no plan"))
    async with app.state.sessionmaker.begin() as session:  # later calls decide
        session.add(call("used", None))
        session.add(call("flaky", "Harbor HTTP 503: overloaded"))  # says nothing about access

    response = await client.get("/api/catalog")
    by_model = {e["model"]: e for e in response.json() if e["connection_name"] == "Harbor"}

    assert by_model["paid-model"]["access"] == "refused"
    assert by_model["used"]["access"] == "works"
    assert by_model["flaky"]["access"] == "unknown"
    assert by_model["untried"]["access"] == "unknown"
    assert by_model["deepseek:free"]["free"] is True and by_model["untried"]["free"] is False


async def test_speed_failures_and_stated_limits_are_measured_from_the_call_log(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """D71: a Groq limit stated in a refusal applies to a Groq connection's same model, even when
    the call went through the built-in `.env` provider."""
    from app.catalog.measured import role_loads

    app.state.services.catalog = service(app.state.settings.data_dir, serve())
    await _connection(app, "Groq", "groq", ["openai/gpt-oss-120b"])
    too_big = (
        "groq HTTP 413: Request too large for model `openai/gpt-oss-120b` on tokens per minute "
        "(TPM): Limit 8000, Requested 9100"
    )
    per_day = "groq HTTP 429: Rate limit reached on tokens per day (TPD): Limit 200000, Used 199527"
    async with app.state.sessionmaker.begin() as session:
        for latency, error in [(900, None), (1100, None), (5000, too_big), (300, per_day)]:
            session.add(LLMCall(
                purpose="coder", provider="groq", model="openai/gpt-oss-120b",
                latency_ms=latency, error=error, persona_id="backend", input_tokens=3000,
            ))  # fmt: skip

    [groq] = [
        e for e in (await client.get("/api/catalog")).json() if e["connection_name"] == "Groq"
    ]

    assert (groq["calls"], groq["ok_calls"], groq["median_latency_ms"]) == (4, 2, 1000)
    assert (groq["tpm_limit"], groq["tpd_limit"]) == (8000, 200000)
    async with app.state.sessionmaker() as session:
        loads = await role_loads(session)
    assert (loads["backend"].typical, loads["backend"].measured) == (3000, True)
    assert loads["researcher"].measured is False  # never ran here: the default
