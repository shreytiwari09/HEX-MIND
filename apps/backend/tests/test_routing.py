"""Per-persona routes: key pools that rotate on a 429, cooldowns, the fallback chain, the events
and `llm_calls` rows they leave, and the guarantee that no secret appears in any of them.
Only the provider's HTTP API is faked; the router, executor, database and events are real."""

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text

from app.db.models import Connection, ConnectionKey, LLMCall, Project, Run
from app.events.log import list_events
from app.providers.base import ChatMessage, LLMRequest
from app.providers.pricing import Pricing
from app.providers.registry import key_ref
from app.providers.routed import RouteExecutor
from app.providers.router import CallContext
from app.providers.routing import Route, Target

SECRETS = {
    "a1": "sk-openai-key-one-000111",
    "a2": "sk-openai-key-two-000222",
    "b1": "sk-ant-key-000333",
}
OPENAI_OK = {
    "choices": [{"message": {"role": "assistant", "content": "from openai"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}
ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "from anthropic"}],
    "usage": {"input_tokens": 12, "output_tokens": 6},
}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Provider:
    """The fake provider APIs. `behave[(host, secret)]` overrides the default success."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (host, which key)
        self.behave: dict[tuple[str, str], Callable[[], httpx.Response]] = {}
        self.respond: Callable[[httpx.Request], httpx.Response] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        secret = request.headers.get("x-api-key") or request.headers.get(
            "authorization", ""
        ).removeprefix("Bearer ")
        which = next((k for k, v in SECRETS.items() if v == secret), "none")
        host = request.url.host
        self.calls.append((host, which))
        if (host, which) in self.behave:
            return self.behave[(host, which)]()
        if self.respond is not None:
            return self.respond(request)
        if host == "api.anthropic.com":
            return httpx.Response(200, json=ANTHROPIC_OK)
        return httpx.Response(200, json=OPENAI_OK)


def rate_limited(retry_after: str | None = "20") -> Callable[[], httpx.Response]:
    headers = {"retry-after": retry_after} if retry_after else {}
    return lambda: httpx.Response(429, headers=headers, json={"error": {"message": "slow down"}})


class World:
    def __init__(self, app: FastAPI, provider: Provider, clock: Clock) -> None:
        self.app, self.provider, self.clock = app, provider, clock
        self.router = app.state.services.providers
        self.keystore = app.state.services.keystore

    async def connection(
        self,
        name: str,
        provider_type: str,
        keys: list[tuple[str, str]],
        base_url: str,
        *,
        enabled: bool = True,
        store: bool = True,
    ) -> Connection:
        async with self.app.state.sessionmaker.begin() as session:
            connection = Connection(
                name=name, provider_type=provider_type, base_url=base_url, enabled=enabled
            )
            session.add(connection)
            await session.flush()
            for position, (label, which) in enumerate(keys):
                key = ConnectionKey(
                    id=uuid.uuid4(), connection_id=connection.id, label=label, position=position
                )
                key.key_ref = key_ref(connection.id, key.id)
                session.add(key)
                if store:
                    self.keystore.set(key.key_ref, SECRETS[which])
            return connection

    async def run_id(self, tmp_path: Path) -> uuid.UUID:
        async with self.app.state.sessionmaker.begin() as session:
            project = Project(name="p", workspace_path=str(tmp_path))
            session.add(project)
            await session.flush()
            run = Run(project_id=project.id, title="r")
            session.add(run)
            await session.flush()
            return run.id

    async def call(self, route: Route, run_id: uuid.UUID | None = None):
        return await self.router.complete(
            LLMRequest(purpose="coder", messages=[ChatMessage(role="user", content="hi")]),
            CallContext(run_id=run_id, agent_id="backend_01", route=route),
        )

    async def events(self, run_id: uuid.UUID, *types: str) -> list[Any]:
        async with self.app.state.sessionmaker() as session:
            events = await list_events(session, run_id)
        return [e for e in events if not types or e.type in types]

    async def llm_calls(self) -> list[LLMCall]:
        async with self.app.state.sessionmaker() as session:
            return list(await session.scalars(select(LLMCall).order_by(LLMCall.created_at)))


def make_world(app: FastAPI) -> World:
    provider, clock = Provider(), Clock()

    async def no_sleep(_: float) -> None:
        return None

    router = app.state.services.providers
    router._sleep = no_sleep  # retries with backoff do not wait in tests
    router.executor = RouteExecutor(
        app.state.sessionmaker,
        app.state.services.keystore,
        Pricing({}),
        transport=httpx.MockTransport(provider),
        clock=clock,
    )
    return World(app, provider, clock)


@pytest.fixture
def world(app: FastAPI) -> World:
    return make_world(app)


OPENAI = "https://api.openai.com/v1"
ANTHROPIC = "https://api.anthropic.com"


async def test_a_429_rotates_to_the_next_key_in_the_pool_and_is_logged(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    world.provider.behave[("api.openai.com", "a1")] = rate_limited("20")
    run_id = await world.run_id(tmp_path)

    result = await world.call(Route((Target(openai.id, "gpt-5"),)), run_id)

    assert result.ok and result.content == "from openai"
    assert (result.provider, result.model, result.key_label) == ("OpenAI", "gpt-5", "key 2")
    # key 1 was tried once (a spare exists, so no backoff), then key 2 answered.
    assert world.provider.calls == [("api.openai.com", "a1"), ("api.openai.com", "a2")]
    [rotation] = await world.events(run_id, "key_rotated")
    assert rotation.payload == {
        "connection": "OpenAI",
        "from_key": "key 1",
        "to_key": "key 2",
        "reason": "rate limit",
    }
    assert rotation.agent_id == "backend_01"
    calls = await world.llm_calls()
    assert [(c.provider, c.key_label, c.connection_id, c.error is None) for c in calls] == [
        ("OpenAI", "key 1", openai.id, False),
        ("OpenAI", "key 2", openai.id, True),
    ]
    assert "429" in (calls[0].error or "")


async def test_a_rate_limited_key_cools_down_for_retry_after_and_then_returns(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    route = Route((Target(openai.id, "gpt-5"),))
    world.provider.behave[("api.openai.com", "a1")] = rate_limited("20")
    await world.call(route)
    world.provider.calls.clear()

    await world.call(route)  # still cooling: goes straight to key 2
    assert world.provider.calls == [("api.openai.com", "a2")]
    [(key_id, (seconds, why))] = world.router.executor.cooling_keys().items()
    assert (seconds, why) == (20, "rate limit")

    world.clock.now += 21  # the cooldown is over
    world.provider.behave.pop(("api.openai.com", "a1"))
    world.provider.calls.clear()
    result = await world.call(route)
    assert world.provider.calls == [("api.openai.com", "a1")] and result.key_label == "key 1"
    assert world.router.executor.cooling_keys() == {} and key_id


async def test_when_every_key_is_limited_it_falls_back_to_the_next_provider(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    claude = await world.connection("Claude", "anthropic", [("key 1", "b1")], ANTHROPIC)
    world.provider.behave[("api.openai.com", "a1")] = rate_limited()
    world.provider.behave[("api.openai.com", "a2")] = rate_limited()
    run_id = await world.run_id(tmp_path)

    result = await world.call(
        Route((Target(openai.id, "gpt-5"), Target(claude.id, "claude-sonnet-5-5"))), run_id
    )

    assert result.ok and result.content == "from anthropic"
    assert (result.provider, result.model) == ("Claude", "claude-sonnet-5-5")
    [fallback] = await world.events(run_id, "provider_fallback")
    assert (fallback.payload["from_provider"], fallback.payload["to_provider"]) == (
        "OpenAI",
        "Claude",
    )
    assert "rate_limit" in fallback.payload["reason"]
    assert len(await world.events(run_id, "key_rotated")) == 1  # key 1 -> key 2 first
    calls = await world.llm_calls()
    assert [(c.provider, c.key_label, c.error is None) for c in calls] == [
        ("OpenAI", "key 1", False),
        ("OpenAI", "key 2", False),
        ("Claude", "key 1", True),
    ]
    assert calls[-1].fallback_from == "OpenAI"


async def test_quota_and_rejected_keys_cool_down_for_longer(world: World) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    route = Route((Target(openai.id, "gpt-5"),))
    world.provider.behave[("api.openai.com", "a1")] = lambda: httpx.Response(
        401, json={"error": {"message": "bad key"}}
    )

    result = await world.call(route)

    assert result.key_label == "key 2"
    [(_, (seconds, why))] = world.router.executor.cooling_keys().items()
    assert (seconds, why) == (900, "auth")  # a rejected key is not retried soon


async def test_a_provider_failure_is_not_blamed_on_the_key(world: World, tmp_path: Path) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    claude = await world.connection("Claude", "anthropic", [("key 1", "b1")], ANTHROPIC)
    world.provider.behave[("api.openai.com", "a1")] = lambda: httpx.Response(500, text="oops")
    run_id = await world.run_id(tmp_path)

    result = await world.call(
        Route((Target(openai.id, "gpt-5"), Target(claude.id, "claude-sonnet-5-5"))), run_id
    )

    # A 500 would repeat on any key, so the spare key is not burned: it goes to the next provider.
    assert result.provider == "Claude"
    assert ("api.openai.com", "a2") not in world.provider.calls
    assert await world.events(run_id, "key_rotated") == []
    assert world.router.executor.cooling_keys() == {}


async def test_the_last_key_retries_with_backoff_before_the_route_falls_back(
    world: World,
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1")], OPENAI)
    claude = await world.connection("Claude", "anthropic", [("key 1", "b1")], ANTHROPIC)
    world.provider.behave[("api.openai.com", "a1")] = rate_limited(None)

    result = await world.call(
        Route((Target(openai.id, "gpt-5"), Target(claude.id, "claude-sonnet-5-5")))
    )

    assert result.provider == "Claude"
    assert world.provider.calls.count(("api.openai.com", "a1")) == 3  # no spare key: it retries


async def test_unusable_targets_are_skipped_and_an_empty_route_says_why(
    world: World, tmp_path: Path
) -> None:
    off = await world.connection("Off", "openai", [("key 1", "a1")], OPENAI, enabled=False)
    nokeys = await world.connection("NoKeys", "groq", [], "https://api.groq.com/openai/v1")
    run_id = await world.run_id(tmp_path)

    result = await world.call(
        Route((Target(off.id, "m"), Target(nokeys.id, "m"), Target(uuid.uuid4(), "m"))), run_id
    )

    assert not result.ok and result.provider == "none"
    assert "disabled" in result.error and "NoKeys: no usable key" in result.error
    assert world.provider.calls == []  # nothing was sent anywhere
    assert (await world.llm_calls())[-1].error == result.error  # and it is on record


async def test_a_key_missing_from_the_key_store_is_reported_not_silently_skipped(
    world: World, tmp_path: Path
) -> None:
    lost = await world.connection("Lost", "openai", [("key 1", "a2")], OPENAI, store=False)
    claude = await world.connection("Claude", "anthropic", [("key 1", "b1")], ANTHROPIC)

    alone = await world.call(Route((Target(lost.id, "m"),)))
    chained = await world.call(
        Route((Target(lost.id, "m"), Target(claude.id, "claude-sonnet-5-5")))
    )

    assert not alone.ok and alone.error.endswith("the key is missing from the key store")
    assert world.provider.calls == [("api.anthropic.com", "b1")]  # the other target served it
    assert chained.provider == "Claude"


async def test_a_connection_without_keys_needs_none_when_it_is_local(world: World) -> None:
    local = await world.connection("LM Studio", "lmstudio", [], "http://127.0.0.1:1234/v1")

    result = await world.call(Route((Target(local.id, "qwen"),)))

    assert result.ok and result.key_label is None
    assert world.provider.calls == [("127.0.0.1", "none")]


async def test_no_secret_reaches_the_database_events_or_errors(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    world.provider.behave[("api.openai.com", "a1")] = lambda: httpx.Response(
        429,
        headers={"retry-after": "5"},
        json={"error": {"message": f"key {SECRETS['a1']} limited"}},
    )
    run_id = await world.run_id(tmp_path)

    await world.call(Route((Target(openai.id, "gpt-5"),)), run_id)

    async with world.app.state.engine.connect() as conn:
        dump = ""
        for table in ("llm_calls", "agent_events", "connections", "connection_keys"):
            dump += str((await conn.execute(text(f"SELECT * FROM {table}"))).all())  # noqa: S608
    # The provider echoed the key in its error body; only the status and its short message are kept.
    for which in ("a1", "a2"):
        assert SECRETS[which] not in dump


async def test_persona_assignments_are_validated_stored_and_become_routes(
    app: FastAPI, client: httpx.AsyncClient, world: World
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key 1", "a1")], OPENAI)
    claude = await world.connection("Claude", "anthropic", [("key 1", "b1")], ANTHROPIC)
    async with app.state.sessionmaker.begin() as session:
        (await session.get(Connection, openai.id)).models = ["gpt-5", "gpt-5-mini"]

    body = {
        "primary": {"connection_id": str(openai.id), "model": "gpt-5"},
        "fallbacks": [{"connection_id": str(claude.id), "model": "claude-sonnet-5-5"}],
        "escalate": {"connection_id": str(openai.id), "model": "gpt-5-mini"},
    }
    saved = await client.put("/api/assignments/backend", json=body)

    assert saved.status_code == 200, saved.text
    assert saved.json()["set_by"] == "user" and saved.json()["escalate"]["model"] == "gpt-5-mini"
    listed = (await client.get("/api/assignments")).json()
    assert [a["persona_id"] for a in listed] == ["backend"]
    from app.providers.assignments import route_for

    async with app.state.sessionmaker() as session:
        route = await route_for(session, "backend")
        assert await route_for(session, "frontend") is None  # unassigned: global order applies
    assert route is not None and route.persona_id == "backend"
    assert [(t.connection_id, t.model) for t in route.targets] == [
        (openai.id, "gpt-5"),
        (claude.id, "claude-sonnet-5-5"),
    ]

    bad_model = {**body, "primary": {"connection_id": str(openai.id), "model": "gpt-9"}}
    assert (await client.put("/api/assignments/backend", json=bad_model)).status_code == 422
    unknown = {**body, "primary": {"connection_id": str(uuid.uuid4()), "model": "x"}}
    assert (await client.put("/api/assignments/backend", json=unknown)).status_code == 422
    assert (await client.put("/api/assignments/nobody", json=body)).status_code == 404
    assert (await client.delete("/api/assignments/backend")).status_code == 204
    assert (await client.delete("/api/assignments/backend")).status_code == 404
    assert json  # (kept for ad-hoc debugging of bodies)


async def test_a_persona_crew_call_is_served_through_its_assigned_route(
    app: FastAPI, client: httpx.AsyncClient, world: World, workspace: Path
) -> None:
    """The exit check in miniature: the Backend persona is assigned a connection with two keys, the
    first is rate limited, and the crew's real model calls rotate to the second."""
    from tests.test_persona_crew import REPORT, feature, run_persona, start

    openai = await world.connection("OpenAI", "openai", [("key 1", "a1"), ("key 2", "a2")], OPENAI)
    assigned = await client.put(
        "/api/assignments/backend",
        json={"primary": {"connection_id": str(openai.id), "model": "gpt-5"}},
    )
    assert assigned.status_code == 200
    world.provider.behave[("api.openai.com", "a1")] = rate_limited("60")

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-5"  # the assigned model, not the global default
        answered = any(m.get("role") == "tool" for m in body["messages"])
        if not answered and body.get("tools"):
            call = {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps(
                        {"path": "src/auth.js", "content": "module.exports = 1\n"}
                    ),
                },
            }
            message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": [call]}
        else:
            message = {"role": "assistant", "content": json.dumps(REPORT)}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            },
        )

    world.provider.respond = respond
    run_id, worktree = await start(app, workspace)

    text = await run_persona(app, run_id, worktree, workspace, "backend", feature("backend"))

    assert json.loads(text)["procedures_followed"] is True
    assert (worktree / "src" / "auth.js").read_text() == "module.exports = 1\n"
    events = await world.events(run_id)
    [rotation] = [e for e in events if e.type == "key_rotated"]
    assert (rotation.payload["from_key"], rotation.payload["to_key"]) == ("key 1", "key 2")
    assert rotation.agent_id == "backend_01"
    done = [e.payload for e in events if e.type == "llm_call_completed"]
    assert {p["provider"] for p in done} == {"OpenAI"} and {p["model"] for p in done} == {"gpt-5"}
    calls = [c for c in await world.llm_calls() if c.run_id == run_id]
    assert [c.key_label for c in calls] == ["key 1", "key 2", "key 2"]
    assert [c.error is None for c in calls] == [False, True, True]
    # After the rotation the pool stayed on key 2 for the rest of the feature.
    assert [which for _, which in world.provider.calls] == ["a1", "a2", "a2"]


