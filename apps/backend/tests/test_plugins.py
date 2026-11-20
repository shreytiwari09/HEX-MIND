"""The plugin manager (PRD §11.7): permission labels come from the configuration, risky plugins
need the user's approval for exactly that configuration, and nothing unapproved is ready."""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.plugins import registry
from app.plugins.config import (
    PluginConfig,
    PluginConfigError,
    approval_reasons,
    check_allowed,
    config_hash,
    permissions,
)

IMAGES = ["node:22-alpine", "python:3.11-slim"]
SAFE = {
    "transport": "stdio",
    "image": "node:22-alpine",
    "command": "node server.js",
    "mount": "read",
}
NETWORK = {
    "transport": "stdio",
    "image": "node:22-alpine",
    "command": "node server.js",
    "network": "allowlist",
    "allow_hosts": ["api.example.com"],
}
WRITER = {**SAFE, "mount": "write"}
REMOTE = {"transport": "http", "url": "https://mcp.example.com/mcp"}


def add_body(plugin_id: str = "notes", config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": plugin_id,
        "name": "Notes",
        "description": "Keeps notes.",
        "config": config or SAFE,
    }


# ---------- labels and risk come from the configuration ----------


@pytest.mark.parametrize(
    ("config", "labels", "reasons"),
    [
        ({**SAFE, "mount": "none"}, ["runs commands"], 0),
        (SAFE, ["runs commands", "reads files"], 0),
        (WRITER, ["runs commands", "reads files", "writes files"], 1),
        (NETWORK, ["runs commands", "network"], 1),
        (
            {**NETWORK, "mount": "write"},
            ["runs commands", "reads files", "writes files", "network"],
            2,
        ),
        (REMOTE, ["network"], 1),
    ],
)
def test_labels_and_the_reasons_for_approval_follow_from_the_configuration(
    config: dict[str, Any], labels: list[str], reasons: int
) -> None:
    parsed = PluginConfig.model_validate(config)

    assert permissions(parsed) == labels
    assert len(approval_reasons(parsed)) == reasons


def test_a_remote_plugin_is_a_network_plugin_for_exactly_its_host() -> None:
    config = PluginConfig.model_validate(REMOTE)

    assert (config.network, config.allow_hosts) == ("allowlist", ["mcp.example.com"])
    assert "mcp.example.com" in approval_reasons(config)[0]


