"""Three slips found in a live Streamlit mission on free DeepSeek (2026-11-21, PRD D77)."""

import asyncio
import subprocess
import threading

import pytest

from app.agents.llm import HexLLM
from app.providers.base import LLMResult, ToolCall
from app.providers.router import CallContext
from app.sandbox import runner as sandbox

# ---------- 1. a timed-out install crashed while reading its output ----------


def test_a_timed_out_check_reports_the_timeout_even_when_its_output_is_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(argv, **kwargs):
        if argv[:2] == ["docker", "kill"]:
            return subprocess.CompletedProcess(argv, 0)
        # subprocess gives the partial output as bytes on a timeout, even with text=True
        raise subprocess.TimeoutExpired(argv, 600, output=b"Collecting streamlit\n", stderr=None)

    monkeypatch.setattr(sandbox.subprocess, "run", timeout)

    outcome = sandbox._run("install", ["docker", "run"], "c", 600, 0.0)

    assert outcome.exit_code is None and "timed out after 600s" in (outcome.error or "")
    assert "Collecting streamlit" in outcome.output_tail


# ---------- 2. tool calls given where a final answer was asked for ----------


class Router:
    def __init__(self, results: list[LLMResult]) -> None:
        self.results, self.requests = results, []

    async def complete(self, request, ctx):
        self.requests.append(request)
        return self.results.pop(0)


def result(content: str | None = None, calls: list[ToolCall] | None = None) -> LLMResult:
    return LLMResult(
        provider="harbor", model="deepseek:free", content=content, tool_calls=calls or [],
        input_tokens=1, output_tokens=1, latency_ms=1, est_cost_usd=None, attempts=1, error=None,
    )  # fmt: skip


def run_llm(router: Router, tools):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        llm = HexLLM(router=router, loop=loop, ctx=CallContext(), purpose="coder")  # type: ignore[arg-type]
        return llm.call([{"role": "user", "content": "Finish."}], tools=tools)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


CALL = ToolCall(id="c1", name="write_file", arguments={"path": "a.py"})


def test_with_no_tools_offered_tool_calls_are_not_handed_on_and_a_text_answer_is_asked_for():
    router = Router([result(calls=[CALL]), result(content='{"implemented": ["a.py"]}')])

    answer = run_llm(router, tools=None)

    assert answer == '{"implemented": ["a.py"]}'  # a string, as the framework needs
    assert len(router.requests) == 2 and router.requests[1].tools is None
    assert "final answer" in router.requests[1].messages[-1].content


def test_a_model_that_still_calls_tools_gives_its_text_or_nothing_never_a_list() -> None:
    router = Router([result(calls=[CALL]), result(content="done", calls=[CALL])])

    assert run_llm(router, tools=None) == "done"


def test_with_tools_offered_tool_calls_are_passed_on_as_before() -> None:
    router = Router([result(calls=[CALL])])
    tools = [{"type": "function", "function": {"name": "write_file", "parameters": {}}}]

    answer = run_llm(router, tools=tools)

    assert isinstance(answer, list) and len(router.requests) == 1


# ---------- 3. load_skill asked for SKILL.md as one of the skill's files ----------


def test_asking_for_the_skill_file_itself_returns_the_skill(tmp_path) -> None:
    from app.mcp_server.tools import WorkspaceTools
    from app.skills.registry import SkillRegistry

    tools = WorkspaceTools(
        tmp_path, workspace=tmp_path, allowed_images=[], check_timeout_s=60,
        skills=SkillRegistry(None), allowed_skills=("run-contract",),
    )  # fmt: skip

    for name in ("SKILL.md", "skill.md", "README.md", "./SKILL.md"):
        text = tools.load_skill("run-contract", name)
        assert "Run contract" in text and "ERROR" not in text


def test_installs_get_more_time_than_other_checks() -> None:
    from app.sandbox.runner import INSTALL_TIMEOUT_S, timeout_for

    assert timeout_for("install", 120) == INSTALL_TIMEOUT_S == 600
    assert timeout_for("test", 120) == 120 and timeout_for("install", 900) == 900


@pytest.mark.skipif(not sandbox.docker_available()[0], reason="Docker unavailable")
def test_the_test_check_does_not_run_qas_tests_for_features_not_built_yet(tmp_path) -> None:
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "unit.test.js").write_text(
        "require('node:test')('setup works', () => {})\n"
    )
    (tmp_path / "tests" / "acceptance").mkdir(parents=True)
    (tmp_path / "tests" / "acceptance" / "later.test.js").write_text(
        "require('../../src/calc.js')  // the next feature writes this\n"
    )

    test = sandbox.run_check(
        name="test", command="node --test", image="node:22-alpine", worktree=tmp_path,
        timeout_s=120,
    )  # fmt: skip
    acceptance = sandbox.run_check(
        name="acceptance", command="node --test", image="node:22-alpine", worktree=tmp_path,
        timeout_s=120,
    )  # fmt: skip

    assert test.passed and sandbox.accepted(test), test.output_tail
    assert not acceptance.passed  # QA's own check still sees and runs them
    assert (tmp_path / "tests" / "acceptance" / "later.test.js").exists()  # nothing was touched


@pytest.mark.parametrize(
    ("exit_code", "output"),
    [
        (5, "=== test session starts ===\ncollected 0 items\n\n=== no tests ran in 0.01s ==="),
        (0, "TAP version 13\n# tests 0\n"),
    ],
)
def test_a_run_with_no_tests_says_to_add_one_whatever_its_exit_code(exit_code, output) -> None:
    check = sandbox.CheckOutcome("test", exit_code, 10, output)

    assert not sandbox.accepted(check)
    assert "ran NO tests: add at least one real test file" in sandbox.check_summary(check)


def test_the_setup_feature_is_planned_with_a_passing_test_and_no_hashes() -> None:
    from app.skills.registry import SkillRegistry

    body = SkillRegistry(None).get("project-layout").body
    assert "one small test that passes" in body and "never write `--hash` lines" in body
