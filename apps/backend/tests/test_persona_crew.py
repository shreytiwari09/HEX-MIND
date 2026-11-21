"""The `persona` crew over A2A: any persona runs one feature in a real worktree with real MCP
tools; only the model is scripted. (No sandbox checks run, so Docker is not needed.)"""

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.a2a.client import CrewCallFailed, call_crew
from app.a2a.protocol import PersonaRequest
from app.db.models import Project, Run
from app.missions.models import AgentReport, Feature, Handoff
from app.providers.base import Completion, LLMRequest, ToolCall
from app.telemetry.hub import TelemetryHub
from app.workspace import git
from tests.conftest import ScriptedAdapter, use_adapter

AUTH_JS = "module.exports = { signup: (email) => ({ email }) }\n"
REPORT = {
    "implemented": ["signup function"],
    "left_undone": [],
    "issues_found": [],
    "procedures_followed": True,
    "notes_for_next": ["signup returns { email }"],
}


def feature(persona: str, **overrides: object) -> Feature:
    data: dict[str, object] = {
        "id": "api-auth-routes",
        "title": "Signup function",
        "persona": persona,
        "expected_behavior": ["signup returns the email"],
    }
    return Feature.model_validate({**data, **overrides})


class PersonaScript:
    """Writes one file (when it has a write tool), then answers with `answer`."""

    def __init__(self, answer: str | None = None) -> None:
        self.answer = json.dumps(REPORT) if answer is None else answer
        self.requests: list[LLMRequest] = []

    def __call__(self, request: LLMRequest) -> Completion:
        self.requests.append(request)
        has_result = any(m.role == "tool" for m in request.messages)
        if not has_result and any_tool(request, "write_file"):
            call = ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name="write_file",
                arguments={"path": "src/auth.js", "content": AUTH_JS},
            )
            return Completion(tool_calls=[call])
        return Completion(content=self.answer)


def any_tool(request: LLMRequest, name: str) -> bool:
    return any(t["function"]["name"] == name for t in request.tools or [])


async def start(app: FastAPI, workspace: Path) -> tuple[uuid.UUID, Path]:
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path=str(workspace))
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        run_id = run.id
    worktree = app.state.settings.data_dir / "worktrees" / str(run_id)
    git.create_worktree(workspace, git.snapshot(workspace), worktree, f"hex/test-{run_id.hex[:8]}")
    return run_id, worktree


async def run_persona(
    app: FastAPI,
    run_id: uuid.UUID,
    worktree: Path,
    workspace: Path,
    persona_id: str,
    feat: Feature,
    earlier: list[Handoff] | None = None,
    escalate: bool = False,
    mode: str = "feature",
) -> str:
    services = app.state.services
    request = PersonaRequest(
        exchange_id=uuid.uuid4(),
        run_id=run_id,
        agent_id=f"{persona_id}_01",
        worktree=str(worktree),
        workspace=str(workspace),
        persona_id=persona_id,
        feature=feat,
        earlier_handoffs=earlier or [],
        escalate=escalate,
        mode=mode,  # type: ignore[arg-type]
    )
    return await call_crew(
        "persona",
        hub=TelemetryHub(services, run_id),
        http=services.a2a_http,
        settings=services.settings,
        prompt=f"Feature {feat.id}",
        request=request,
        parent="persona_crew",
    )


async def test_the_persona_crew_is_listed_with_its_agent_card(
    app: FastAPI,
    client: "httpx.AsyncClient",  # noqa: F821
) -> None:
    agents = {a["role"]: a for a in (await client.get("/api/a2a/agents")).json()}
    card = agents["persona"]["card"]
    assert agents["persona"]["reachable"] is True
    assert card["name"] == "persona_crew" and card["url"].endswith("/persona/")
    assert [s["id"] for s in card["skills"]] == ["persona-feature"]