# ---------- Auto assignment and escalation (P4 step 4) ----------


async def _auto_world(app: FastAPI) -> dict[str, Connection]:
    from tests.test_catalog import CATALOG, _connection, serve, service

    app.state.services.catalog = service(app.state.settings.data_dir, serve())
    await app.state.services.catalog.refresh()
    del CATALOG  # (the served catalog is the shared test fixture)
    return {
        "claude": await _connection(app, "Claude", "anthropic", ["claude-opus-5-5"]),
        "openai": await _connection(app, "OpenAI", "openai", ["gpt-5"]),
        "google": await _connection(app, "Gemini", "google", ["gemini-3.5-pro"]),
    }


async def test_auto_assign_previews_saves_and_never_overwrites_your_choices(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    connections = await _auto_world(app)

    preview = (await client.post("/api/assignments/auto", json={"dry_run": True})).json()
    assert preview["preset"] == "balanced"
    assert {p["outcome"] for p in preview["proposals"]} == {"would_save"}
    assert (await client.get("/api/assignments")).json() == []  # a preview saves nothing

    saved = (await client.post("/api/assignments/auto", json={})).json()
    assert {p["outcome"] for p in saved["proposals"]} == {"saved"} and len(saved["proposals"]) == 10
    stored = {a["persona_id"]: a for a in (await client.get("/api/assignments")).json()}
    assert len(stored) == 10 and {a["set_by"] for a in stored.values()} == {"auto"}
    pm = stored["pm"]
    assert pm["primary"]["model"] == "gpt-5"  # ties on tier; cheaper wins
    assert "$1.25 in / $10 out per Mtok" in pm["reason"] and pm["reason"].startswith("strongest")
    assert stored["backend"]["reason"].startswith("cheapest model meeting coding ≥4, tool use ≥4")

    # You set one yourself; Auto leaves it alone unless you say otherwise.
    manual = {
        "primary": {"connection_id": str(connections["claude"].id), "model": "claude-opus-5-5"}
    }
    assert (await client.put("/api/assignments/designer", json=manual)).status_code == 200
    again = {
        p["persona_id"]: p
        for p in (await client.post("/api/assignments/auto", json={})).json()["proposals"]
    }
    assert again["designer"]["outcome"] == "kept_manual" and again["pm"]["outcome"] == "saved"
    kept = {a["persona_id"]: a for a in (await client.get("/api/assignments")).json()}
    assert (
        kept["designer"]["set_by"] == "user"
        and kept["designer"]["primary"]["model"] == "claude-opus-5-5"
    )
    forced = (await client.post("/api/assignments/auto", json={"overwrite_manual": True})).json()
    assert {p["persona_id"]: p["outcome"] for p in forced["proposals"]}["designer"] == "saved"
    assert {a["set_by"] for a in (await client.get("/api/assignments")).json()} == {"auto"}


async def test_an_unusable_preset_clears_stale_automatic_choices_but_keeps_manual_ones(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    connections = await _auto_world(app)
    await client.post("/api/assignments/auto", json={})
    manual = {"primary": {"connection_id": str(connections["openai"].id), "model": "gpt-5"}}
    await client.put("/api/assignments/backend", json=manual)

    private = (await client.post("/api/assignments/auto", json={"preset": "private"})).json()

    outcomes = {p["persona_id"]: p["outcome"] for p in private["proposals"]}
    assert outcomes["backend"] == "kept_manual"
    assert {o for pid, o in outcomes.items() if pid != "backend"} == {"none"}  # no local model
    assert all(
        "add a connection" in p["reason"] for p in private["proposals"] if p["outcome"] == "none"
    )
    left = (await client.get("/api/assignments")).json()
    assert [a["persona_id"] for a in left] == ["backend"]  # only the one you chose remains
    assert (await client.post("/api/assignments/auto", json={"preset": "nope"})).status_code == 422


async def test_with_no_connections_every_persona_is_explained(client: httpx.AsyncClient) -> None:
    result = (await client.post("/api/assignments/auto", json={})).json()

    assert {p["outcome"] for p in result["proposals"]} == {"none"}
    assert (await client.get("/api/assignments")).json() == []


async def test_an_escalation_route_tries_the_stronger_model_first_then_the_normal_route(
    app: FastAPI, client: httpx.AsyncClient, world: World
) -> None:
    from app.providers.assignments import route_for

    openai = await world.connection("OpenAI", "openai", [("key 1", "a1")], OPENAI)
    claude = await world.connection("Claude", "anthropic", [("key 1", "b1")], ANTHROPIC)
    body = {
        "primary": {"connection_id": str(openai.id), "model": "gpt-5-mini"},
        "fallbacks": [{"connection_id": str(claude.id), "model": "claude-haiku-5-5"}],
        "escalate": {"connection_id": str(claude.id), "model": "claude-opus-5-5"},
    }
    assert (await client.put("/api/assignments/backend", json=body)).status_code == 200
    plain = {"primary": body["primary"]}
    assert (await client.put("/api/assignments/frontend", json=plain)).status_code == 200

    async with app.state.sessionmaker() as session:
        normal = await route_for(session, "backend")
        stronger = await route_for(session, "backend", escalate=True)
        no_escalation = await route_for(session, "frontend", escalate=True)
        plain_route = await route_for(session, "frontend")

    assert [t.model for t in normal.targets] == ["gpt-5-mini", "claude-haiku-5-5"]
    assert [t.model for t in stronger.targets] == [
        "claude-opus-5-5",
        "gpt-5-mini",
        "claude-haiku-5-5",
    ]
    assert no_escalation == plain_route  # no escalation model: the normal route


async def test_the_last_attempt_runs_on_the_escalation_model(
    app: FastAPI, client: httpx.AsyncClient, world: World, workspace: Path
) -> None:
    from tests.test_persona_crew import REPORT, feature, run_persona, start

    openai = await world.connection("OpenAI", "openai", [("key 1", "a1")], OPENAI)
    await client.put(
        "/api/assignments/backend",
        json={
            "primary": {"connection_id": str(openai.id), "model": "gpt-5-mini"},
            "escalate": {"connection_id": str(openai.id), "model": "gpt-5"},
        },
    )
    models: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        models.append(body["model"])
        message = {"role": "assistant", "content": json.dumps(REPORT)}
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": {}})

    world.provider.respond = respond
    run_id, worktree = await start(app, workspace)

    await run_persona(app, run_id, worktree, workspace, "backend", feature("backend"))
    await run_persona(
        app, run_id, worktree, workspace, "backend", feature("backend"), escalate=True
    )

    assert models == ["gpt-5-mini", "gpt-5"]  # the second call was the escalated attempt
    calls = [c for c in await world.llm_calls() if c.run_id == run_id]
    assert [c.model for c in calls] == ["gpt-5-mini", "gpt-5"]  # on record in llm_calls
