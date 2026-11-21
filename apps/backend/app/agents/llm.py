"""CrewAI LLM adapter: every agent model call goes through our ProviderRouter (plan §0 #3), so
it is logged in `llm_calls`, emits run events, and gets provider retry/fallback.

Tool use is native by default: CrewAI passes OpenAI-style tool schemas, we forward them to the
provider, and return the provider's structured tool calls for CrewAI to execute. (Small local
models follow structured tool calls far more reliably than the text ReAct format.) Text ReAct
remains available as a setting.

CrewAI runs agents on worker threads; `call` hands each request to the server event loop and
waits for the result there.
"""

import asyncio
import json
from typing import Any

from crewai.llms.base_llm import BaseLLM
from pydantic import PrivateAttr

from app.providers.base import ChatMessage, LLMRequest, LLMResult, Purpose, ToolCall
from app.providers.router import CallContext, ProviderRouter

_ROLES = {"system", "user", "assistant", "tool"}

# An agent's loop re-sends the whole conversation on every step, so a file read at step 2 is paid
# for again at steps 3 to 25 (live run: ~50,000 input tokens to write one 60-line file). Results
# older than the last KEEP_RECENT_MESSAGES messages are cut to their first OLD_RESULT_CHARS
# characters; the agent can call the tool again if it needs the rest.
FINAL_ANSWER_NOW = (
    "No tools are available at this step. Give your final answer now, as text only, in the "
    "format the task asked for. Do not call any tool."
)
KEEP_RECENT_MESSAGES = 8
OLD_RESULT_CHARS = 300
_SHORTENED = "[older result shortened"


class ProviderCallFailed(RuntimeError):
    pass


class HexLLM(BaseLLM):
    _router: ProviderRouter = PrivateAttr()
    _loop: asyncio.AbstractEventLoop = PrivateAttr()
    _ctx: CallContext = PrivateAttr()
    _purpose: Purpose = PrivateAttr()
    _max_tokens: int = PrivateAttr()
    _native_tools: bool = PrivateAttr()
    # Provider extras (e.g. Gemini thought signatures) by tool-call id. CrewAI rebuilds the
    # assistant message without them, so they are re-attached on the next call.
    _call_extras: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)

    def __init__(
        self,
        *,
        router: ProviderRouter,
        loop: asyncio.AbstractEventLoop,
        ctx: CallContext,
        purpose: Purpose,
        max_tokens: int = 2048,
        native_tools: bool = True,
        **data: Any,
    ) -> None:
        super().__init__(model=f"hexmind-{purpose}", **data)
        self._router = router
        self._loop = loop
        self._ctx = ctx
        self._purpose = purpose
        self._max_tokens = max_tokens
        self._native_tools = native_tools

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str | list[dict[str, Any]]:
        native = self._native_tools and bool(tools)
        stop = None if native else (list(self.stop) if getattr(self, "stop", None) else None)
        request = LLMRequest(
            purpose=self._purpose,
            messages=trim_history(to_chat_messages(messages, self._call_extras)),
            tools=tools if native else None,
            max_tokens=self._max_tokens,
            temperature=0.2,
            stop=stop,
        )
        future = asyncio.run_coroutine_threadsafe(
            self._router.complete(request, self._ctx), self._loop
        )
        result = future.result()
        if not result.ok:
            raise ProviderCallFailed(f"{result.provider} call failed: {result.error}")
        if result.tool_calls and not native:
            # No tools were offered: the framework wants the final answer as text. A model that
            # still answers with tool calls (free DeepSeek did, D77) is asked once, plainly, for
            # the text; a list here would fail the whole attempt.
            result = self._ask_for_text(request)
            return truncate_at_stop(result.content or "", stop)
        if result.tool_calls:
            for call in result.tool_calls:
                if call.extra:
                    self._call_extras[call.id] = call.extra
            return [to_crewai_tool_call(call) for call in result.tool_calls]
        return truncate_at_stop(result.content or "", stop)

    def _ask_for_text(self, request: LLMRequest) -> LLMResult:
        again = request.model_copy(
            update={
                "messages": [
                    *request.messages,
                    ChatMessage(role="user", content=FINAL_ANSWER_NOW),
                ],
                "tools": None,
            }
        )
        future = asyncio.run_coroutine_threadsafe(
            self._router.complete(again, self._ctx), self._loop
        )
        result = future.result()
        if not result.ok:
            raise ProviderCallFailed(f"{result.provider} call failed: {result.error}")
        return result

    def supports_function_calling(self) -> bool:
        return self._native_tools

    def supports_stop_words(self) -> bool:
        return not self._native_tools

    def get_context_window_size(self) -> int:
        return 8192


def trim_history(messages: list[ChatMessage]) -> list[ChatMessage]:
    """The conversation with old, long tool results shortened. Same messages in the same order
    (tool calls and their results stay paired); only the text of old results changes."""
    cutoff = len(messages) - KEEP_RECENT_MESSAGES
    trimmed: list[ChatMessage] = []
    for index, message in enumerate(messages):
        text = message.content or ""
        if (
            index < cutoff
            and message.role == "tool"
            and len(text) > OLD_RESULT_CHARS
            and _SHORTENED not in text
        ):
            note = (
                f"\n… {_SHORTENED} from {len(text)} characters; "
                "call the tool again if you need the rest]"
            )
            message = message.model_copy(
                update={"content": text[:OLD_RESULT_CHARS].rstrip() + note}
            )
        trimmed.append(message)
    return trimmed


def to_chat_messages(
    messages: Any, extras: dict[str, dict[str, Any]] | None = None
) -> list[ChatMessage]:
    """CrewAI/OpenAI-style message dicts (including tool calls and tool results) -> ours.
    `extras` re-attaches provider data to the tool calls this conversation produced."""
    if isinstance(messages, str):
        return [ChatMessage(role="user", content=messages)]
    converted = []
    for message in messages:
        role = message.get("role", "user")
        role = role if role in _ROLES else "user"
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            content = str(content)
        tool_calls = [_from_crewai_tool_call(c) for c in message.get("tool_calls") or []]
        for call in tool_calls:
            if extras and call.id in extras:
                call.extra = extras[call.id]
        converted.append(
            ChatMessage(
                role=role,
                content=content if content is not None or tool_calls else "",
                tool_calls=tool_calls or None,
                tool_call_id=message.get("tool_call_id"),
                name=message.get("name"),
            )
        )
    return converted


def to_crewai_tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": "function",
        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
    }


def _from_crewai_tool_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function", {})
    raw = function.get("arguments") or {}
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except ValueError:
        arguments = {"_raw": raw}
    return ToolCall(id=call.get("id") or "call", name=function.get("name", ""), arguments=arguments)


def truncate_at_stop(text: str, stop: list[str] | None) -> str:
    """Providers that ignore stop sequences may run past `Observation:`; cut there."""
    if not stop:
        return text
    cut = min((i for s in stop if (i := text.find(s)) >= 0), default=-1)
    return text if cut < 0 else text[:cut]
