"""Provenance (PRD §14.2): a changed file is traced back to the feature, persona version, skills,
model calls, validators and the user's approval, all read from what was recorded, each with its
place in the audit chain."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import AgentEvent, LLMCall
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import (
    FAILING_TEST,
    GOOD,
    PLAN,
    Script,
    approve,
    finish,
    load,
    new_mission,
)
from tests.test_run_workflow import FILTER_JS, FILTER_TEST, TODOS_JS, TODOS_TEST
from tests.test_validators import Validators

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


def plan_with_review() -> dict[str, Any]:
    plan = json.loads(json.dumps(PLAN))
    for milestone in plan["milestones"]:
        milestone["validators"] = ["code-reviewer"]
    return plan


async def provenance(
    client: httpx.AsyncClient, mission: dict[str, Any], **params: str
) -> httpx.Response:
    return await client.get(f"/api/missions/{mission['id']}/provenance", params=params)


async def run_mission(
    app: FastAPI,
    client: httpx.AsyncClient,
    repo: Path,
    script: Script,
    plan: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    use_adapter(app, ScriptedAdapter(Validators(script)))
    mission = await new_mission(client, repo, plan or plan_with_review(), **extra)
    await approve(client, mission)
    await finish(app)
    assert (await load(app, mission["id"]))[0].status == "completed"
    return mission


# ---------- a file back to its origin ----------


@needs_docker
async def test_a_changed_file_is_traced_to_its_feature_persona_model_skills_and_approval(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    await client.put("/api/personas/backend", json={"name": "API engineer"})  # persona version 2
    mission = await run_mission(app, client, repo, Script())

    document = (await provenance(client, mission, path="src/todos.js")).json()

    [file] = document["files"]
    [change] = file["changes"]
    assert file["path"] == "src/todos.js"
    assert change["feature"] == {"id": "todo-model", "title": "Todo model", "milestone": "m1-model"}
    assert change["persona"] == {"id": "backend", "version": 2}  # the version that did the work
    assert (change["agent_id"], change["attempt"]) == ("backend_01", 1)
    assert change["model_used"] == "scripted:scripted-model"
    assert {s["name"] for s in change["skills"]} == {"rest-api", "auth-basics", "testing-backend"}
    assert all(s["version"].startswith(s["name"] + "@") for s in change["skills"])
    assert [(c["command"], c["exit_code"]) for c in change["commands"]] == [("node --test", 0)]
    assert change["validated_by"] == [{"validator": "code-reviewer", "round": 1, "verdict": "pass"}]
    assert len(change["commit"]) == 40
    # Every model call of the attempt, with the hashes of what was sent and received.
    assert change["model_calls"]
    for call in change["model_calls"]:
        assert call["purpose"] == "coder" and len(call["request_sha256"]) == 64
    # The plan and the approval.
    assert [f["id"] for f in document["plan"]] == ["todo-model", "filter-helper"]
    assert document["mission"]["title"] == "Todo app" and document["approval"]["seq"] > 0
    # ...and their place in the audit chain: the hashes are the stored events' own.
    _, _, run = await load(app, mission["id"])
    async with app.state.sessionmaker() as session:
        events = {
            e.seq: e
            for e in await session.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id))
        }
    assert document["approval"]["hash"] == events[document["approval"]["seq"]].hash
    handoff_event = change["handoff_event"]
    assert events[handoff_event["seq"]].type == "handoff_recorded"
    assert events[handoff_event["seq"]].hash == handoff_event["hash"]
    assert (
        document["audit"]["ok"] is True
        and document["audit"]["head"]
        == (await client.get("/api/audit/head", params={"mission_id": mission["id"]})).json()[
            "head"
        ]
    )


@needs_docker
async def test_the_whole_mission_lists_every_changed_file_with_who_changed_it(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await run_mission(app, client, repo, Script())

    document = (await provenance(client, mission)).json()

    by_path = {f["path"]: [c["feature"]["id"] for c in f["changes"]] for f in document["files"]}
    assert by_path == {
        "src/todos.js": ["todo-model"],
        "src/todos.test.js": ["todo-model"],
        "src/filter.js": ["filter-helper"],
        "src/filter.test.js": ["filter-helper"],
    }
    personas = {f["path"]: f["changes"][0]["persona"]["id"] for f in document["files"]}
    assert personas["src/todos.js"] == "backend" and personas["src/filter.js"] == "frontend"


@needs_docker
async def test_a_file_touched_by_two_features_lists_both_in_order(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    script = Script(
        {
            ("Todo model", 0): GOOD["Todo model"],
            ("Filter helper", 0): [
                ("src/filter.js", FILTER_JS),
                ("src/filter.test.js", FILTER_TEST),
                ("src/todos.js", TODOS_JS + "// also touched by the filter feature\n"),
            ],
        }
    )
    mission = await run_mission(app, client, repo, script)

    [file] = (await provenance(client, mission, path="src/todos.js")).json()["files"]

    assert [(c["feature"]["id"], c["persona"]["id"]) for c in file["changes"]] == [
        ("todo-model", "backend"), ("filter-helper", "frontend"),
    ]  # fmt: skip
    assert file["changes"][0]["commit"] != file["changes"][1]["commit"]


@needs_docker
async def test_after_a_retry_the_provenance_is_the_attempt_that_was_accepted(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    script = Script(
        {
            ("Todo model", 0): [("src/todos.js", TODOS_JS), ("src/todos.test.js", FAILING_TEST)],
            ("Todo model", 1): [("src/todos.test.js", TODOS_TEST)],
            ("Filter helper", 0): GOOD["Filter helper"],
        }
    )
    mission = await run_mission(app, client, repo, script)

    [file] = (await provenance(client, mission, path="src/todos.test.js")).json()["files"]

    [change] = file["changes"]
    assert (change["attempt"], change["agent_id"]) == (2, "backend_02")
    _, _, run = await load(app, mission["id"])
    async with app.state.sessionmaker() as session:
        every = list(
            await session.scalars(
                select(LLMCall).where(LLMCall.run_id == run.id, LLMCall.persona_id == "backend")
            )
        )
    assert (
        0 < len(change["model_calls"]) < len(every)
    )  # the failed first attempt's calls are not here
    assert change["feature"]["id"] == "todo-model"


@needs_docker
async def test_the_variant_and_a_users_decisions_are_part_of_the_record(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    await client.post(
        "/api/variants",
        json={
            "id": "terse",
            "name": "Terse",
            "personas": {
                "backend": {
                    "instructions": "You are a terse backend engineer who writes very little.",
                    "skills": [],
                }
            },
        },
    )
    mission = await run_mission(app, client, repo, Script(), variant_id="terse")

    document = (await provenance(client, mission)).json()

    assert document["mission"]["variant_id"] == "terse"
    backend = next(f for f in document["files"] if f["path"] == "src/todos.js")["changes"][0]
    assert backend["variant_id"] == "terse" and backend["skills"] == []
    assert document["decisions"] == []  # nobody had to decide anything


# ---------- the export ----------


@needs_docker
async def test_the_record_exports_as_w3c_prov_json_with_consistent_references(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await run_mission(app, client, repo, Script())

    prov = (await provenance(client, mission, format="prov")).json()

    assert set(prov) == {
        "prefix", "entity", "activity", "agent", "wasGeneratedBy", "used", "wasAssociatedWith",
        "actedOnBehalfOf", "wasDerivedFrom",
    }  # fmt: skip
    assert "hex:file-src/todos.js" in prov["entity"] and "hex:approval" in prov["activity"]
    assert "hex:user" in prov["agent"] and "hex:persona-backend-v1" in prov["agent"]
    known = set(prov["entity"]) | set(prov["activity"]) | set(prov["agent"])
    for section in (
        "wasGeneratedBy",
        "used",
        "wasAssociatedWith",
        "actedOnBehalfOf",
        "wasDerivedFrom",
    ):
        assert prov[section], section
        for relation in prov[section].values():
            for value in relation.values():
                assert value in known, (
                    section,
                    value,
                )  # nothing points at something that is not there
    generated = {r["prov:entity"] for r in prov["wasGeneratedBy"].values()}
    assert generated == {f"hex:file-src/{n}.js" for n in ("todos", "filter")} | {
        f"hex:file-src/{n}.test.js" for n in ("todos", "filter")
    }
    activity = next(a for k, a in prov["activity"].items() if k.startswith("hex:work-todo-model"))
    assert (
        activity["hex:model"] == "scripted:scripted-model" and len(activity["hex:audit_hash"]) == 64
    )
    assert any(
        k.startswith("hex:call-") for k in prov["activity"]
    )  # the model calls are activities too


# ---------- errors ----------


async def test_unknown_missions_and_files_are_refused(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    assert (await client.get(f"/api/missions/{uuid.uuid4()}/provenance")).status_code == 404
    mission = await new_mission(client, repo)  # created, never run: nothing changed yet

    empty = (await provenance(client, mission)).json()
    assert empty["files"] == [] and empty["approval"] is None and empty["audit"]["ok"] is True
    missing = await provenance(client, mission, path="src/none.js")
    assert missing.status_code == 404 and "did not change that file" in missing.json()["detail"]
    assert (await provenance(client, mission, format="xml")).status_code == 422
