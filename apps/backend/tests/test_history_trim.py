"""Old tool results are shortened so an agent's loop stops re-paying for them on every step."""

from app.agents.llm import KEEP_RECENT_MESSAGES, OLD_RESULT_CHARS, trim_history
from app.providers.base import ChatMessage, ToolCall

FILE = "const x = 1;\n" * 150  # ~2,000 characters, like a small source file


def loop(steps: int, *, result: str = FILE) -> list[ChatMessage]:
    """system, task, then `steps` rounds of (assistant asks for a tool, tool answers)."""
    messages = [
        ChatMessage(role="system", content="You are a builder."),
        ChatMessage(role="user", content="Work on this feature. " * 30),
    ]
    for i in range(steps):
        call = ToolCall(id=f"c{i}", name="read_file", arguments={"path": f"f{i}.js"})
        messages.append(ChatMessage(role="assistant", content="", tool_calls=[call]))
        messages.append(
            ChatMessage(role="tool", content=result, tool_call_id=f"c{i}", name="read_file")
        )
    return messages


def size(messages: list[ChatMessage]) -> int:
    return sum(len(m.content or "") for m in messages)


def test_old_long_results_are_shortened_and_recent_ones_are_kept_whole() -> None:
    messages = loop(12)

    trimmed = trim_history(messages)

    assert len(trimmed) == len(messages)
    cutoff = len(messages) - KEEP_RECENT_MESSAGES
    for index, (before, after) in enumerate(zip(messages, trimmed, strict=True)):
        if index >= cutoff or before.role != "tool":
            assert after == before  # recent messages, and anything that is not a tool result
        else:
            assert after.content.startswith(FILE[:OLD_RESULT_CHARS].rstrip())
            assert f"shortened from {len(FILE)} characters" in after.content
            assert after.tool_call_id == before.tool_call_id and after.name == before.name


def test_tool_calls_and_their_results_stay_paired() -> None:
    trimmed = trim_history(loop(15))

    asked = [c.id for m in trimmed if m.tool_calls for c in m.tool_calls]
    answered = [m.tool_call_id for m in trimmed if m.role == "tool"]
    assert asked == answered


def test_short_results_and_short_conversations_are_untouched() -> None:
    short = loop(12, result="ok")
    few = loop(3)

    assert trim_history(short) == short  # nothing long enough to be worth shortening
    assert trim_history(few) == few  # all of it is recent


def test_trimming_twice_changes_nothing_more() -> None:
    once = trim_history(loop(14))

    assert trim_history(once) == once


def test_the_caller_s_messages_are_not_modified() -> None:
    messages = loop(14)
    before = [m.model_copy(deep=True) for m in messages]

    trim_history(messages)

    assert messages == before


def test_it_saves_most_of_the_input_over_a_long_loop() -> None:
    # What the model is sent at each of 25 steps, with and without trimming.
    full = sum(size(loop(step)) for step in range(1, 26))
    trimmed = sum(size(trim_history(loop(step))) for step in range(1, 26))

    assert trimmed < full * 0.5  # measured below: the saving grows with the length of the loop
