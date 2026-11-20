"""Metrics (PRD §14.3): every figure is computed from stored data, so each test seeds exactly what
it expects to see and checks the numbers; what cannot be measured is null, not a guess."""

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text

from app.db.models import FeatureRow, LLMCall, Milestone, ValidatorReportRow
from app.events.log import EventType, append_event
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import PLAN, Script, approve, finish, load, new_mission
from tests.test_run_contract import repo_with

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


async def call(
    app: FastAPI,
    run_id: uuid.UUID,
    *,
    persona: str | None,
    provider: str = "groq",
    model: str = "m",
    inp: int | None = 100,
    out: int | None = 50,
    cost: str | None = "0.01",
    latency: int = 100,
    error: str | None = None,
    variant: str | None = None,
) -> None:
    async with app.state.sessionmaker.begin() as session:
        session.add(
            LLMCall(
                run_id=run_id, purpose="coder", provider=provider, model=model, input_tokens=inp,
                output_tokens=out, est_cost_usd=Decimal(cost) if cost else None, latency_ms=latency,
                attempts=1, error=error, persona_id=persona, variant_id=variant,
            )
        )  # fmt: skip


async def event(app: FastAPI, run_id: uuid.UUID, kind: EventType, payload: dict[str, Any]) -> None:
    async with app.state.sessionmaker.begin() as session:
        await append_event(session, run_id, kind, payload=payload)


