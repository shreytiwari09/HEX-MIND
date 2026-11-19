"""The native Anthropic adapter: request translation, response parsing, error classification."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.providers.anthropic import AnthropicAdapter
from app.providers.base import ChatMessage, LLMRequest, ProviderError, ToolCall
from app.providers.pricing import Pricing

KEY = "sk-ant-secret-0123456789"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
]


def adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    key: str | None = KEY,
    pricing: Pricing | None = None,
) -> tuple[AnthropicAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    made = AnthropicAdapter(
        api_key=key,
        model="claude-sonnet-5-5",
        pricing=pricing or Pricing({}),
        transport=httpx.MockTransport(record),
    )
    return made, seen


def ok(content: list[dict[str, Any]], usage: dict[str, int] | None = None) -> httpx.Response:
    return httpx.Response(200, json={"content": content, "usage": usage or {}})


async def test_the_request_is_translated_to_the_messages_api() -> None:
    sent, seen = adapter(
        lambda r: ok([{"type": "text", "text": "done"}], {"input_tokens": 10, "output_tokens": 3})
    )
    request = LLMRequest(
        purpose="coder",
        max_tokens=500,
        temperature=0.1,
        stop=["END"],
        tools=TOOLS,
        messages=[
            ChatMessage(role="system", content="You are a backend engineer."),
            ChatMessage(role="system", content="Be careful."),
            ChatMessage(role="user", content="Add a route."),
            ChatMessage(
                role="assistant",
                content="Let me look.",
                tool_calls=[
                    ToolCall(id="t1", name="read_file", arguments={"path": "a.js"}),
                    ToolCall(id="t2", name="read_file", arguments={"path": "b.js"}),
                ],
            ),
            ChatMessage(role="tool", tool_call_id="t1", name="read_file", content="A"),
            ChatMessage(role="tool", tool_call_id="t2", name="read_file", content="B"),
        ],
    )

    result = await sent.complete(request)

    http = seen[0]
    assert http.url.path == "/v1/messages"
    assert http.headers["x-api-key"] == KEY and http.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in http.headers
    body = json.loads(http.content)
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 500
    assert body["temperature"] == 0.1 and body["stop_sequences"] == ["END"]
    assert body["system"] == "You are a backend engineer.\n\nBe careful."
    assert body["tool_choice"] == {"type": "auto"}
    assert body["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][1]["content"] == [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.js"}},
        {"type": "tool_use", "id": "t2", "name": "read_file", "input": {"path": "b.js"}},
    ]
    # Both results of the turn travel together in one user message.
    assert body["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "A"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "B"},
    ]
    assert (result.content, result.input_tokens, result.output_tokens) == ("done", 10, 3)


async def test_consecutive_user_turns_merge_and_tool_results_come_first() -> None:
    sent, seen = adapter(lambda r: ok([{"type": "text", "text": "x"}]))
    await sent.complete(
        LLMRequest(
            purpose="coder",
            messages=[
                ChatMessage(role="user", content="first"),
                ChatMessage(role="assistant", tool_calls=[ToolCall(id="t1", name="read_file")]),
                ChatMessage(role="user", content="and also this"),
                ChatMessage(role="tool", tool_call_id="t1", content="result"),
            ],
        )
    )

    messages = json.loads(seen[0].content)["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [b["type"] for b in messages[2]["content"]] == ["tool_result", "text"]


async def test_a_json_schema_goes_into_the_system_prompt() -> None:
    sent, seen = adapter(lambda r: ok([{"type": "text", "text": "{}"}]))
    await sent.complete(
        LLMRequest(
            purpose="router",
            json_schema={"type": "object"},
            messages=[
                ChatMessage(role="system", content="Classify."),
                ChatMessage(role="user", content="hi"),
            ],
        )
    )

    system = json.loads(seen[0].content)["system"]
    assert system.startswith("Classify.") and '{"type": "object"}' in system


async def test_the_reply_becomes_text_tool_calls_and_token_counts() -> None:
    pricing = Pricing(
        {
            "models": {
                "anthropic/claude-sonnet-5-5": {"input_per_mtok": 2.0, "output_per_mtok": 10.0}
            }
        }
    )
    sent, _ = adapter(
        lambda r: ok(
            [
                {"type": "text", "text": "I will read it. "},
                {"type": "text", "text": "Now."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {"path": "a.js"},
                },
            ],
            {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50},
        ),
        pricing=pricing,
    )

    result = await sent.complete(
        LLMRequest(purpose="coder", messages=[ChatMessage(role="user", content="go")])
    )

    assert result.content == "I will read it. Now."
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("toolu_1", "read_file", {"path": "a.js"})
    ]
    assert (result.input_tokens, result.output_tokens) == (1000, 50)  # cached input counts as input
    assert result.est_cost_usd is not None and float(result.est_cost_usd) == pytest.approx(0.0025)


async def test_a_model_missing_from_the_price_table_gets_no_cost() -> None:
    sent, _ = adapter(
        lambda r: ok([{"type": "text", "text": "x"}], {"input_tokens": 5, "output_tokens": 5})
    )

    result = await sent.complete(
        LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])
    )

    assert result.est_cost_usd is None  # never a guessed price


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(401, json={"error": {"message": "invalid x-api-key"}}), "auth"),
        (httpx.Response(403, json={"error": {"message": "forbidden"}}), "auth"),
        (httpx.Response(404, json={"error": {"message": "model: nope"}}), "model_unavailable"),
        (
            httpx.Response(
                429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}}
            ),
            "rate_limit",
        ),
        (httpx.Response(529, json={"error": {"message": "Overloaded"}}), "server"),
        (httpx.Response(500, json={"error": {"message": "oops"}}), "server"),
        (
            httpx.Response(
                400, json={"error": {"message": "Your credit balance is too low to access the API"}}
            ),
            "quota",
        ),
        (httpx.Response(400, json={"error": {"message": "max_tokens: required"}}), "bad_request"),
    ],
)
async def test_errors_are_classified_for_the_router(response: httpx.Response, kind: str) -> None:
    sent, _ = adapter(lambda r: response)

    with pytest.raises(ProviderError) as caught:
        await sent.complete(
            LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])
        )

    assert caught.value.kind == kind
    assert caught.value.retryable is (kind in ("rate_limit", "server"))
    assert KEY not in str(caught.value)
    if response.status_code == 429:
        assert caught.value.retry_after == 7


async def test_only_the_providers_short_error_message_is_kept() -> None:
    body = {
        "error": {"message": "bad", "echo": "x" * 5000},
        "request": {"messages": "SECRET PROMPT"},
    }
    sent, _ = adapter(lambda r: httpx.Response(400, json=body))

    with pytest.raises(ProviderError) as caught:
        await sent.complete(
            LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])
        )

    assert str(caught.value) == "anthropic HTTP 400: bad"


async def test_network_failures_are_retryable_kinds_and_carry_no_url_or_key() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out calling {request.url} with {KEY}")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused {KEY}")

    for handler, kind in ((timeout, "timeout"), (refused, "connection")):
        sent, _ = adapter(handler)
        with pytest.raises(ProviderError) as caught:
            await sent.complete(
                LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])
            )
        assert caught.value.kind == kind and caught.value.retryable is True
        assert KEY not in str(caught.value) and "api.anthropic.com" not in str(caught.value)


async def test_without_a_key_it_is_unconfigured_and_fails_as_an_auth_error() -> None:
    sent, seen = adapter(lambda r: ok([]), key=None)

    assert sent.configured is False
    assert (await sent.health()).configured is False
    with pytest.raises(ProviderError) as caught:
        await sent.complete(
            LLMRequest(purpose="chat", messages=[ChatMessage(role="user", content="hi")])
        )
    assert caught.value.kind == "auth" and seen == []


async def test_health_checks_the_key_and_the_model() -> None:
    def listing(models: list[str]) -> Callable[[httpx.Request], httpx.Response]:
        return lambda r: httpx.Response(200, json={"data": [{"id": m} for m in models]})

    good, _ = adapter(listing(["claude-sonnet-5-5"]))
    missing, _ = adapter(listing(["claude-opus-5-5"]))
    rejected, _ = adapter(lambda r: httpx.Response(401))
    unreachable, _ = adapter(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")))

    assert (await good.health()).available is True
    assert (await missing.health()).detail == "model not offered by the provider"
    assert (await rejected.health()).detail == "API key rejected"
    assert (await unreachable.health()).available is False