async def test_a_worker_persona_changes_files_and_returns_a_valid_report(
    app: FastAPI, workspace: Path
) -> None:
    script = PersonaScript()
    use_adapter(app, ScriptedAdapter(script))
    run_id, worktree = await start(app, workspace)
    earlier = [
        Handoff(
            feature_id="schema",
            persona_id="data",
            model_used="m",
            procedures_followed=True,
            notes_for_next=["users table has a unique email"],
        )
    ]

    text = await run_persona(
        app,
        run_id,
        worktree,
        workspace,
        "backend",
        feature("backend", target_files=["src/app.ts"]),
        earlier,
    )

    report = AgentReport.model_validate_json(text)
    assert report.implemented == ["signup function"] and report.procedures_followed
    assert (worktree / "src" / "auth.js").read_text() == AUTH_JS
    assert not (workspace / "src" / "auth.js").exists()  # the user's files are untouched
    first = script.requests[0]
    assert first.purpose == "coder"  # the worker kind's provider purpose
    prompt = "\n".join(m.content or "" for m in first.messages)
    assert "Backend engineer" in prompt  # the persona's own instructions
    assert "Feature: Signup function" in prompt
    assert "users table has a unique email" in prompt  # earlier handoff, not chat history
    assert any_tool(first, "write_file") and any_tool(first, "run_check")
    # The worker is shown a map of the project, the file it is expected to touch first.
    assert "Map of the project" in prompt and "src/app.ts  (x)" in prompt
    # The builder already has the file it is expected to touch, and is told to batch its steps.
    assert "already read for you" in prompt and "export const x = 1" in prompt
    assert "ask for all of those tool calls in one step" in prompt
    assert any_tool(first, "delete_file") and any_tool(first, "git_diff")
    assert any_tool(first, "get_feature_context")


async def test_a_validator_persona_is_read_only(app: FastAPI, workspace: Path) -> None:
    script = PersonaScript()
    use_adapter(app, ScriptedAdapter(script))
    run_id, worktree = await start(app, workspace)

    await run_persona(app, run_id, worktree, workspace, "code-reviewer", feature("code-reviewer"))

    first = script.requests[0]
    assert first.purpose == "reviewer"
    assert any_tool(first, "read_file")
    assert not any_tool(first, "write_file") and not any_tool(first, "run_check")
    assert not (worktree / "src" / "auth.js").exists()


@pytest.mark.parametrize(
    ("persona_id", "answer", "reason"),
    [
        ("backend", "I finished everything, trust me.", "no JSON object"),
        ("backend", json.dumps({"implemented": ["x"]}), "procedures_followed"),
        ("ghost", json.dumps(REPORT), "ghost"),
    ],
)
async def test_an_invalid_report_or_unknown_persona_fails_the_task(
    app: FastAPI, workspace: Path, persona_id: str, answer: str, reason: str
) -> None:
    use_adapter(app, ScriptedAdapter(PersonaScript(answer)))
    run_id, worktree = await start(app, workspace)

    with pytest.raises(CrewCallFailed, match=reason):
        await run_persona(app, run_id, worktree, workspace, persona_id, feature(persona_id))


@pytest.mark.parametrize(
    ("persona_id", "mode"), [("qa", "acceptance"), ("code-reviewer", "feature")]
)
async def test_only_builders_get_files_in_the_first_prompt_not_qa_or_reviewers(
    app: FastAPI, workspace: Path, persona_id: str, mode: str
) -> None:
    # QA must write acceptance tests from the contract, not from the implementation, and
    # validators judge the diff themselves.
    script = PersonaScript()
    use_adapter(app, ScriptedAdapter(script))
    run_id, worktree = await start(app, workspace)

    await run_persona(
        app,
        run_id,
        worktree,
        workspace,
        persona_id,
        feature(persona_id, target_files=["src/app.ts"]),
        mode=mode,
    )

    prompt = "\n".join(m.content or "" for m in script.requests[0].messages)
    assert "already read for you" not in prompt and "export const x = 1" not in prompt
