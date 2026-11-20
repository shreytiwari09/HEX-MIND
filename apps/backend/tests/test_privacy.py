"""Privacy modes per project (PRD §13.5): a call that the project's mode forbids is never sent,
whichever way it is routed, and says why."""

import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import LLMCall, Project
from app.providers.base import ChatMessage, Completion, LLMRequest
from app.providers.privacy import ANY, Privacy, privacy_for
from app.providers.router import CallContext
from app.providers.routing import Route, Target
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_routing import ANTHROPIC, OPENAI, World, make_world

LOCAL = "http://127.0.0.1:1234/v1"


@pytest.fixture
def world(app: FastAPI) -> World:
    return make_world(app)


BLOCKED_LOCAL = "blocked by this project's privacy mode (local models only)"
BLOCKED_TRUSTED = "blocked by this project's privacy mode (only trusted providers)"


async def set_mode(
    world: World, run_id: uuid.UUID, mode: str, trusted: list[uuid.UUID] | None = None
) -> None:
    async with world.app.state.sessionmaker.begin() as session:
        from app.db.models import Run

        run = await session.get(Run, run_id)
        project = await session.get(Project, run.project_id)  # type: ignore[union-attr]
        project.privacy_mode = mode  # type: ignore[union-attr]
        project.trusted_connections = [str(t) for t in trusted or []]  # type: ignore[union-attr]


# ---------- the rules ----------


def test_the_rules_for_each_mode() -> None:
    remote, local, listed = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    anything = Privacy("any")
    trusted = Privacy("trusted", frozenset({str(listed)}))
    only_local = Privacy("local")

    assert anything.allows_connection(remote, local=False) and anything.allows_legacy("groq")
    assert trusted.allows_connection(listed, local=False)
    assert not trusted.allows_connection(remote, local=False)
    assert trusted.allows_connection(local, local=True)  # a local model is always fine
    assert not only_local.allows_connection(listed, local=False)
    assert only_local.allows_connection(local, local=True)
    assert only_local.allows_legacy("ollama") and not only_local.allows_legacy("groq")
    assert trusted.allows_legacy("ollama") and not trusted.allows_legacy("gemini")
    assert ANY.mode == "any" and "local models only" in only_local.why_blocked()


async def test_a_call_without_a_run_or_with_an_unknown_run_is_not_restricted(world: World) -> None:
    assert await privacy_for(world.app.state.sessionmaker, None) == ANY
    assert await privacy_for(world.app.state.sessionmaker, uuid.uuid4()) == ANY


async def test_a_mode_the_code_does_not_know_is_read_as_the_strictest(
    world: World, tmp_path: Path
) -> None:
    run_id = await world.run_id(tmp_path)
    await set_mode(world, run_id, "weird")

    assert (await privacy_for(world.app.state.sessionmaker, run_id)).mode == "local"


# ---------- routed calls ----------


