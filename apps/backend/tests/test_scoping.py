"""The PM scoping chat: questions, then a plan the user edits and turns into a mission.
Models are scripted; the sessions, runs, worktrees and missions are real."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import LLMCall, Run
from app.events.log import list_events
from app.missions import scoping
from app.providers.base import Completion, LLMRequest, ProviderError
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import PLAN, Script, load

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
PRD = "# Todo app\n\n## Must-haves\n- add and toggle todos\n"
IDEA = "A todo app where I can add and tick off todos"


def asking(*questions: str) -> str:
    return json.dumps({"message": "A few questions first.", "questions": list(questions)})


def planning(plan: dict[str, Any] | None = None, prd: str | None = PRD) -> str:
    return json.dumps({"message": "Here is the plan.", "plan": plan or PLAN, "prd": prd})


class PM:
    """Plays the PM: one scripted answer per call (the last repeats); records every prompt."""

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, request: LLMRequest) -> Completion:
        if request.purpose != "planner":
            raise AssertionError(f"unexpected purpose {request.purpose}")
        self.prompts.append("\n".join(m.content or "" for m in request.messages))
        answer = self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return Completion(content=answer)


async def start(client: httpx.AsyncClient, root: Path, **extra: Any) -> dict[str, Any]:
    project = (await client.post("/api/projects", json={"workspace_path": str(root)})).json()
    response = await client.post(
        "/api/scoping", json={"project_id": project["id"], "idea": IDEA, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_pm_asks_questions_first_and_its_calls_are_logged_on_the_sessions_run(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    (repo / ".env").write_text("SECRET=1\n")
    (repo / "src").mkdir()
    (repo / "src" / "index.js").write_text("console.log(1)\n")
    pm = PM(asking("Who uses it?", "Do you need login?"))
    use_adapter(app, ScriptedAdapter(pm))

    session = await start(client, repo)

    assert session["status"] == "asking" and session["plan"] is None and session["error"] is None
    [message] = session["messages"]
    assert message["role"] == "pm" and message["questions"] == [
        "Who uses it?",
        "Do you need login?",
    ]
    prompt = pm.prompts[0]
    assert IDEA in prompt and "- src/index.js" in prompt and "README.md" in prompt
    assert ".env" not in prompt and "SECRET" not in prompt  # never shown, not even by name
    for persona in ("backend", "frontend", "devops", "code-reviewer", "qa"):
        assert f"- {persona} (" in prompt
    # The PM's model call belongs to the session's own run, for the PM persona.
    async with app.state.sessionmaker() as db:
        calls = list(await db.scalars(select(LLMCall).where(LLMCall.run_id == session["run_id"])))
        events = await list_events(db, session["run_id"])
    assert [c.persona_id for c in calls] == ["pm"] and "run_created" in [e.type for e in events]


async def test_answers_lead_to_a_plan_without_runtime_state_and_the_user_can_keep_talking(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    pm = PM(asking("Who uses it?"), planning(), planning())
    use_adapter(app, ScriptedAdapter(pm))
    session = await start(client, repo)

    done = (
        await client.post(f"/api/scoping/{session['id']}/messages", json={"content": "just me"})
    ).json()

    assert done["status"] == "planned" and done["prd"] == PRD
    assert [m["role"] for m in done["messages"]] == ["pm", "user", "pm"]
    assert "User: just me" in pm.prompts[1] and "Who uses it?" in pm.prompts[1]
    assert done["plan"]["title"] == "Todo app" and len(done["plan"]["milestones"]) == 2
    feature = done["plan"]["milestones"][0]["features"][0]
    assert "attempts" not in feature and "commit" not in feature and "status" not in feature
    # Asking for a change makes the PM plan again.
    again = (
        await client.post(f"/api/scoping/{session['id']}/messages", json={"content": "add login"})
    ).json()
    assert again["status"] == "planned" and len(again["messages"]) == 5
    assert (await client.get(f"/api/scoping/{session['id']}")).json()["id"] == session["id"]
    listed = (await client.get("/api/scoping", params={"project_id": session["project_id"]})).json()
    assert [s["id"] for s in listed] == [session["id"]]


async def test_after_enough_questions_the_pm_is_told_to_plan(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    pm = PM(asking("one?"), asking("two?"), asking("three?"), planning())
    use_adapter(app, ScriptedAdapter(pm))
    session = await start(client, repo)
    for answer in ("a", "b"):
        session = (
            await client.post(f"/api/scoping/{session['id']}/messages", json={"content": answer})
        ).json()
    assert all("propose the plan now" not in p for p in pm.prompts)

    session = (
        await client.post(f"/api/scoping/{session['id']}/messages", json={"content": "c"})
    ).json()

    assert scoping.MAX_QUESTION_TURNS == 3
    assert "propose the plan now" in pm.prompts[3] and session["status"] == "planned"


async def test_an_invalid_plan_is_repaired_once_and_never_accepted_as_it_is(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    broken = json.loads(json.dumps(PLAN))
    broken["milestones"][0]["features"][0]["persona"] = "wizard"  # not a worker persona
    pm = PM(planning(broken), planning())
    use_adapter(app, ScriptedAdapter(pm))

    session = await start(client, repo)

    assert len(pm.prompts) == 2 and "That answer was invalid" in pm.prompts[1]
    assert session["status"] == "planned" and session["error"] is None

    # A PM that keeps giving an invalid plan produces no plan and says why.
    pm = PM(planning(broken))
    use_adapter(app, ScriptedAdapter(pm))
    session = await start(client, repo)
    assert session["status"] == "asking" and session["plan"] is None
    assert "wizard" in session["error"] or "persona" in session["error"]
    assert [m["role"] for m in session["messages"]] == []  # nothing invented


async def test_a_plan_without_its_prd_is_not_a_plan(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(PM(planning(prd=None))))

    session = await start(client, repo)

    assert session["status"] == "asking" and session["plan"] is None and session["error"]


async def test_a_provider_outage_leaves_the_session_asking_and_retry_asks_again(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    pm = PM(ProviderError("model unavailable", retryable=False), planning())
    use_adapter(app, ScriptedAdapter(pm))

    session = await start(client, repo)

    assert session["status"] == "asking" and session["plan"] is None
    assert "model unavailable" in session["error"]
    retried = (await client.post(f"/api/scoping/{session['id']}/retry")).json()
    assert retried["status"] == "planned" and retried["error"] is None


async def test_the_user_edits_the_plan_and_an_invalid_edit_is_refused(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(PM(planning())))
    session = await start(client, repo)
    edited = json.loads(json.dumps(PLAN))
    edited["title"] = "Todo app (mine)"
    edited["milestones"][1]["features"][0]["persona"] = "backend"

    saved = await client.put(
        f"/api/scoping/{session['id']}/plan",
        json={"plan": edited, "prd": PRD + "\nMy note.", "budget_usd": 2.5},
    )

    body = saved.json()
    assert saved.status_code == 200 and body["plan"]["title"] == "Todo app (mine)"
    assert body["prd"].endswith("My note.") and body["budget_usd"] == 2.5
    edited["milestones"][0]["validators"] = ["backend"]  # a builder, not a validator
    refused = await client.put(
        f"/api/scoping/{session['id']}/plan", json={"plan": edited, "prd": PRD}
    )
    assert refused.status_code == 422
    assert (await client.get(f"/api/scoping/{session['id']}")).json()["plan"]["title"] == (
        "Todo app (mine)"
    )


async def test_the_plan_becomes_a_mission_on_the_same_run_with_its_prd(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    plan = json.loads(json.dumps(PLAN))
    plan["validation_contract"] = [
        {"id": "VC-1", "text": "addTodo trims titles", "how": "unit test", "feature": "todo-model"}
    ]
    use_adapter(app, ScriptedAdapter(PM(planning(plan))))
    session = await start(client, repo, budget_usd=3)

    response = await client.post(f"/api/scoping/{session['id']}/mission")

    assert response.status_code == 201
    mission = response.json()
    assert mission["status"] == "awaiting_approval" and mission["run_id"] == session["run_id"]
    assert mission["budget_usd"] == 3 and [c["id"] for c in mission["validation_contract"]] == [
        "VC-1"
    ]
    _, _, run = await load(app, mission["id"])
    folder = Path(run.worktree_path or "") / ".hex" / "mission"
    assert (folder / "prd.md").read_text() == PRD
    assert (folder / "validation-contract.md").exists() and (folder / "features.json").exists()
    async with app.state.sessionmaker() as db:
        events = [e.type for e in await list_events(db, run.id)]
        assert (await db.get(Run, run.id)).title == "Todo app"  # type: ignore[union-attr]
    assert events.count("run_created") == 1 and "llm_call_completed" in events
    done = (await client.get(f"/api/scoping/{session['id']}")).json()
    assert done["status"] == "started" and done["mission_id"] == mission["id"]
    # A started session is closed.
    for call in (
        client.post(f"/api/scoping/{session['id']}/messages", json={"content": "more"}),
        client.post(f"/api/scoping/{session['id']}/mission"),
        client.post(f"/api/scoping/{session['id']}/abandon"),
    ):
        assert (await call).status_code == 409


async def test_there_is_no_mission_before_there_is_a_plan_and_abandoning_closes_the_session(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(PM(asking("Who?"))))
    session = await start(client, repo)

    assert (await client.post(f"/api/scoping/{session['id']}/mission")).status_code == 409
    abandoned = await client.post(f"/api/scoping/{session['id']}/abandon")
    assert abandoned.json()["status"] == "abandoned"
    assert (await client.post(f"/api/scoping/{session['id']}/retry")).status_code == 409
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/scoping/{missing}")).status_code == 404
    assert (await client.post(f"/api/scoping/{missing}/mission")).status_code == 404


async def test_a_folder_without_git_cannot_become_a_mission(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    use_adapter(app, ScriptedAdapter(PM(planning())))
    session = await start(client, folder)

    response = await client.post(f"/api/scoping/{session['id']}/mission")

    assert response.status_code == 409 and "Git" in response.json()["detail"]
    assert (await client.get(f"/api/scoping/{session['id']}")).json()["status"] == "planned"
    empty = scoping.project_context(folder)
    assert "empty" in empty


@needs_docker
async def test_from_an_idea_to_a_finished_mission(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    from tests.test_mission_runner import approve, finish

    builders = Script()
    pm = PM(asking("Who uses it?"), planning())

    def handler(request: LLMRequest) -> Completion:
        return pm(request) if request.purpose == "planner" else builders(request)

    use_adapter(app, ScriptedAdapter(handler))
    session = await start(client, repo)
    session = (
        await client.post(f"/api/scoping/{session['id']}/messages", json={"content": "just me"})
    ).json()
    mission = (await client.post(f"/api/scoping/{session['id']}/mission")).json()

    assert (await approve(client, mission)).json()["status"] == "running"
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "completed"
    assert {f.status for f in features.values()} == {"done"}


async def test_the_pm_is_told_to_copy_exact_interfaces_from_the_idea_into_the_plan(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    # Found in the first live mission: a plan that said "currentStreak calculates streaks" lost
    # the signatures the idea gave, so the builders and QA invented a different interface.
    pm = PM(asking("Who uses it?"))
    use_adapter(app, ScriptedAdapter(pm))

    await start(client, repo)

    prompt = pm.prompts[0]
    assert "copy them word for word" in prompt
    assert "builders and QA see only the plan" in prompt


async def test_the_pm_is_told_to_size_the_plan_to_the_task_and_use_fewer_validators(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    # Found in the first live mission: a two-function library got 4 milestones, a scaffold,
    # separate module and test features, and security reviews of a pure calculation.
    pm = PM(asking("Who uses it?"))
    use_adapter(app, ScriptedAdapter(pm))

    await start(client, repo)

    prompt = pm.prompts[0]
    assert "Size the plan to the task" in prompt
    assert "a module and its tests are one feature" in prompt
    assert "Add security only to a milestone that handles" in prompt
    assert "code-reviewer and security on every milestone" not in prompt


async def test_the_pm_plans_a_layout_the_user_can_run_on_their_own_computer(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    # The user found built projects with no folder structure, no README and no venv setup.
    pm = PM(asking("Who uses it?"))
    use_adapter(app, ScriptedAdapter(pm))

    await start(client, repo)

    prompt = pm.prompts[0]
    assert "src/ and tests/" in prompt and "a .gitignore" in prompt
    assert "README with local setup commands" in prompt and "virtual environment" in prompt


def test_devops_has_the_project_layout_skill_and_it_is_valid() -> None:
    from app.agents.persona import get_persona
    from app.skills.registry import SkillRegistry

    assert "project-layout" in get_persona("devops").skills
    skill = SkillRegistry(None).get("project-layout")
    assert ".venv/" in skill.body and "python3 -m venv .venv" in skill.body
    assert "Never create or commit the virtual environment" in skill.body
