"""Connections and key pools: creation with a live test, key handling, and the guarantee that a
secret never leaves the key store (not in responses, the database, or error text)."""

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.providers.secrets import KeyStoreError, MemoryKeyStore

GOOD = "sk-good-key-0123456789"
GOOD_2 = "sk-good-key-second-987654"
BAD = "sk-bad-key-0123456789abc"

OPENAI_LIST = {"data": [{"id": "gpt-5"}, {"id": "gpt-5-mini"}]}
ANTHROPIC_LIST = {"data": [{"id": "claude-opus-5-5"}, {"id": "claude-sonnet-5-5"}]}
GOOGLE_LIST = {"data": [{"id": "models/gemini-3.5-pro"}, {"id": "models/gemini-3.5-flash"}]}
OLLAMA_TAGS = {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.2:3b"}]}


class Provider:
    """A fake provider API behind `services.connection_http`. Records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.valid_keys = {GOOD, GOOD_2}
        self.fail: Callable[[httpx.Request], httpx.Response] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            return self.fail(request)
        key = request.headers.get("x-api-key") or request.headers.get(
            "authorization", ""
        ).removeprefix("Bearer ")
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=OLLAMA_TAGS)
        if key not in self.valid_keys:
            # Providers often echo the rejected key: the app must never repeat it.
            return httpx.Response(401, json={"error": {"message": f"Invalid key {key}"}})
        if request.url.host == "api.anthropic.com":
            return httpx.Response(200, json=ANTHROPIC_LIST)
        if "generativelanguage" in request.url.host:
            return httpx.Response(200, json=GOOGLE_LIST)
        return httpx.Response(200, json=OPENAI_LIST)


@pytest.fixture
def provider(app: FastAPI) -> Provider:
    fake = Provider()
    app.state.services.connection_http = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    return fake


async def create(client: httpx.AsyncClient, **body: object) -> httpx.Response:
    return await client.post("/api/connections", json=body)


async def everything_stored(app: FastAPI) -> str:
    """All text in the tables that could hold a secret, as one string."""
    async with app.state.engine.connect() as conn:
        rows = []
        for table in ("connections", "connection_keys"):
            result = await conn.execute(text(f"SELECT * FROM {table}"))  # noqa: S608
            rows += [str(tuple(row)) for row in result]
    return "\n".join(rows)


async def test_provider_types_are_listed(client: httpx.AsyncClient) -> None:
    types = {t["type"]: t for t in (await client.get("/api/provider-types")).json()}

    assert {"openrouter", "anthropic", "openai", "google", "nvidia", "deepseek", "glm"} <= set(
        types
    )
    assert {"groq", "ollama", "lmstudio", "custom"} <= set(types)
    assert types["ollama"]["requires_key"] is False and types["ollama"]["local"] is True
    assert types["custom"]["base_url"] is None and types["openrouter"]["requires_key"] is True


async def test_a_new_connection_is_tested_lists_its_models_and_keeps_the_key_secret(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider
) -> None:
    response = await create(
        client,
        name="OpenAI",
        provider_type="openai",
        api_key=GOOD,
        extra_headers={"X-Title": "HEX"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    connection = body["connection"]
    assert connection["base_url"] == "https://api.openai.com/v1"
    assert connection["models"] == ["gpt-5", "gpt-5-mini"]
    assert connection["last_test"]["ok"] is True and connection["last_test"]["error"] is None
    assert connection["keys"] == [
        {"id": connection["keys"][0]["id"], "label": "key 1", "position": 0, "disabled": False}
    ]
    assert body["test"]["ok"] is True and body["test"]["models"] == ["gpt-5", "gpt-5-mini"]
    # The provider saw the key (as a Bearer token) and our extra header.
    sent = provider.requests[0]
    assert str(sent.url) == "https://api.openai.com/v1/models"
    assert sent.headers["authorization"] == f"Bearer {GOOD}" and sent.headers["x-title"] == "HEX"
    # The secret is in the key store only: not in any response, and not in the database.
    ref = f"connection-{connection['id']}-{connection['keys'][0]['id']}"
    assert app.state.services.keystore.get(ref) == GOOD
    listed = await client.get("/api/connections")
    assert GOOD not in response.text and GOOD not in listed.text
    assert GOOD not in await everything_stored(app)


async def test_each_provider_family_is_probed_the_way_it_expects(
    client: httpx.AsyncClient, provider: Provider
) -> None:
    anthropic = (await create(client, name="A", provider_type="anthropic", api_key=GOOD)).json()
    google = (await create(client, name="G", provider_type="google", api_key=GOOD)).json()
    ollama = await create(client, name="L", provider_type="ollama")

    a = provider.requests[0]
    assert str(a.url) == "https://api.anthropic.com/v1/models?limit=1000"
    assert a.headers["x-api-key"] == GOOD and a.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in a.headers
    assert anthropic["connection"]["models"] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert google["connection"]["models"] == [
        "gemini-3.5-flash",
        "gemini-3.5-pro",
    ]  # "models/" removed
    assert ollama.status_code == 201
    assert ollama.json()["connection"]["models"] == ["llama3.2:3b", "qwen2.5-coder:7b"]
    assert ollama.json()["connection"]["keys"] == []
    assert str(provider.requests[-1].url) == "http://127.0.0.1:11434/api/tags"
    assert "authorization" not in provider.requests[-1].headers


async def test_a_key_the_provider_rejects_is_not_saved_and_never_echoed(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider
) -> None:
    response = await create(client, name="OpenAI", provider_type="openai", api_key=BAD)

    assert response.status_code == 422
    assert "rejected this key" in response.json()["detail"]
    assert BAD not in response.text  # the provider echoed it; we did not
    assert (await client.get("/api/connections")).json() == []
    assert app.state.services.keystore._secrets == {}


async def test_an_unreachable_provider_still_creates_the_connection_so_it_can_be_fixed(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider
) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route to host for {request.url} with {GOOD}")

    provider.fail = down
    response = await create(
        client, name="Mine", provider_type="custom", base_url="https://llm.example/v1", api_key=GOOD
    )

    assert response.status_code == 201
    connection = response.json()["connection"]
    assert connection["last_test"]["ok"] is False
    assert "could not connect" in connection["last_test"]["error"]
    assert GOOD not in response.text
    assert len(connection["keys"]) == 1  # the key was not rejected, so it is kept
    assert len(app.state.services.keystore._secrets) == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"name": "X", "provider_type": "nope"}, "unknown provider type"),
        ({"name": "X", "provider_type": "custom", "api_key": GOOD}, "needs a base URL"),
        (
            {
                "name": "X",
                "provider_type": "custom",
                "base_url": "http://llm.example/v1",
                "api_key": GOOD,
            },
            "plain http",
        ),
        (
            {
                "name": "X",
                "provider_type": "custom",
                "base_url": "https://user:pw@llm.example/v1",
                "api_key": GOOD,
            },
            "username or password",
        ),
        (
            {
                "name": "X",
                "provider_type": "custom",
                "base_url": "ftp://llm.example",
                "api_key": GOOD,
            },
            "http://",
        ),
        (
            {
                "name": "X",
                "provider_type": "openai",
                "api_key": GOOD,
                "extra_headers": {"Authorization": "Bearer x"},
            },
            "looks like a credential",
        ),
        (
            {
                "name": "X",
                "provider_type": "openai",
                "api_key": GOOD,
                "extra_headers": {"X-Api-Key": "x"},
            },
            "looks like a credential",
        ),
    ],
)
async def test_unsafe_connections_are_refused(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider, body: dict, message: str
) -> None:
    response = await client.post("/api/connections", json=body)

    assert response.status_code == 422
    assert message in response.text
    assert GOOD not in response.text
    assert (await client.get("/api/connections")).json() == []
    assert provider.requests == []  # nothing was sent anywhere


async def test_local_http_is_allowed_with_a_key_and_names_must_be_unique(
    client: httpx.AsyncClient, provider: Provider
) -> None:
    local = await create(
        client,
        name="LM",
        provider_type="lmstudio",
        base_url="http://localhost:1234/v1",
        api_key=GOOD,
    )
    again = await create(client, name="LM", provider_type="openai", api_key=GOOD)

    assert local.status_code == 201
    assert again.status_code == 409


async def test_validation_errors_do_not_echo_the_key(
    client: httpx.AsyncClient, provider: Provider
) -> None:
    response = await client.post(
        "/api/connections", json={"provider_type": "openai", "api_key": GOOD}
    )

    assert response.status_code == 422
    assert GOOD not in response.text


async def test_keys_can_be_added_to_the_pool_and_removed(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider
) -> None:
    connection = (await create(client, name="O", provider_type="openai", api_key=GOOD)).json()[
        "connection"
    ]
    url = f"/api/connections/{connection['id']}/keys"

    added = await client.post(url, json={"api_key": GOOD_2, "label": "work account"})
    rejected = await client.post(url, json={"api_key": BAD})

    assert added.status_code == 201
    keys = added.json()["connection"]["keys"]
    assert [(k["label"], k["position"]) for k in keys] == [("key 1", 0), ("work account", 1)]
    assert rejected.status_code == 422 and BAD not in rejected.text
    assert len(app.state.services.keystore._secrets) == 2
    assert GOOD_2 not in added.text and GOOD_2 not in await everything_stored(app)

    removed = await client.delete(f"{url}/{keys[0]['id']}")
    assert [k["label"] for k in removed.json()["keys"]] == ["work account"]
    assert list(app.state.services.keystore._secrets.values()) == [GOOD_2]  # the first is gone
    missing = await client.delete(f"{url}/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


async def test_deleting_a_connection_deletes_its_keys_from_the_key_store(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider
) -> None:
    connection = (await create(client, name="O", provider_type="openai", api_key=GOOD)).json()[
        "connection"
    ]
    await client.post(f"/api/connections/{connection['id']}/keys", json={"api_key": GOOD_2})
    assert len(app.state.services.keystore._secrets) == 2

    response = await client.delete(f"/api/connections/{connection['id']}")

    assert response.status_code == 204
    assert app.state.services.keystore._secrets == {}
    assert (await client.get("/api/connections")).json() == []
    assert "connection_keys" in await _table_names(app)
    assert await everything_stored(app) == ""


async def _table_names(app: FastAPI) -> str:
    async with app.state.engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )
        return " ".join(row[0] for row in result)


async def test_retesting_updates_the_result_and_reports_a_missing_key(
    client: httpx.AsyncClient, provider: Provider
) -> None:
    connection = (await create(client, name="O", provider_type="openai", api_key=GOOD)).json()[
        "connection"
    ]
    provider.valid_keys.clear()  # the provider revokes the key

    revoked = await client.post(f"/api/connections/{connection['id']}/test")
    assert revoked.json()["test"]["ok"] is False
    assert revoked.json()["connection"]["last_test"]["error"] == "the provider rejected the key"
    assert revoked.json()["connection"]["models"] == ["gpt-5", "gpt-5-mini"]  # last good list kept

    await client.delete(f"/api/connections/{connection['id']}/keys/{connection['keys'][0]['id']}")
    none = await client.post(f"/api/connections/{connection['id']}/test")
    assert none.json()["test"]["error"] == "this connection has no usable key"


async def test_connections_can_be_renamed_and_disabled(
    client: httpx.AsyncClient, provider: Provider
) -> None:
    one = (await create(client, name="One", provider_type="openai", api_key=GOOD)).json()[
        "connection"
    ]
    await create(client, name="Two", provider_type="groq", api_key=GOOD)

    updated = await client.put(
        f"/api/connections/{one['id']}", json={"name": "Primary", "enabled": False}
    )
    clash = await client.put(f"/api/connections/{one['id']}", json={"name": "Two"})

    assert updated.json()["name"] == "Primary" and updated.json()["enabled"] is False
    assert clash.status_code == 409


async def test_a_key_store_failure_saves_nothing_and_says_why(
    app: FastAPI, client: httpx.AsyncClient, provider: Provider
) -> None:
    class Broken(MemoryKeyStore):
        def set(self, ref: str, secret: str) -> None:
            raise KeyStoreError(
                "no secure key store is available on this system, so keys cannot be saved"
            )

    app.state.services.keystore = Broken()

    response = await create(client, name="O", provider_type="openai", api_key=GOOD)

    assert response.status_code == 503
    assert "no secure key store" in response.json()["detail"] and GOOD not in response.text
    assert (await client.get("/api/connections")).json() == []


async def test_the_api_needs_the_token(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as anon:
        assert (await anon.get("/api/connections")).status_code == 401
        assert (await anon.post("/api/connections", json={})).status_code == 401
        assert (await anon.get("/api/provider-types")).status_code == 401
    assert json  # (json is used by the helpers above when debugging)
