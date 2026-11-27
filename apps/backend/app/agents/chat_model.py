"""LangChain chat model for LangGraph agents: every call goes through our ProviderRouter, the same
entry point CrewAI agents use (HexLLM). One router means one place for provider selection,
retry/fallback, cost estimates, `llm_calls` logging and run events, whichever framework an agent
belongs to. No LangChain provider integration is used.

LangChain messages and tool schemas are converted to and from our provider-neutral types. Gemini
thought signatures on tool calls round-trip through the AI message's `additional_kwargs`.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr

from app.providers.base import ChatMessage, LLMRequest, LLMResult, Purpose, ToolCall
from app.providers.router import CallContext, ProviderRouter

# additional_kwargs key holding provider extras per tool-call id (e.g. Gemini thought signatures)
TOOL_EXTRA_KEY = "hexmind_tool_call_extra"


class ProviderCallFailed(RuntimeError):
    pass


class HexChatModel(BaseChatModel):
    """The real provider and model are chosen per call by the ProviderRouter and recorded on each
    `llm_calls` row; `purpose` picks the router policy."""

    _router: ProviderRouter = PrivateAttr()
    _ctx: CallContext = PrivateAttr()
    _purpose: Purpose = PrivateAttr()
    _max_tokens: int = PrivateAttr()
    # The most recent request/result: for callbacks (provider, model, tokens, cost) and for the
    # structured-output guard's repair call.
    _last_request: LLMRequest | None = PrivateAttr(default=None)
    _last_result: LLMResult | None = PrivateAttr(default=None)

    def __init__(
        self,
        *,
        router: ProviderRouter,
        ctx: CallContext,
        purpose: Purpose,
        max_tokens: int = 2048,
        **data: Any,
    ) -> None:
        super().__init__(**data)
        self._router = router
        self._ctx = ctx
        self._purpose = purpose
        self._max_tokens = max_tokens

    @property
    def _llm_type(self) -> str:
        return "hexmind"

    @property
    def last_request(self) -> LLMRequest | None:
        return self._last_request

    @property
    def last_result(self) -> LLMResult | None:
        return self._last_result

    @property
    def router(self) -> ProviderRouter:
        return self._router

    @property
    def ctx(self) -> CallContext:
        return self._ctx

    @property
    def purpose(self) -> Purpose:
        return self._purpose

    def use_context(self, ctx: CallContext) -> None:
        """Change who later calls are made for (for example a persona route found after start)."""
        self._ctx = ctx

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("HexChatModel is async only: use ainvoke")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        request = LLMRequest(
            purpose=self._purpose,
            messages=to_chat_messages(messages),
            tools=kwargs.get("tools") or None,
            json_schema=kwargs.get("json_schema"),
            max_tokens=kwargs.get("max_tokens") or self._max_tokens,
            stop=stop,
        )
        self._last_request = request
        result = await self._router.complete(request, self._ctx)
        self._last_result = result
        if not result.ok:
            raise ProviderCallFailed(f"{result.provider} call failed: {result.error}")
        message = to_ai_message(result)
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output=dict(message.response_metadata),
        )


def to_chat_messages(messages: Sequence[BaseMessage]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for message in messages:
        text = message.text if isinstance(message.text, str) else str(message.content)
        if isinstance(message, SystemMessage):
            out.append(ChatMessage(role="system", content=text))
        elif isinstance(message, HumanMessage):
            out.append(ChatMessage(role="user", content=text))
        elif isinstance(message, AIMessage):
            extras = message.additional_kwargs.get(TOOL_EXTRA_KEY) or {}
            calls = [
                ToolCall(
                    id=call.get("id") or "",
                    name=call["name"],
                    arguments=dict(call.get("args") or {}),
                    extra=extras.get(call.get("id") or ""),
                )
                for call in message.tool_calls
            ]
            out.append(
                ChatMessage(role="assistant", content=text or None, tool_calls=calls or None)
            )
        elif isinstance(message, ToolMessage):
            out.append(
                ChatMessage(
                    role="tool", content=text, tool_call_id=message.tool_call_id, name=message.name
                )
            )
        else:
            out.append(ChatMessage(role="user", content=text))
    return out


def to_ai_message(result: LLMResult) -> AIMessage:
    usage = None
    if result.input_tokens is not None or result.output_tokens is not None:
        usage = {
            "input_tokens": result.input_tokens or 0,
            "output_tokens": result.output_tokens or 0,
            "total_tokens": (result.input_tokens or 0) + (result.output_tokens or 0),
        }
    extras = {c.id: c.extra for c in result.tool_calls if c.extra}
    return AIMessage(
        content=result.content or "",
        tool_calls=[
            {"name": c.name, "args": c.arguments, "id": c.id, "type": "tool_call"}
            for c in result.tool_calls
        ],
        usage_metadata=usage,  # type: ignore[arg-type]
        additional_kwargs={TOOL_EXTRA_KEY: extras} if extras else {},
        response_metadata={
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "est_cost_usd": str(result.est_cost_usd) if result.est_cost_usd is not None else None,
            "fallback_from": result.fallback_from,
        },
    )