async def project_with_missions(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, count: int = 2, **extra: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = repo_with(tmp_path / "app", None) if (tmp_path / "app").exists() else None
    if root is None:
        (tmp_path / "app").mkdir()
        root = repo_with(tmp_path / "app", None)
    project = (await client.post("/api/projects", json={"workspace_path": str(root)})).json()
    missions = []
    for _ in range(count):
        response = await client.post(
            "/api/missions",
            json={"project_id": project["id"], "idea": "todo app", "plan": PLAN, **extra},
        )
        assert response.status_code == 201, response.text
        missions.append(response.json())
    return project, missions


async def metrics(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/api/metrics", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------- calls ----------


async def test_calls_are_totalled_and_split_by_persona_and_model(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    _, [first, second] = await project_with_missions(app, client, tmp_path)
    run = uuid.UUID(first["run_id"])
    other = uuid.UUID(second["run_id"])
    await call(
        app, run, persona="backend", model="big", inp=1000, out=200, cost="0.30", latency=400
    )
    await call(app, run, persona="backend", model="big", inp=500, out=100, cost="0.10", latency=200)
    await call(
        app, run, persona="frontend", model="small", inp=300, out=60, cost="0.02", latency=100
    )
    await call(
        app,
        run,
        persona="backend",
        model="big",
        inp=None,
        out=None,
        cost=None,
        latency=50,
        error="429",
    )
    await call(
        app,
        run,
        persona="qa",
        provider="ollama",
        model="local",
        inp=80,
        out=20,
        cost=None,
        latency=900,
    )
    await call(app, other, persona="backend", model="big", inp=10, out=10, cost="0.01", latency=100)

    one = await metrics(client, mission_id=first["id"])

    calls = one["calls"]
    assert (calls["count"], calls["failed"], calls["error_rate"]) == (5, 1, 0.2)
    assert (calls["input_tokens"], calls["output_tokens"]) == (1880, 380)
    assert calls["cost_usd"] == pytest.approx(0.42)
    assert calls["without_cost"] == 1  # the local model answered, with no price to charge
    assert calls["avg_latency_ms"] == 330  # (400 + 200 + 100 + 50 + 900) / 5
    assert (calls["p50_latency_ms"], calls["p95_latency_ms"]) == (
        300,
        825,
    )  # of the four that succeeded
    personas = {p["persona"]: p for p in one["by_persona"]}
    assert personas["backend"]["calls"] == 3 and personas["backend"]["failed"] == 1
    assert personas["backend"]["cost_usd"] == pytest.approx(0.40)
    assert personas["backend"]["input_tokens"] == 1500
    assert [p["persona"] for p in one["by_persona"]][0] == "backend"  # most expensive first
    models = {(m["provider"], m["model"]): m for m in one["by_model"]}
    assert models[("groq", "big")]["calls"] == 3 and models[("ollama", "local")]["cost_usd"] == 0.0
    # The other mission's call is not counted here, and both are counted together.
    assert (await metrics(client, mission_id=second["id"]))["calls"]["count"] == 1


async def test_a_project_with_no_calls_has_zeroes_and_no_invented_rates(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    project, _ = await project_with_missions(app, client, tmp_path, count=1)

    body = await metrics(client, project_id=project["id"])

    assert body["calls"]["count"] == 0 and body["calls"]["error_rate"] is None
    assert body["calls"]["p50_latency_ms"] is None and body["calls"]["cost_usd"] == 0.0
    assert body["by_persona"] == [] and body["by_model"] == []
    assert body["validators"]["catch_rate"] is None and body["missions"]["avg_duration_s"] is None


# ---------- process ----------


async def test_the_process_counts_come_from_the_event_log(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    _, [mission, other] = await project_with_missions(app, client, tmp_path)
    run, other_run = uuid.UUID(mission["run_id"]), uuid.UUID(other["run_id"])
    for _ in range(2):
        await event(
            app,
            run,
            EventType.PROVIDER_FALLBACK,
            {"from_provider": "a", "to_provider": "b", "reason": "429"},
        )
    await event(
        app,
        run,
        EventType.KEY_ROTATED,
        {"connection": "c", "from_key": "1", "to_key": "2", "reason": "rate limit"},
    )
    await event(
        app,
        run,
        EventType.ESCALATED,
        {
            "persona": "backend",
            "feature_id": "f",
            "attempt": 3,
            "connection": "c",
            "model": "m",
            "reason": "r",
        },
    )
    await event(
        app,
        run,
        EventType.GUARDRAIL_TRIGGERED,
        {"guardrail": "prompt_injection", "action": "warned", "reason": "x"},
    )
    await event(
        app,
        run,
        EventType.GUARDRAIL_TRIGGERED,
        {"guardrail": "prompt_injection", "action": "warned", "reason": "y"},
    )
    await event(
        app,
        run,
        EventType.GUARDRAIL_TRIGGERED,
        {"guardrail": "secret_scan", "action": "blocked", "reason": "z"},
    )
    await event(
        app,
        other_run,
        EventType.KEY_ROTATED,
        {"connection": "c", "from_key": "1", "to_key": "2", "reason": "x"},
    )

    body = await metrics(client, mission_id=mission["id"])

    process = body["process"]
    assert (process["fallbacks"], process["key_rotations"], process["escalations"]) == (2, 1, 1)
    assert process["guardrail_triggers"] == 3 and process["guardrails"] == {
        "prompt_injection": 2,
        "secret_scan": 1,
    }
    assert process["budget_warnings"] == 0
    assert (
        await metrics(
            client,
            project_id=(await client.get(f"/api/missions/{mission['id']}")).json()["project_id"],
        )
    )["process"]["key_rotations"] == 2


async def test_features_retries_and_first_try_rate(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    _, [mission, _] = await project_with_missions(app, client, tmp_path)
    async with app.state.sessionmaker.begin() as session:
        rows = list(
            await session.scalars(
                select(FeatureRow)
                .where(FeatureRow.mission_id == uuid.UUID(mission["id"]))
                .order_by(FeatureRow.position)
            )
        )
        rows[0].status, rows[0].attempts = "done", 1  # first try
        rows[1].status, rows[1].attempts = "done", 3  # needed retries

    body = await metrics(client, mission_id=mission["id"])

    assert body["features"]["by_status"] == {"done": 2}
    assert (body["features"]["attempts"], body["features"]["retried"]) == (4, 1)
    assert body["features"]["first_try_rate"] == 0.5


# ---------- validators ----------


async def test_validator_catch_rate_counts_found_then_fixed_and_admits_what_it_cannot_know(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    _, [mission, _] = await project_with_missions(app, client, tmp_path)
    mission_id = uuid.UUID(mission["id"])
    async with app.state.sessionmaker.begin() as session:
        m1, m2 = list(
            await session.scalars(
                select(Milestone)
                .where(Milestone.mission_id == mission_id)
                .order_by(Milestone.position)
            )
        )
        for milestone, validator, round_, verdict in [
            (m1, "code-reviewer", 1, "fail"),  # caught...
            (m1, "code-reviewer", 2, "pass"),  # ...then fixed
            (m1, "security", 1, "pass"),
            (m2, "code-reviewer", 1, "fail"),  # caught...
            (m2, "code-reviewer", 2, "fail"),  # ...and never fixed
            (m2, "qa", 1, "needs_user"),  # could not check
        ]:  # fmt: skip
            session.add(
                ValidatorReportRow(
                    mission_id=mission_id, milestone_id=milestone.id, validator=validator,
                    round=round_, verdict=verdict, data={"milestone_id": milestone.key},
                )
            )  # fmt: skip

    validators = (await metrics(client, mission_id=mission["id"]))["validators"]

    assert validators["milestones"] == 2 and validators["checks"] == 4
    assert (validators["caught"], validators["caught_and_fixed"], validators["unavailable"]) == (
        2,
        1,
        1,
    )
    assert validators["catch_rate"] == 0.5
    assert validators["false_positive_rate"] is None  # no ground truth in the record: not measured


async def test_edit_format_compliance_is_not_measured_because_that_layer_is_not_built(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    project, _ = await project_with_missions(app, client, tmp_path, count=1)

    assert (await metrics(client, project_id=project["id"]))["edit_format_compliance"] is None


# ---------- missions and variants ----------


async def test_missions_are_counted_by_status_and_variant_with_their_cost(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    await client.post(
        "/api/variants",
        json={
            "id": "terse",
            "name": "Terse",
            "personas": {
                "backend": {"instructions": "You are terse and write very little.", "skills": []}
            },
        },
    )
    root = tmp_path / "app"
    root.mkdir()
    project = (
        await client.post("/api/projects", json={"workspace_path": str(repo_with(root, None))})
    ).json()
    made = []
    for variant in (None, "terse", "terse"):
        extra = {"variant_id": variant} if variant else {}
        made.append(
            (
                await client.post(
                    "/api/missions",
                    json={"project_id": project["id"], "idea": "todo app", "plan": PLAN, **extra},
                )
            ).json()
        )
    await call(app, uuid.UUID(made[0]["run_id"]), persona="backend", cost="0.50")
    await call(app, uuid.UUID(made[1]["run_id"]), persona="backend", cost="0.20")
    await call(app, uuid.UUID(made[2]["run_id"]), persona="backend", cost="0.30")
    async with app.state.sessionmaker.begin() as session:
        await session.execute(
            text(
                "UPDATE missions SET status = 'completed', "
                "started_at = now() - interval '90 seconds', finished_at = now() WHERE id = :m"
            ),
            {"m": uuid.UUID(made[1]["id"])},
        )
        await session.execute(
            text("UPDATE missions SET status = 'failed' WHERE id = :m"),
            {"m": uuid.UUID(made[2]["id"])},
        )

    body = await metrics(client, project_id=project["id"])

    assert body["missions"]["count"] == 3
    assert body["missions"]["by_status"] == {"awaiting_approval": 1, "completed": 1, "failed": 1}
    assert 89 <= body["missions"]["avg_duration_s"] <= 92
    variants = {v["variant_id"]: v for v in body["by_variant"]}
    assert variants["terse"]["missions"] == 2 and variants["terse"]["completed"] == 1
    assert variants["terse"]["cost_usd"] == pytest.approx(0.50)
    assert variants[None]["missions"] == 1 and variants[None]["cost_usd"] == pytest.approx(0.50)
    assert [v["variant_id"] for v in body["by_variant"]] == ["terse", None]  # the default last


# ---------- errors ----------


async def test_a_project_or_mission_is_required_and_must_exist(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/metrics")).status_code == 422
    assert (
        await client.get("/api/metrics", params={"project_id": str(uuid.uuid4())})
    ).status_code == 404
    assert (
        await client.get("/api/metrics", params={"mission_id": str(uuid.uuid4())})
    ).status_code == 404


# ---------- against a real mission ----------


@needs_docker
async def test_a_real_missions_metrics_agree_with_its_own_cost_and_token_totals(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)
    await approve(client, mission)
    await finish(app)
    row, features, _ = await load(app, mission["id"])
    shown = (await client.get(f"/api/missions/{mission['id']}")).json()

    body = await metrics(client, mission_id=mission["id"])

    assert row.status == "completed"
    assert body["calls"]["count"] > 0 and body["calls"]["failed"] == 0
    assert body["calls"]["input_tokens"] == shown["tokens_in"]  # the same totals the mission shows
    assert body["calls"]["cost_usd"] == pytest.approx(shown["spent_usd"])
    assert body["missions"]["by_status"] == {"completed": 1}
    assert body["features"]["by_status"] == {"done": len(features)}
    assert {p["persona"] for p in body["by_persona"]} == {"backend", "frontend"}
    assert json.dumps(body)  # all plain data: it serialises
