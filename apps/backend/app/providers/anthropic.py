"""Native Anthropic Messages API adapter (PRD §10.1, decision D11: no LiteLLM).

Translates the provider-neutral request (OpenAI-style messages and tool definitions) to the
Messages API and back, and classifies errors the way the ProviderRouter expects. It implements
the same `ProviderAdapter` protocol as the OpenAI-compatible adapter, so the router treats both
alike.

- System messages become the top-level `system` field.
- An assistant turn's tool calls become `tool_use` blocks; the matching tool results become
  `tool_result` blocks in one user message (the API requires all results of a turn together).
- Consecutive messages of one role are merged, because the API needs alternating roles.
"""

import json
import uuid
from typing import Any

import httpx

from app.providers.base import (
    ChatMessage,
    Completion,
    ErrorKind,
    LLMRequest,
    ProviderError,
    ProviderHealth,
    ToolCall,
)
from app.providers.pricing import Pricing

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
# Exhausted prepaid credit comes back as a 400, not a 429.
_QUOTA_HINTS = ("credit balance", "billing", "usage limit")


class AnthropicAdapter:
    def __init__(
        self,
        *,
        name: str = "anthropic",
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None,
        model: str,
        pricing: Pricing,
        extra_headers: dict[str, str] | None = None,
        pricing_name: str | None = None,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self._pricing_name = pricing_name or name
        self.model = model
        self._api_key = api_key
        self._pricing = pricing
        headers = {"anthropic-version": ANTHROPIC_VERSION, **(extra_headers or {})}
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            headers=headers,
            follow_redirects=False,  # never replay the key at a redirect target
        )
        self.rate_limit: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> ProviderHealth:
        if not self.configured:
            return ProviderHealth(
                provider=self.name,
                available=False,
                configured=False,
                model=self.model,
                detail="no API key",
            )
        try:
            response = await self._client.get("/v1/models", params={"limit": 1000}, timeout=5.0)
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail=type(exc).__name__,
            )
        if response.status_code in (401, 403):
            return ProviderHealth(
                provider=self.name, available=False, model=self.model, detail="API key rejected"
            )
        if response.status_code != 200:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail=f"HTTP {response.status_code}",
            )
        ids = {m.get("id") for m in response.json().get("data", [])}
        if self.model not in ids:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail="model not offered by the provider",
            )
        return ProviderHealth(provider=self.name, available=True, model=self.model)

    async def complete(self, request: LLMRequest) -> Completion:
        if not self.configured:
            raise ProviderError(f"{self.name}: no API key configured", kind="auth")

        system, messages = _to_anthropic(request.messages)
        if request.json_schema is not None:
            system = "\n\n".join(
                part
                for part in (
                    system,
                    "Respond with a single JSON object matching this JSON Schema, and nothing "
                    "else:\n" + json.dumps(request.json_schema),
                )
                if part
            )
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if request.tools:
            body["tools"] = [_tool(t) for t in request.tools]
            body["tool_choice"] = {"type": "auto"}
        if request.stop:
            body["stop_sequences"] = request.stop[:4]

        try:
            response = await self._client.post("/v1/messages", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"{self.name} timeout: {type(exc).__name__}", kind="timeout"
            ) from None
        except httpx.TransportError as exc:
            raise ProviderError(
                f"{self.name} connection error: {type(exc).__name__}", kind="connection"
            ) from None

        self.rate_limit = {
            k.removeprefix("anthropic-ratelimit-"): v
            for k, v in response.headers.items()
            if k.lower().startswith("anthropic-ratelimit-")
        }
        if response.status_code != 200:
            raise _classify(self.name, response)

        data = response.json()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        calls = [
            ToolCall(
                id=b.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                name=b.get("name", ""),
                arguments=b.get("input") if isinstance(b.get("input"), dict) else {},
            )
            for b in data.get("content", [])
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        # Cached input is billed differently but is still input the model read.
        input_tokens = sum(
            usage.get(k) or 0
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        output_tokens = usage.get("output_tokens")
        return Completion(
            content=text,
            tool_calls=calls,
            input_tokens=input_tokens if usage else None,
            output_tokens=output_tokens,
            est_cost_usd=self._pricing.cost(
                self._pricing_name, self.model, input_tokens, output_tokens
            ),
        )


def _tool(definition: dict[str, Any]) -> dict[str, Any]:
    function = definition.get("function", definition)
    return {
        "name": function["name"],
        "description": function.get("description", ""),
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def _to_anthropic(messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
    """(system text, alternating user/assistant messages with content blocks)."""
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
        elif message.role == "user":
            add("user", [{"type": "text", "text": message.content or ""}])
        elif message.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls or []:
                blocks.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                )
            add("assistant", blocks or [{"type": "text", "text": ""}])
        elif message.role == "tool":
            add(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content or "",
                    }
                ],
            )
    # Tool results must come first in a user message that also carries text.
    for message in out:
        if message["role"] == "user":
            message["content"].sort(key=lambda b: b["type"] != "tool_result")
    return "\n\n".join(system_parts), out


def _classify(provider: str, response: httpx.Response) -> ProviderError:
    status = response.status_code
    body = response.text
    retry_after = _retry_after(response)
    kind: ErrorKind
    if status in (401, 403):
        kind = "auth"
    elif status == 404:
        kind = "model_unavailable"
    elif status == 429:
        kind = "rate_limit"
    elif status in (500, 502, 503, 504, 529) or status >= 500:
        kind = "server"  # 529 is "overloaded"
    elif status == 400 and any(hint in body.lower() for hint in _QUOTA_HINTS):
        kind = "quota"
    else:
        kind = "bad_request"
    # The body can echo request content; keep only the provider's short error message.
    message = _error_message(response) or f"HTTP {status}"
    return ProviderError(f"{provider} HTTP {status}: {message}", kind=kind, retry_after=retry_after)


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return ""
    return str(error.get("message", ""))[:300]


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