def test_the_hash_changes_with_anything_that_matters_and_not_with_order() -> None:
    base = PluginConfig.model_validate(NETWORK)

    assert config_hash(base) == config_hash(PluginConfig.model_validate(NETWORK))
    for change in (
        {"command": "node other.js"},
        {"image": "python:3.11-slim"},
        {"allow_hosts": ["api.example.com", "cdn.example.com"]},
        {"mount": "read"},
        {"network": "none", "allow_hosts": []},
    ):
        assert config_hash(PluginConfig.model_validate({**NETWORK, **change})) != config_hash(base)
    two = PluginConfig.model_validate(
        {**NETWORK, "allow_hosts": ["a.example.com", "b.example.com"]}
    )
    one = PluginConfig.model_validate(
        {**NETWORK, "allow_hosts": ["b.example.com", "a.example.com"]}
    )
    assert config_hash(two) != config_hash(one)  # a different list is a different configuration


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"transport": "stdio", "command": "x"}, "needs an image and a command"),
        ({"transport": "stdio", "image": "node:22-alpine"}, "needs an image and a command"),
        ({**SAFE, "command": "a\nb"}, "one non-empty line"),
        ({**SAFE, "url": "https://x.example.com"}, "no url"),
        ({**SAFE, "network": "allowlist"}, "the hosts it may reach"),
        ({**SAFE, "allow_hosts": ["a.example.com"]}, "only used when network"),
        ({**NETWORK, "allow_hosts": ["https://api.example.com"]}, "not a host name"),
        ({**NETWORK, "allow_hosts": ["*.example.com"]}, "not a host name"),
        ({**NETWORK, "allow_hosts": ["api.example.com:443"]}, "not a host name"),
        ({**NETWORK, "allow_hosts": ["localhost"]}, "not a host name"),
        ({"transport": "http"}, "needs a url"),
        ({"transport": "http", "url": "http://mcp.example.com"}, "https"),
        ({"transport": "http", "url": "https://user:pw@mcp.example.com"}, "no credentials"),
        ({"transport": "http", "url": "https://localhost/mcp"}, "public host"),
        ({"transport": "http", "url": "https://192.168.1.5/mcp"}, "public host"),
        ({"transport": "http", "url": "https://127.0.0.1/mcp"}, "public host"),
        ({**REMOTE, "image": "node:22-alpine"}, "runs elsewhere"),
        ({**REMOTE, "mount": "read"}, "runs elsewhere"),
    ],
)
def test_a_bad_configuration_is_refused_with_the_reason(
    config: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        PluginConfig.model_validate(config)


def test_only_allowed_images_may_run_a_plugin() -> None:
    check_allowed(PluginConfig.model_validate(SAFE), IMAGES)
    with pytest.raises(PluginConfigError, match="image 'ubuntu:24.04' is not allowed"):
        check_allowed(PluginConfig.model_validate({**SAFE, "image": "ubuntu:24.04"}), IMAGES)


# ---------- adding and the approval gate ----------


async def test_a_low_risk_plugin_is_added_disabled_and_can_be_enabled_without_approval(
    client: httpx.AsyncClient,
) -> None:
    added = await client.post("/api/plugins", json=add_body())

    body = added.json()
    assert added.status_code == 201
    assert (body["status"], body["needs_approval"], body["enabled"]) == ("disabled", False, False)
    assert body["permissions"] == ["runs commands", "reads files"] and body["reasons"] == []
    enabled = (await client.post("/api/plugins/notes/enable")).json()
    assert (enabled["status"], enabled["enabled"]) == ("ready", True)
    disabled = (await client.post("/api/plugins/notes/disable")).json()
    assert disabled["status"] == "disabled"
    assert (
        await client.post("/api/plugins/notes/approve", json={"permissions": body["permissions"]})
    ).status_code == 409


async def test_a_risky_plugin_is_blocked_until_you_approve_exactly_what_it_can_do(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.post("/api/plugins", json=add_body("web", NETWORK))).json()
    assert (body["status"], body["needs_approval"], body["approved"]) == (
        "needs_approval",
        True,
        False,
    )
    assert body["permissions"] == ["runs commands", "network"]
    assert body["reasons"] == ["it can send data to api.example.com"]

    blocked = await client.post("/api/plugins/web/enable")
    assert blocked.status_code == 409 and "needs your approval first" in blocked.json()["detail"]
    assert "api.example.com" in blocked.json()["detail"]
    assert (await client.get("/api/plugins/web")).json()["enabled"] is False

    wrong = await client.post("/api/plugins/web/approve", json={"permissions": ["runs commands"]})
    assert wrong.status_code == 409 and "not the ones you were shown" in wrong.json()["detail"]
    approved = (
        await client.post(
            "/api/plugins/web/approve", json={"permissions": ["network", "runs commands"]}
        )
    ).json()
    assert approved["approved"] is True and approved["approved_at"] is not None
    assert approved["status"] == "disabled"  # approved, still not switched on
    assert (await client.post("/api/plugins/web/enable")).json()["status"] == "ready"


async def test_changing_what_a_plugin_can_do_removes_its_approval_and_switches_it_off(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/api/plugins", json=add_body("web", NETWORK))
    await client.post(
        "/api/plugins/web/approve", json={"permissions": ["runs commands", "network"]}
    )
    await client.post("/api/plugins/web/enable")

    renamed = (await client.put("/api/plugins/web", json={"name": "Web helper"})).json()
    assert (renamed["status"], renamed["approved"]) == ("ready", True)  # a name changes nothing

    widened = (
        await client.put(
            "/api/plugins/web",
            json={"config": {**NETWORK, "allow_hosts": ["api.example.com", "evil.example.com"]}},
        )
    ).json()
    assert (widened["status"], widened["approved"], widened["enabled"]) == (
        "needs_approval",
        False,
        False,
    )
    assert widened["approved_at"] is None
    assert (await client.post("/api/plugins/web/enable")).status_code == 409

    same = await client.put("/api/plugins/web", json={"config": widened["config"]})
    assert same.json()["status"] == "needs_approval"  # still not approved
    await client.post("/api/plugins/web/approve", json={"permissions": widened["permissions"]})
    assert (await client.post("/api/plugins/web/enable")).json()["status"] == "ready"


async def test_a_plugin_that_writes_files_needs_approval_even_without_network(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.post("/api/plugins", json=add_body("fixer", WRITER))).json()

    assert body["needs_approval"] is True
    assert body["reasons"] == ["third-party code can change files in the project"]
    assert (await client.post("/api/plugins/fixer/enable")).status_code == 409


async def test_bad_plugins_are_refused(client: httpx.AsyncClient) -> None:
    for body, status, message in [
        (add_body("Bad Id"), 422, "lowercase"),
        (add_body("x"), 422, "at least 2 characters"),
        (add_body("notes", {**SAFE, "image": "ubuntu:24.04"}), 422, "is not allowed"),
        (add_body("notes", {**SAFE, "command": ""}), 422, "one non-empty line"),
        (add_body("notes", {"transport": "carrier-pigeon"}), 422, "transport"),
    ]:
        response = await client.post("/api/plugins", json=body)
        assert response.status_code == status, body
        assert message in response.text, response.text
    assert (await client.post("/api/plugins", json=add_body())).status_code == 201
    assert (await client.post("/api/plugins", json=add_body())).status_code == 409
    assert (await client.get("/api/plugins/ghost")).status_code == 404
    assert (await client.post("/api/plugins/ghost/enable")).status_code == 404
    assert (await client.delete("/api/plugins/ghost")).status_code == 404


async def test_listing_shows_every_plugin(client: httpx.AsyncClient) -> None:
    await client.post("/api/plugins", json=add_body("a-notes"))
    await client.post("/api/plugins", json=add_body("b-web", NETWORK))

    listed = (await client.get("/api/plugins")).json()

    assert [(p["id"], p["status"]) for p in listed] == [
        ("a-notes", "disabled"),
        ("b-web", "needs_approval"),
    ]


# ---------- attaching to personas ----------


async def test_a_plugin_is_attached_to_personas_and_cannot_be_removed_while_attached(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/api/plugins", json=add_body())

    attached = await client.put("/api/personas/backend", json={"plugins": ["notes"]})

    assert attached.status_code == 200 and attached.json()["plugins"] == ["notes"]
    assert (await client.get("/api/plugins/notes")).json()["personas"] == ["backend"]
    refused = await client.delete("/api/plugins/notes")
    assert refused.status_code == 409 and "still attached to: backend" in refused.json()["detail"]
    assert (await client.put("/api/personas/backend", json={"plugins": []})).status_code == 200
    assert (await client.delete("/api/plugins/notes")).status_code == 204
    assert (await client.get("/api/plugins/notes")).status_code == 404


async def test_only_existing_plugins_can_be_attached(client: httpx.AsyncClient) -> None:
    ghost = await client.put("/api/personas/backend", json={"plugins": ["ghost"]})
    assert ghost.status_code == 422 and "no such plugin: ghost" in ghost.json()["detail"]

    await client.post("/api/plugins", json=add_body())
    twice = await client.put("/api/personas/backend", json={"plugins": ["notes", "notes"]})
    assert twice.status_code == 422 and "attached once" in twice.json()["detail"]


async def test_only_ready_plugins_are_ever_started_for_a_persona(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    for body in (add_body("a-safe"), add_body("b-web", NETWORK), add_body("c-off")):
        await client.post("/api/plugins", json=body)
    await client.post("/api/plugins/a-safe/enable")
    await client.post(
        "/api/plugins/b-web/approve", json={"permissions": ["runs commands", "network"]}
    )
    await client.post("/api/plugins/b-web/enable")
    await client.post("/api/plugins/c-off/enable")
    await client.post("/api/plugins/c-off/disable")
    await client.put(
        "/api/plugins/b-web", json={"config": {**NETWORK, "command": "node changed.js"}}
    )

    async with app.state.sessionmaker() as session:
        ready = await registry.ready_for(session, ["a-safe", "b-web", "c-off", "ghost", "a-safe"])

    # b-web changed after its approval, c-off is disabled, ghost does not exist.
    assert [row.id for row in ready] == ["a-safe"]


async def test_the_options_list_the_images_a_plugin_may_use(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/plugins/options")).json()

    assert body == {"images": IMAGES}
