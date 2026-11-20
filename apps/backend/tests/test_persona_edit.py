"""Editing the team (PRD §11.1): change a built-in persona, make a custom one, version every
change, and see the next mission use it."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.agents.persona import all_personas, builtin_personas, get_persona
from app.providers.base import Completion, LLMRequest
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import PLAN, Script, approve, finish, load, new_mission
from tests.test_persona_crew import REPORT, feature, start
from tests.test_skills import make_skill

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
LONG = "You are the motion designer on this team. You add animation that helps, never decoration."


async def put(client: httpx.AsyncClient, persona_id: str, **body: object) -> httpx.Response:
    return await client.put(f"/api/personas/{persona_id}", json=body)


# ---------- listing ----------


async def test_the_team_lists_every_persona_with_its_source_version_and_instructions(
    client: httpx.AsyncClient,
) -> None:
    team = {p["id"]: p for p in (await client.get("/api/personas")).json()}

    assert set(team) == set(builtin_personas())
    designer = team["designer"]
    assert designer["source"] == "builtin" and designer["version"] == 1
    assert designer["skills"] == ["ui-ux-pro", "accessibility", "design-tokens"]
    assert designer["missing_skills"] == [] and "product designer" in designer["instructions"]
    assert (await client.get("/api/personas/designer")).json()["id"] == "designer"
    assert (await client.get("/api/personas/ghost")).status_code == 404


# ---------- editing a built-in persona ----------


async def test_editing_a_built_in_persona_makes_a_new_version_and_keeps_the_old_one(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    make_skill(
        app.state.settings.data_dir / "skills", "motion-graphics", description="Animate UIs."
    )

    response = await put(
        client,
        "designer",
        skills=["ui-ux-pro", "accessibility", "design-tokens", "motion-graphics"],
        instructions=LONG,
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["source"], body["version"]) == ("customized", 2)
    assert body["skills"][-1] == "motion-graphics" and body["instructions"] == LONG
    assert (
        get_persona("designer").version == 2
        and "motion designer" in get_persona("designer").instructions
    )
    versions = (await client.get("/api/personas/designer/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[1]["snapshot"]["skills"] == ["ui-ux-pro", "accessibility", "design-tokens"]
    assert "product designer" in versions[1]["snapshot"]["instructions"]  # the shipped default
    assert versions[0]["snapshot"]["skills"][-1] == "motion-graphics"
    # A second edit is version 3; the same edit again is not a change.
    assert (await put(client, "designer", name="Motion designer")).json()["version"] == 3
    assert (await put(client, "designer", name="Motion designer")).json()["version"] == 3
    assert [v["version"] for v in (await client.get("/api/personas/designer/versions")).json()] == [
        3,
        2,
        1,
    ]


async def test_a_bad_edit_is_refused_and_changes_nothing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    cases = [
        ({"skills": ["ghost-skill"]}, "no such skill: ghost-skill"),
        ({"skills": ["rest-api", "rest-api"]}, "different skills"),
        ({"instructions": "too short"}, "instructions must be"),
        ({"plugins": ["figma"]}, "no such plugin: figma"),
    ]
    for body, message in cases:
        response = await put(client, "backend", **body)
        assert response.status_code == 422 and message in response.json()["detail"], body
    assert (await put(client, "ghost", name="Nobody")).status_code == 404
    assert (await put(client, "backend", name="x")).status_code == 422  # name too short
    backend = (await client.get("/api/personas/backend")).json()
    assert backend["version"] == 1 and backend["source"] == "builtin"


async def test_resetting_a_built_in_persona_returns_to_the_default_and_versions_keep_rising(
    client: httpx.AsyncClient,
) -> None:
    await put(client, "backend", name="API engineer")

    reset = await client.delete("/api/personas/backend")

    assert reset.status_code == 200
    body = reset.json()
    assert (body["name"], body["source"], body["version"]) == ("Backend engineer", "builtin", 1)
    assert get_persona("backend").name == "Backend engineer"
    assert (await client.delete("/api/personas/backend")).status_code == 409  # already default
    # Editing again does not reuse version 2.
    assert (await put(client, "backend", name="API engineer 2")).json()["version"] == 3


async def test_editing_the_fixed_parts_is_not_possible(client: httpx.AsyncClient) -> None:
    body = (await put(client, "code-reviewer", name="Reviewer", instructions=LONG)).json()

    assert body["kind"] == "validator"  # the kind never changes
    changed = await client.put("/api/personas/code-reviewer", json={"kind": "worker"})
    assert changed.status_code == 200 and changed.json()["kind"] == "validator"  # ignored


# ---------- custom personas ----------


async def test_a_custom_worker_is_created_listed_and_removed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    make_skill(app.state.settings.data_dir / "skills", "motion-graphics")

    created = await client.post(
        "/api/personas",
        json={
            "id": "motion",
            "name": "Motion designer",
            "instructions": LONG,
            "skills": ["motion-graphics"],
        },
    )

    body = created.json()
    assert created.status_code == 201
    assert (body["kind"], body["source"], body["version"]) == ("worker", "custom", 1)
    assert "motion" in all_personas() and "motion" not in builtin_personas()
    assert "motion" in [p["id"] for p in (await client.get("/api/personas")).json()]
    assert (await client.delete("/api/personas/motion")).status_code == 204
    assert "motion" not in all_personas()
    assert (await client.get("/api/personas/motion")).status_code == 404


async def test_creating_a_persona_checks_the_id_and_the_skills(client: httpx.AsyncClient) -> None:
    good = {"id": "motion", "name": "Motion designer", "instructions": LONG, "skills": []}

    for override, status, message in [
        ({"id": "Motion Designer"}, 422, "lowercase"),
        ({"id": "backend"}, 409, "already exists"),
        ({"skills": ["ghost"]}, 422, "no such skill"),
        ({"instructions": "short"}, 422, ""),
    ]:
        response = await client.post("/api/personas", json={**good, **override})
        assert response.status_code == status, override
        assert message in json.dumps(response.json())
    assert (await client.post("/api/personas", json=good)).status_code == 201
    assert (await client.post("/api/personas", json=good)).status_code == 409


async def test_a_persona_with_work_in_a_live_mission_cannot_be_deleted(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    await client.post(
        "/api/personas",
        json={"id": "motion", "name": "Motion designer", "instructions": LONG, "skills": []},
    )
    plan = json.loads(json.dumps(PLAN))
    plan["milestones"][0]["features"][0]["persona"] = "motion"
    await new_mission(client, repo, plan)  # awaiting approval: the work is waiting

    refused = await client.delete("/api/personas/motion")

    assert refused.status_code == 409 and "mission in progress" in refused.json()["detail"]
    assert "motion" in all_personas()


# ---------- the team uses what you edited ----------


async def test_a_plan_can_use_a_custom_persona_and_the_pm_is_told_about_it(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    plan = json.loads(json.dumps(PLAN))
    plan["milestones"][0]["features"][0]["persona"] = "motion"
    before = await client.post(
        "/api/missions",
        json={
            "project_id": (
                await client.post("/api/projects", json={"workspace_path": str(repo)})
            ).json()["id"],
            "idea": "A todo app",
            "plan": plan,
        },
    )
    assert before.status_code == 422 and "not a worker persona" in before.text  # unknown yet

    await client.post(
        "/api/personas",
        json={"id": "motion", "name": "Motion designer", "instructions": LONG, "skills": []},
    )

    mission = await new_mission(client, repo, plan)
    assert mission["milestones"][0]["features"][0]["persona"] == "motion"
    from app.missions.scoping import _team

    assert "- motion (Motion designer): You are the motion designer" in _team()


async def test_the_crew_runs_as_the_edited_persona_with_its_new_skill(
    app: FastAPI, workspace: Path
) -> None:
    make_skill(
        app.state.settings.data_dir / "skills", "motion-graphics", description="Animate UIs."
    )
    seen: list[LLMRequest] = []

    def handler(request: LLMRequest) -> Completion:
        seen.append(request)
        return Completion(content=json.dumps(REPORT))

    use_adapter(app, ScriptedAdapter(handler))
    run_id, worktree = await start(app, workspace)
    edited = get_persona("designer").model_copy(
        update={
            "instructions": LONG,
            "skills": [*get_persona("designer").skills, "motion-graphics"],
            "version": 2,
        }
    )

    import uuid

    from app.a2a.client import call_crew
    from app.a2a.protocol import PersonaRequest
    from app.telemetry.hub import TelemetryHub
    from tests.test_persona_crew import PersonaScript  # noqa: F401  (same request builder below)

    services = app.state.services
    await call_crew(
        "persona",
        hub=TelemetryHub(services, run_id),
        http=services.a2a_http,
        settings=services.settings,
        prompt="designer",
        request=PersonaRequest(
            exchange_id=uuid.uuid4(),
            run_id=run_id,
            agent_id="designer_01",
            worktree=str(worktree),
            workspace=str(workspace),
            persona_id="designer",
            persona=edited,  # what the orchestrator sends: the persona as the user has it now
            feature=feature("designer"),
        ),
        parent="test",
    )

    prompt = "\n".join(m.content or "" for m in seen[0].messages)
    assert "motion designer" in prompt and "product designer" not in prompt
    assert "- motion-graphics: Animate UIs." in prompt


@needs_docker
async def test_after_an_edit_the_next_mission_uses_it_and_the_handoff_records_the_version(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    prompts: list[str] = []
    script = Script()

    def handler(request: LLMRequest) -> Completion:
        prompts.append("\n".join(m.content or "" for m in request.messages))
        return script(request)

    use_adapter(app, ScriptedAdapter(handler))
    make_skill(
        app.state.settings.data_dir / "skills", "motion-graphics", description="Animate UIs."
    )
    await put(
        client,
        "backend",
        instructions=LONG + " You also write the API.",
        skills=["rest-api", "motion-graphics"],
    )
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    backend_prompt = next(p for p in prompts if "Feature: Todo model" in p)
    assert "motion designer on this team" in backend_prompt
    assert "- motion-graphics: Animate UIs." in backend_prompt
    path = Path(run.worktree_path or "") / ".hex" / "mission" / "handoffs.jsonl"
    handoffs = {h["feature_id"]: h for h in map(json.loads, path.read_text().splitlines())}
    assert handoffs["todo-model"]["persona_version"] == 2  # the edited backend persona
    assert handoffs["filter-helper"]["persona_version"] == 1  # frontend was not touched


# ---------- model assignment for custom personas ----------


async def test_a_custom_persona_gets_a_model_like_any_builder(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/personas",
        json={"id": "motion", "name": "Motion designer", "instructions": LONG, "skills": []},
    )

    result = (await client.post("/api/assignments/auto", json={"dry_run": True})).json()

    proposal = next(p for p in result["proposals"] if p["persona_id"] == "motion")
    assert "no requirements are defined" not in proposal["reason"]  # judged like a worker
    assert (await client.put("/api/assignments/ghost", json={})).status_code in (404, 422)
