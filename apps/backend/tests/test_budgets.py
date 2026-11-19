"""Budgets, costs and the delegation log (P4 step 5). Missions run for real (see
test_mission_runner); spending is seeded as real `llm_calls` rows, because the scripted model is
free."""

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import LLMCall, PersonaBudget
from app.events.log import EventType, append_event, list_events
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_catalog import _connection
from tests.test_mission_runner import Script, approve, finish, load, needs, new_mission, report

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


async def spend(
    app: FastAPI,
    run_id: str,
    cost: str | None,
    *,
    persona: str | None = None,
    provider: str = "scripted",
    model: str = "m",
    tokens: tuple[int, int] = (100, 50),
    error: str | None = None,
) -> None:
    async with app.state.sessionmaker.begin() as session:
        session.add(
            LLMCall(
                run_id=uuid.UUID(run_id),
                purpose="coder",
                provider=provider,
                model=model,
                latency_ms=5,
                persona_id=persona,
                input_tokens=tokens[0],
                output_tokens=tokens[1],
                est_cost_usd=Decimal(cost) if cost is not None else None,
                error=error,
            )
        )


async def events_of(app: FastAPI, run_id: str, *types: str) -> list[Any]:
    async with app.state.sessionmaker() as session:
        events = await list_events(session, uuid.UUID(run_id))
    return [e for e in events if not types or e.type in types]


async def test_a_persona_budget_can_be_set_listed_and_cleared(client: httpx.AsyncClient) -> None:
    assert (await client.put("/api/budgets/personas/backend", json={"budget_usd": 1.5})).json() == {
        "persona_id": "backend",
        "budget_usd": 1.5,
    }
    await client.put("/api/budgets/personas/backend", json={"budget_usd": 2})  # replaces it
    await client.put("/api/budgets/personas/qa", json={"budget_usd": 0.25})

    listed = (await client.get("/api/budgets/personas")).json()
    assert listed == [
        {"persona_id": "backend", "budget_usd": 2.0},
        {"persona_id": "qa", "budget_usd": 0.25},
    ]
    assert (await client.delete("/api/budgets/personas/qa")).status_code == 204
    assert (await client.delete("/api/budgets/personas/qa")).status_code == 404
    assert (
        await client.put("/api/budgets/personas/nobody", json={"budget_usd": 1})
    ).status_code == 404
    for bad in (0, -1, 20_000):
        assert (
            await client.put("/api/budgets/personas/qa", json={"budget_usd": bad})
        ).status_code == 422


@needs_docker
async def test_the_mission_budget_warns_once_at_80_percent_and_keeps_going(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo, budget_usd=1.0)
    await spend(app, mission["run_id"], "0.85")

    await approve(client, mission)
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "completed"  # a warning is not a stop
    [warning] = await events_of(
        app, mission["run_id"], "budget_warning"
    )  # two features, one warning
    assert warning.payload == {
        "scope": "mission",
        "spent_usd": 0.85,
        "budget_usd": 1.0,
        "percent": 85,
    }


