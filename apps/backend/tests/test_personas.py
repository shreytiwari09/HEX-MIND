"""Personas, features, handoffs and the generic agent builder (no database, no model calls)."""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.agents.build import (
    MAX_HANDOFFS_SHOWN,
    build_agent,
    feature_prompt,
    tool_names_for,
)
from app.agents.llm import HexLLM
from app.agents.persona import (
    PERSONAS_DIR,
    UnknownPersona,
    builtin_personas,
    get_persona,
    load_persona_file,
)
from app.agents.tools import READ_ONLY
from app.missions.models import (
    AgentReport,
    CommandResult,
    Feature,
    Handoff,
    MissionContext,
)
from app.providers.router import CallContext

WORKERS = {"data", "backend", "designer", "frontend", "devops"}
VALIDATORS = {"qa", "security", "code-reviewer"}


def feature(persona: str = "backend", **overrides: object) -> Feature:
    data: dict[str, object] = {
        "id": "api-auth-routes",
        "title": "Sign-up and login endpoints",
        "persona": persona,
        "description": "Add the auth routes.",
        "expected_behavior": ["POST /auth/signup creates a user", "tests pass"],
    }
    return Feature.model_validate({**data, **overrides})


def handoff(feature_id: str = "schema", **overrides: object) -> Handoff:
    data: dict[str, object] = {
        "feature_id": feature_id,
        "persona_id": "data",
        "model_used": "scripted-model",
        "procedures_followed": True,
    }
    return Handoff.model_validate({**data, **overrides})


def make_llm() -> HexLLM:
    return HexLLM(
        router=MagicMock(),
        loop=asyncio.new_event_loop(),
        ctx=CallContext(run_id=uuid.uuid4(), agent_id="backend_01"),
        purpose="coder",
    )


def test_all_ten_builtin_personas_load_with_the_prd_kinds() -> None:
    personas = builtin_personas()
    assert set(personas) == WORKERS | VALIDATORS | {"pm", "researcher"}
    assert {p.id for p in personas.values() if p.kind == "worker"} == WORKERS
    assert {p.id for p in personas.values() if p.kind == "validator"} == VALIDATORS
    assert personas["pm"].kind == "orchestrator"
    assert personas["researcher"].kind == "research"
    assert personas["qa"].plugins == ["playwright"]


def test_a_persona_file_must_match_its_id(tmp_path: Path) -> None:
    text = (PERSONAS_DIR / "backend.yaml").read_text(encoding="utf-8")
    wrong = tmp_path / "frontend.yaml"
    wrong.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="must match the file name"):
        load_persona_file(wrong)


def test_unknown_persona() -> None:
    with pytest.raises(UnknownPersona):
        get_persona("ghost")


def test_persona_purpose_follows_its_kind() -> None:
    assert get_persona("backend").purpose == "coder"
    assert get_persona("code-reviewer").purpose == "reviewer"
    assert get_persona("pm").purpose == "planner"


def test_only_workers_get_write_tools() -> None:
    for persona in builtin_personas().values():
        names = tool_names_for(persona)
        if persona.kind == "worker":
            assert {"write_file", "replace_in_file", "run_check"} <= set(names)
        else:
            assert names == READ_ONLY


def test_feature_validation() -> None:
    with pytest.raises(ValidationError):
        feature(id="Bad Id")
    with pytest.raises(ValidationError):
        feature(expected_behavior=[])


def test_build_agent_uses_only_its_own_persona() -> None:
    backend = get_persona("backend")
    ctx = MissionContext(worktree=Path("w"), workspace=Path("p"))
    agent = build_agent(backend, feature(), ctx, llm=make_llm(), tools=[], max_iter=5)
    assert agent.role == "Backend engineer"
    assert agent.goal == "Sign-up and login endpoints"
    assert agent.backstory.strip() == backend.instructions.strip()
    assert agent.allow_delegation is False
    with pytest.raises(ValueError, match="assigned to designer"):
        build_agent(backend, feature("designer"), ctx, llm=make_llm(), tools=[], max_iter=5)


def test_the_prompt_carries_the_feature_and_earlier_work_but_not_chat_history() -> None:
    ctx = MissionContext(
        worktree=Path("w"),
        workspace=Path("p"),
        earlier_handoffs=[
            handoff("schema", implemented=["users table"], notes_for_next=["email is unique"])
        ],
    )
    prompt = feature_prompt(
        get_persona("backend"),
        feature(preconditions=["users table exists"], contract_refs=["VC-2.3"]),
        ctx,
    )
    assert "Feature: Sign-up and login endpoints" in prompt
    assert "- POST /auth/signup creates a user" in prompt
    assert "users table exists" in prompt and "VC-2.3" in prompt
    assert "- schema (data): implemented users table notes: email is unique" in prompt
    assert "write_file" in prompt and "run_check" in prompt
    assert "procedures_followed" in prompt  # the report schema


def test_validator_prompt_is_read_only_and_only_recent_handoffs_are_shown() -> None:
    many = [handoff(f"feat-{i:02d}") for i in range(MAX_HANDOFFS_SHOWN + 3)]
    ctx = MissionContext(worktree=Path("w"), workspace=Path("p"), earlier_handoffs=many)
    prompt = feature_prompt(get_persona("code-reviewer"), feature("code-reviewer"), ctx)
    assert "You can read the project but not change it." in prompt
    assert "write_file" not in prompt
    assert "feat-00" not in prompt and f"feat-{len(many) - 1:02d}" in prompt


def test_a_handoff_takes_measured_facts_not_agent_claims() -> None:
    # The agent tries to report files and commands itself; AgentReport has no such fields.
    report = AgentReport.model_validate(
        {
            "implemented": ["signup route"],
            "procedures_followed": True,
            "files_changed": ["/etc/passwd"],
            "commands": [{"command": "fake", "exit_code": 0, "duration_s": 0, "summary": "ok"}],
        }
    )
    result = Handoff.assemble(
        report,
        feature=feature(),
        model_used="scripted-model",
        commands=[CommandResult(command="npm test", exit_code=0, duration_s=1.2, summary="2 pass")],
        files_changed=["src/auth.js"],
        tokens_in=100,
        tokens_out=40,
        cost_usd=0.002,
    )
    assert result.files_changed == ["src/auth.js"]
    assert [c.command for c in result.commands] == ["npm test"]
    assert (result.feature_id, result.persona_id) == ("api-auth-routes", "backend")
    assert result.implemented == ["signup route"]
    assert (result.tokens_in, result.tokens_out, result.cost_usd) == (100, 40, 0.002)


def test_mission_dir_is_inside_the_worktree() -> None:
    ctx = MissionContext(worktree=Path("w"), workspace=Path("p"))
    assert ctx.mission_dir == Path("w") / ".hex" / "mission"


async def test_the_personas_endpoint_lists_the_team(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/api/personas")

    assert response.status_code == 200
    team = {p["id"]: p for p in response.json()}
    assert set(team) == WORKERS | VALIDATORS | {"pm", "researcher"}
    assert (team["backend"]["name"], team["backend"]["kind"]) == ("Backend engineer", "worker")
    assert team["qa"]["plugins"] == ["playwright"]