async def test_in_local_mode_a_remote_connection_is_skipped_and_the_local_one_answers(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key", "a1")], OPENAI)
    local = await world.connection("LM Studio", "lmstudio", [], LOCAL)
    run_id = await world.run_id(tmp_path)
    await set_mode(world, run_id, "local")

    result = await world.call(Route((Target(openai.id, "gpt-5"), Target(local.id, "qwen"))), run_id)

    assert result.ok and result.provider == "LM Studio"
    assert [host for host, _ in world.provider.calls] == ["127.0.0.1"]  # nothing went to OpenAI


async def test_in_local_mode_with_only_remote_models_nothing_is_sent_and_it_says_why(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key", "a1")], OPENAI)
    run_id = await world.run_id(tmp_path)
    await set_mode(world, run_id, "local")

    result = await world.call(Route((Target(openai.id, "gpt-5"),)), run_id)

    assert not result.ok and BLOCKED_LOCAL in (result.error or "")
    assert "OpenAI" in (result.error or "")
    assert world.provider.calls == []  # fails closed: not a single request left
    [row] = await world.llm_calls()
    assert row.error is not None and BLOCKED_LOCAL in row.error


async def test_in_trusted_mode_only_the_listed_connections_are_used(
    world: World, tmp_path: Path
) -> None:
    anthropic = await world.connection("Anthropic", "anthropic", [("key", "b1")], ANTHROPIC)
    openai = await world.connection("OpenAI", "openai", [("key", "a1")], OPENAI)
    run_id = await world.run_id(tmp_path)
    await set_mode(world, run_id, "trusted", [openai.id])

    result = await world.call(
        Route((Target(anthropic.id, "claude"), Target(openai.id, "gpt-5"))), run_id
    )

    assert result.ok and result.provider == "OpenAI"
    assert [host for host, _ in world.provider.calls] == ["api.openai.com"]

    nothing = await world.call(Route((Target(anthropic.id, "claude"),)), run_id)
    assert not nothing.ok and BLOCKED_TRUSTED in (nothing.error or "")
    assert [host for host, _ in world.provider.calls] == [
        "api.openai.com"
    ]  # still no Anthropic call


async def test_in_any_mode_the_first_connection_is_used_as_before(
    world: World, tmp_path: Path
) -> None:
    anthropic = await world.connection("Anthropic", "anthropic", [("key", "b1")], ANTHROPIC)
    openai = await world.connection("OpenAI", "openai", [("key", "a1")], OPENAI)
    run_id = await world.run_id(tmp_path)

    result = await world.call(
        Route((Target(anthropic.id, "claude"), Target(openai.id, "gpt-5"))), run_id
    )

    assert result.ok and result.provider == "Anthropic"


async def test_a_call_with_no_run_is_not_restricted_even_if_every_project_is_local_only(
    world: World, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key", "a1")], OPENAI)
    run_id = await world.run_id(tmp_path)
    await set_mode(world, run_id, "local")

    result = await world.call(Route((Target(openai.id, "gpt-5"),)), None)  # e.g. a connection test

    assert result.ok


# ---------- the policy chain (providers from .env) ----------


class Named(ScriptedAdapter):
    def __init__(self, name: str) -> None:
        super().__init__(lambda request: Completion(content="ok"))
        self.name = name


async def chain_call(app: FastAPI, adapter_name: str, run_id: uuid.UUID, mode: str):
    use_adapter(app, Named(adapter_name))
    async with app.state.sessionmaker.begin() as session:
        from app.db.models import Run

        run = await session.get(Run, run_id)
        (await session.get(Project, run.project_id)).privacy_mode = mode  # type: ignore[union-attr]
    request = LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])
    return await app.state.provider_router.complete(request, CallContext(run_id=run_id))


async def test_the_policy_chain_obeys_the_mode_too(world: World, tmp_path: Path) -> None:
    run_id = await world.run_id(tmp_path)

    blocked = await chain_call(world.app, "groq", run_id, "local")
    allowed = await chain_call(world.app, "ollama", run_id, "local")
    free = await chain_call(world.app, "groq", run_id, "any")

    assert not blocked.ok and BLOCKED_LOCAL in (blocked.error or "")
    assert allowed.ok and allowed.provider == "ollama"
    assert free.ok


async def test_an_explicit_provider_is_checked_as_well(world: World, tmp_path: Path) -> None:
    run_id = await world.run_id(tmp_path)
    use_adapter(world.app, Named("groq"))
    async with world.app.state.sessionmaker.begin() as session:
        for project in await session.scalars(select(Project)):
            project.privacy_mode = "local"
    request = LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])

    result = await world.app.state.provider_router.complete(
        request, CallContext(run_id=run_id), provider="groq"
    )

    assert not result.ok and result.error and result.error.startswith("not sent: groq: blocked")
    async with world.app.state.sessionmaker() as session:
        assert len(list(await session.scalars(select(LLMCall)))) == 1  # the refusal is logged


