"""Prompt and skill variants (PRD §11.5, E5): a mission can run under a named set of changes to
personas' instructions and skills, and the variant's id is on everything it does."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.agents.persona import get_persona
from app.agents.variants import PersonaOverride, Variant, apply
from app.db.models import LLMCall
from app.events.log import list_events
from app.providers.base import Completion, LLMRequest
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import PLAN, Script, approve, finish, load, new_mission
from tests.test_scoping import PM, planning
from tests.test_validators import Validators

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
TERSE = "You are the backend engineer. Answer tersely and write only the code that is asked for."
CAREFUL = "You are the security reviewer. Be paranoid about every query and every file path."


def body(**extra: Any) -> dict[str, Any]:
    return {
        "id": "terse",
        "name": "Terse builders",
        "description": "Short instructions, no skills.",
        "personas": {"backend": {"instructions": TERSE, "skills": []}},
        **extra,
    }


# ---------- applying a variant ----------


def test_a_variant_changes_instructions_and_skills_and_nothing_else() -> None:
    backend = get_persona("backend")
    variant = Variant(
        "v",
        "V",
        "",
        {
            "backend": PersonaOverride(
                instructions=f"  {TERSE}  ", skills=["rest-api", "rest-api"]
            ),
            "qa": PersonaOverride(skills=[]),
        },
    )

    changed = apply(backend, variant)

    assert changed.instructions == TERSE and changed.skills == ["rest-api"]  # tidied, deduplicated
    assert (changed.id, changed.kind, changed.version, changed.plugins) == (
        backend.id, backend.kind, backend.version, backend.plugins,
    )  # fmt: skip
    assert backend.skills == [
        "rest-api",
        "auth-basics",
        "testing-backend",
    ]  # the original is intact
    assert apply(get_persona("qa"), variant).skills == []  # skills can be turned off
    assert apply(get_persona("qa"), variant).instructions == get_persona("qa").instructions
    assert apply(get_persona("designer"), variant) is get_persona("designer")  # not named: same
    assert apply(backend, None) is backend


# ---------- the API ----------


async def test_variants_are_created_listed_edited_and_deleted(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/variants", json=body())

    assert created.status_code == 201
    made = created.json()
    assert made["id"] == "terse" and made["missions"] == 0
    assert made["personas"]["backend"] == {"instructions": TERSE, "skills": []}
    assert [v["id"] for v in (await client.get("/api/variants")).json()] == ["terse"]
    edited = await client.put(
        "/api/variants/terse", json={"name": "Terse", "personas": {"qa": {"skills": []}}}
    )
    assert edited.status_code == 200
    assert edited.json()["name"] == "Terse" and list(edited.json()["personas"]) == ["qa"]
    assert (await client.delete("/api/variants/terse")).status_code == 204
    assert (await client.get("/api/variants")).json() == []
    assert (await client.delete("/api/variants/terse")).status_code == 404
    assert (await client.put("/api/variants/terse", json={"name": "x y"})).status_code == 404


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "Bad Id"}, "lowercase"),
        ({"personas": {}}, "1 to 12 personas"),
        ({"personas": {"ghost": {"skills": []}}}, "no such persona: ghost"),
        ({"personas": {"backend": {}}}, "change its instructions or its skills"),
        ({"personas": {"backend": {"instructions": "short"}}}, "instructions must be"),
        ({"personas": {"backend": {"skills": ["ghost-skill"]}}}, "no such skill: ghost-skill"),
        ({"name": "x"}, "at least 2 characters"),
    ],
)
async def test_a_bad_variant_is_refused_with_the_reason(
    client: httpx.AsyncClient, change: dict[str, Any], message: str
) -> None:
    response = await client.post("/api/variants", json=body(**change))

    assert response.status_code == 422 and message in response.text, response.text
    assert (await client.get("/api/variants")).json() == []


async def test_a_variant_id_is_taken_once(client: httpx.AsyncClient) -> None:
    await client.post("/api/variants", json=body())

    again = await client.post("/api/variants", json=body())

    assert again.status_code == 409 and "already exists" in again.json()["detail"]


async def test_a_mission_or_scoping_session_cannot_use_a_variant_that_does_not_exist(
    client: httpx.AsyncClient, repo: Path
) -> None:
    project = (await client.post("/api/projects", json={"workspace_path": str(repo)})).json()

    mission = await client.post(
        "/api/missions",
        json={"project_id": project["id"], "idea": "todo", "plan": PLAN, "variant_id": "ghost"},
    )
    session = await client.post(
        "/api/scoping",
        json={"project_id": project["id"], "idea": "todo app", "variant_id": "ghost"},
    )

    assert mission.status_code == 404 and "no such variant: ghost" in mission.text
    assert session.status_code == 404


# ---------- running under a variant ----------


@needs_docker
async def test_a_mission_runs_under_its_variant_and_everything_it_did_carries_the_id(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    prompts: list[str] = []
    script = Script()

    def handler(request: LLMRequest) -> Completion:
        prompts.append("\n".join(m.content or "" for m in request.messages))
        return script(request)

    use_adapter(app, ScriptedAdapter(handler))
    await client.post("/api/variants", json=body())
    mission = await new_mission(client, repo, variant_id="terse")
    assert mission["variant_id"] == "terse"

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    backend = next(p for p in prompts if "Feature: Todo model" in p)
    assert TERSE in backend and "product designer" not in backend
    assert "Skills you can load" not in backend  # the variant turned the backend's skills off
    frontend = next(p for p in prompts if "Feature: Filter helper" in p)
    assert "Skills you can load" in frontend and TERSE not in frontend  # others are as they were
    async with app.state.sessionmaker() as session:
        calls = list(await session.scalars(select(LLMCall).where(LLMCall.run_id == run.id)))
        events = await list_events(session, run.id)
    assert calls and {c.variant_id for c in calls} == {"terse"}  # on every model call
    chosen = [e.payload for e in events if e.type == "prompt_variant_selected"]
    assert chosen == [{"role": "backend", "variant": "terse"}]
    path = Path(run.worktree_path or "") / ".hex" / "mission" / "handoffs.jsonl"
    handoffs = {h["feature_id"]: h for h in map(json.loads, path.read_text().splitlines())}
    assert all(h["variant_id"] == "terse" for h in handoffs.values())
    assert handoffs["todo-model"]["skills"] == []  # offered nothing
    assert len(handoffs["filter-helper"]["skills"]) == 3
    # The mission now pins the variant's meaning.
    listed = (await client.get("/api/variants")).json()
    assert listed[0]["missions"] == 1
    blocked = await client.put("/api/variants/terse", json={"personas": {"qa": {"skills": []}}})
    assert blocked.status_code == 409 and "make a new variant" in blocked.json()["detail"]
    assert (await client.put("/api/variants/terse", json={"name": "Renamed"})).status_code == 200
    kept = await client.delete("/api/variants/terse")
    assert kept.status_code == 409 and "kept for the record" in kept.json()["detail"]


@needs_docker
async def test_without_a_variant_nothing_is_tagged_or_announced(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    _, _, run = await load(app, mission["id"])
    async with app.state.sessionmaker() as session:
        calls = list(await session.scalars(select(LLMCall).where(LLMCall.run_id == run.id)))
        events = await list_events(session, run.id)
    assert calls and {c.variant_id for c in calls} == {None}
    assert not [e for e in events if e.type == "prompt_variant_selected"]


@needs_docker
async def test_a_variant_reaches_the_validators_too(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    reviews: list[tuple[str, str | None]] = []
    play = Validators(Script())

    def handler(request: LLMRequest) -> Completion:
        if request.purpose == "reviewer":
            text = "\n".join(m.content or "" for m in request.messages)
            reviews.append((text, None))
        return play(request)

    use_adapter(app, ScriptedAdapter(handler))
    await client.post(
        "/api/variants",
        json=body(id="paranoid", name="Paranoid", personas={"security": {"instructions": CAREFUL}}),
    )
    plan = json.loads(json.dumps(PLAN))
    for milestone in plan["milestones"]:
        milestone["validators"] = ["security"]
    mission = await new_mission(client, repo, plan, variant_id="paranoid")

    await approve(client, mission)
    await finish(app)

    _, _, run = await load(app, mission["id"])
    security = [text for text, _ in reviews if "for security problems" in text]
    assert security and all(CAREFUL in text for text in security)
    async with app.state.sessionmaker() as session:
        calls = list(
            await session.scalars(
                select(LLMCall).where(LLMCall.run_id == run.id, LLMCall.purpose == "reviewer")
            )
        )
    assert calls and {c.variant_id for c in calls} == {"paranoid"}


async def test_the_pm_scopes_under_the_variant_and_its_calls_carry_the_id(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    pm = PM(planning())
    use_adapter(app, ScriptedAdapter(pm))
    await client.post(
        "/api/variants",
        json=body(
            id="lean-pm",
            name="Lean PM",
            personas={
                "pm": {
                    "instructions": "You are a PM who plans in the fewest features possible.",
                    "skills": [],
                }
            },
        ),
    )
    project = (await client.post("/api/projects", json={"workspace_path": str(repo)})).json()

    session = (
        await client.post(
            "/api/scoping",
            json={"project_id": project["id"], "idea": "a todo app", "variant_id": "lean-pm"},
        )
    ).json()

    assert session["variant_id"] == "lean-pm"
    prompt = pm.prompts[0]
    assert "who plans in the fewest features possible" in prompt
    assert "## Skill:" not in prompt  # the PM's skills were turned off by the variant
    async with app.state.sessionmaker() as db:
        calls = list(await db.scalars(select(LLMCall).where(LLMCall.run_id == session["run_id"])))
    assert calls and {c.variant_id for c in calls} == {"lean-pm"}
    mission = (await client.post(f"/api/scoping/{session['id']}/mission")).json()
    assert mission["variant_id"] == "lean-pm"  # the plan becomes a mission under the same variant


async def test_scoping_without_a_variant_still_uses_the_pms_skills(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    pm = PM(planning())
    use_adapter(app, ScriptedAdapter(pm))
    project = (await client.post("/api/projects", json={"workspace_path": str(repo)})).json()

    await client.post("/api/scoping", json={"project_id": project["id"], "idea": "a todo app"})

    assert "## Skill: scoping-interview" in pm.prompts[0]