@needs_docker
async def test_a_persona_over_80_percent_of_its_budget_is_warned_not_stopped(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    await client.put("/api/budgets/personas/backend", json={"budget_usd": 1.0})
    mission = await new_mission(client, repo)
    await spend(app, mission["run_id"], "0.9", persona="backend")
    await spend(app, mission["run_id"], "5", persona="frontend")  # another persona's spend

    await approve(client, mission)
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "completed"
    [warning] = await events_of(app, mission["run_id"], "budget_warning")
    assert (warning.payload["scope"], warning.payload["percent"]) == ("backend", 90)


@needs_docker
async def test_a_persona_over_its_budget_stops_in_needs_you_and_can_be_given_more(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    await client.put("/api/budgets/personas/backend", json={"budget_usd": 0.5})
    mission = await new_mission(client, repo)
    await spend(app, mission["run_id"], "0.9", persona="backend")

    await approve(client, mission)
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "needs_user" and features["todo-model"].attempts == 0  # never started
    [need] = await needs(app, mission["id"])
    assert need.kind == "persona_budget_reached" and need.options == [
        "raise_budget",
        "skip",
        "stop",
    ]
    assert need.evidence == {"persona_id": "backend", "spent_usd": 0.9, "budget_usd": 0.5}
    assert "backend has spent 0.9" in need.summary
    assert str(need.feature_id) == str(features["todo-model"].id)

    too_low = await client.post(
        f"/api/needs/{need.id}/answer", json={"action": "raise_budget", "budget_usd": 0.8}
    )
    assert too_low.status_code == 409 and "backend has spent" in too_low.json()["detail"]
    raised = await client.post(
        f"/api/needs/{need.id}/answer", json={"action": "raise_budget", "budget_usd": 5}
    )
    assert raised.json()["status"] == "running"
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "completed"
    async with app.state.sessionmaker() as session:
        assert (await session.get(PersonaBudget, "backend")).budget_usd == Decimal("5")


@needs_docker
async def test_skipping_the_feature_of_an_over_budget_persona_moves_on(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    await client.put("/api/budgets/personas/backend", json={"budget_usd": 0.5})
    mission = await new_mission(client, repo)
    await spend(app, mission["run_id"], "0.9", persona="backend")
    await approve(client, mission)
    await finish(app)
    [need] = await needs(app, mission["id"])

    await client.post(f"/api/needs/{need.id}/answer", json={"action": "skip"})
    await finish(app)

    _, features, _ = await load(app, mission["id"])
    assert (features["todo-model"].status, features["filter-helper"].status) == ("skipped", "done")


async def test_costs_are_real_totals_by_persona_and_by_model_and_unpriced_calls_are_counted(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    mission = await new_mission(client, repo)
    run = mission["run_id"]
    await client.put("/api/budgets/personas/backend", json={"budget_usd": 2})
    await spend(
        app, run, "1.50", persona="backend", provider="OpenAI", model="gpt-5", tokens=(1000, 200)
    )
    await spend(
        app, run, "0.50", persona="backend", provider="OpenAI", model="gpt-5", tokens=(500, 100)
    )
    await spend(app, run, "0.25", persona="qa", provider="Claude", model="haiku", tokens=(300, 30))
    await spend(
        app, run, None, persona="qa", provider="Local", model="qwen", tokens=(40, 4)
    )  # unpriced
    await spend(
        app, run, None, persona="qa", provider="Claude", model="haiku", error="429"
    )  # failed
    await spend(
        app, run, "0.10", persona=None, provider="OpenAI", model="gpt-5-mini", tokens=(10, 1)
    )

    costs = (await client.get(f"/api/missions/{mission['id']}/costs")).json()

    assert (costs["total_usd"], costs["calls"], costs["unpriced_calls"]) == (2.35, 6, 1)
    assert (costs["tokens_in"], costs["tokens_out"]) == (
        1000 + 500 + 300 + 40 + 100 + 10,
        200 + 100 + 30 + 4 + 50 + 1,
    )
    personas = {p["persona_id"]: p for p in costs["by_persona"]}
    assert personas["backend"] | {"x": 0} == {
        "persona_id": "backend",
        "budget_usd": 2.0,
        "spent_usd": 2.0,
        "calls": 2,
        "tokens_in": 1500,
        "tokens_out": 300,
        "x": 0,
    }
    assert personas["qa"]["budget_usd"] is None and personas[None]["spent_usd"] == 0.1
    assert [p["persona_id"] for p in costs["by_persona"]][:2] == ["backend", "qa"]  # biggest first
    models = {(m["provider"], m["model"]): m for m in costs["by_model"]}
    assert (
        models[("OpenAI", "gpt-5")]["calls"] == 2
        and models[("OpenAI", "gpt-5")]["spent_usd"] == 2.0
    )
    # The mission view carries the same real totals.
    shown = (await client.get(f"/api/missions/{mission['id']}")).json()
    assert (shown["spent_usd"], shown["tokens_in"], shown["tokens_out"]) == (2.35, 1950, 385)
    assert (
        await client.get("/api/missions/00000000-0000-0000-0000-000000000000/costs")
    ).status_code == 404


async def test_the_delegation_log_lists_assignments_with_reasons_and_this_missions_events(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    from tests.test_catalog import CATALOG, serve, service

    app.state.services.catalog = service(app.state.settings.data_dir, serve())
    await app.state.services.catalog.refresh()
    await _connection(app, "OpenAI", "openai", ["gpt-5"])
    await client.post("/api/assignments/auto", json={})
    await client.put("/api/budgets/personas/backend", json={"budget_usd": 3})
    mission = await new_mission(client, repo)
    async with app.state.sessionmaker.begin() as session:
        run = uuid.UUID(mission["run_id"])
        await append_event(
            session, run, EventType.TOOL_CALLED, payload={"tool": "read_file", "ok": True}
        )
        await append_event(
            session,
            run,
            EventType.KEY_ROTATED,
            agent_id="backend_01",
            payload={
                "connection": "OpenAI",
                "from_key": "key 1",
                "to_key": "key 2",
                "reason": "rate limit",
            },
        )
        await append_event(
            session,
            run,
            EventType.PROVIDER_FALLBACK,
            payload={
                "from_provider": "OpenAI",
                "to_provider": "Claude",
                "reason": "rate_limit: slow",
            },
        )
        await append_event(
            session,
            run,
            EventType.ESCALATED,
            payload={
                "persona": "backend",
                "feature_id": "todo-model",
                "attempt": 3,
                "connection": "OpenAI",
                "model": "gpt-5",
                "reason": "attempts 1 to 2 were rejected",
            },
        )

    log = (await client.get(f"/api/missions/{mission['id']}/delegation")).json()

    assert [e["type"] for e in log["events"]] == ["key_rotated", "provider_fallback", "escalated"]
    assert log["events"][0]["agent_id"] == "backend_01"
    assert log["events"][2]["payload"]["model"] == "gpt-5"
    by_persona = {a["persona_id"]: a for a in log["assignments"]}
    assert len(by_persona) == 10 and by_persona["pm"]["set_by"] == "auto"
    assert by_persona["backend"]["model"] == "gpt-5" and by_persona["backend"]["budget_usd"] == 3.0
    assert by_persona["backend"]["reason"].startswith("cheapest model meeting")
    assert by_persona["pm"]["budget_usd"] is None and CATALOG


@needs_docker
async def test_the_escalation_is_recorded_in_the_delegation_log_on_the_last_attempt_only(
    app: FastAPI, client: httpx.AsyncClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.missions import runner as runner_module
    from tests.test_catalog import CATALOG, serve, service

    app.state.services.catalog = service(app.state.settings.data_dir, serve())
    openai = await _connection(app, "OpenAI", "openai", ["gpt-5-mini", "gpt-5"])
    await client.put(
        "/api/assignments/backend",
        json={
            "primary": {"connection_id": str(openai.id), "model": "gpt-5-mini"},
            "escalate": {"connection_id": str(openai.id), "model": "gpt-5"},
        },
    )

    async def no_changes(role: str, **kwargs: Any) -> str:
        return report("Todo model")  # a valid report, but no files changed: it is rejected

    monkeypatch.setattr(runner_module, "call_crew", no_changes)
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    [escalated] = await events_of(app, mission["run_id"], "escalated")
    assert escalated.payload == {
        "persona": "backend",
        "feature_id": "todo-model",
        "attempt": 3,
        "connection": "OpenAI",
        "model": "gpt-5",
        "reason": "attempts 1 to 2 were rejected",
    }
    assert escalated.agent_id == "backend_03" and CATALOG
    log = (await client.get(f"/api/missions/{mission['id']}/delegation")).json()
    assert [e["type"] for e in log["events"]] == ["escalated", "need_raised"]
    assert select  # (imported for ad-hoc queries when debugging)