# ---------- the API ----------


async def test_the_privacy_api_reads_and_sets_the_mode(
    world: World, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    openai = await world.connection("OpenAI", "openai", [("key", "a1")], OPENAI)
    local = await world.connection("LM Studio", "lmstudio", [], LOCAL)
    project = (await client.post("/api/projects", json={"workspace_path": str(tmp_path)})).json()
    url = f"/api/projects/{project['id']}/privacy"

    default = (await client.get(url)).json()
    assert default["mode"] == "any" and default["trusted_connections"] == []
    assert {c["name"]: c["local"] for c in default["connections"]} == {
        "LM Studio": True,
        "OpenAI": False,
    }

    saved = await client.put(url, json={"mode": "trusted", "trusted_connections": [str(openai.id)]})
    assert saved.status_code == 200
    assert saved.json()["mode"] == "trusted" and saved.json()["trusted_connections"] == [
        str(openai.id)
    ]
    assert (await client.put(url, json={"mode": "local"})).json()["trusted_connections"] == []

    unknown = await client.put(
        url, json={"mode": "trusted", "trusted_connections": [str(uuid.uuid4())]}
    )
    assert unknown.status_code == 422 and "no such connection" in unknown.text
    assert (await client.put(url, json={"mode": "whatever"})).status_code == 422
    missing = f"/api/projects/{uuid.uuid4()}/privacy"
    assert (await client.get(missing)).status_code == 404
    assert (await client.put(missing, json={"mode": "any"})).status_code == 404
    assert local.id  # created above; only listed, never trusted by name


@pytest.mark.parametrize("mode", ["any", "trusted", "local"])
async def test_a_new_project_starts_open_and_the_mode_survives_a_reload(
    world: World, client: httpx.AsyncClient, tmp_path: Path, mode: str
) -> None:
    project = (await client.post("/api/projects", json={"workspace_path": str(tmp_path)})).json()
    url = f"/api/projects/{project['id']}/privacy"
    assert (await client.get(url)).json()["mode"] == "any"

    await client.put(url, json={"mode": mode})

    assert (await client.get(url)).json()["mode"] == mode


# ---------- plugins ----------


class Ollama(ScriptedAdapter):
    name = "ollama"  # a local provider: allowed in every mode


async def test_in_local_mode_a_plugin_with_network_access_is_not_started(
    world: World, client: httpx.AsyncClient, repo: Path
) -> None:
    from app.sandbox.runner import docker_available
    from tests.test_mission_runner import Script, approve, finish, load, new_mission

    if not docker_available()[0]:
        pytest.skip("Docker unavailable")
    safe = {"transport": "stdio", "image": "node:22-alpine", "command": "true", "mount": "none"}
    web = {**safe, "network": "allowlist", "allow_hosts": ["api.example.com"]}
    for plugin_id, config in (("quiet", safe), ("web", web)):
        await client.post(
            "/api/plugins", json={"id": plugin_id, "name": plugin_id, "config": config}
        )
    await client.post(
        "/api/plugins/web/approve", json={"permissions": ["runs commands", "network"]}
    )
    await client.post("/api/plugins/web/enable")
    await client.post("/api/plugins/quiet/enable")
    await client.put("/api/personas/backend", json={"plugins": ["quiet", "web"]})
    use_adapter(world.app, Ollama(Script()))
    mission = await new_mission(client, repo)
    async with world.app.state.sessionmaker.begin() as session:
        for project in await session.scalars(select(Project)):
            project.privacy_mode = "local"

    await approve(client, mission)
    await finish(world.app)

    row, _, run = await load(world.app, mission["id"])
    assert row.status == "completed"
    handoffs = (Path(run.worktree_path or "") / ".hex/mission/handoffs.jsonl").read_text()
    import json

    first = json.loads(handoffs.splitlines()[0])
    assert [p["id"] for p in first["plugins"]] == ["quiet"]  # the network plugin never ran
