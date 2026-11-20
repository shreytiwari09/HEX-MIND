"""Experiments (PRD §15): list them, run a sweep of trials, read the stored results."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.agents import variants
from app.api.deps import ServicesDep, SessionDep
from app.evaluation import experiments as exp
from app.evaluation import missions, results, safety

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _sweeps(request: Request) -> dict[str, exp.Sweep]:
    if not hasattr(request.app.state, "sweeps"):
        request.app.state.sweeps = {}
    return request.app.state.sweeps  # type: ignore[no-any-return]


class SweepRequest(BaseModel):
    apps: list[str] | None = None  # default: every mission benchmark app
    repeats: int = Field(default=1, ge=1, le=10)
    budget_usd: Decimal = Field(default=exp.MAX_BUDGET_USD, gt=0, le=100)  # per trial
    variants: list[str] = Field(default_factory=list, max_length=8)  # E5: compared to baseline


async def _catalog(
    session: SessionDep, chosen: list[str] | None = None
) -> dict[str, exp.Experiment]:
    known = [row.id for row in await variants.all_rows(session)]
    return exp.experiments(chosen if chosen is not None else known)


@router.get("")
async def list_experiments(session: SessionDep) -> dict[str, Any]:
    catalog = await _catalog(session)
    return {
        "benchmark_version": missions.BENCHMARK_VERSION,
        "apps": [
            {"id": a.id, "idea": a.idea, "features": a.feature_ids()} for a in missions.load_apps()
        ],
        "experiments": [
            {
                "id": e.id,
                "title": e.title,
                "question": e.question,
                "varies": e.varies,
                "conditions": [{"id": c.id, "label": c.label} for c in e.conditions],
                "blocked": e.blocked,
                "note": e.note,
            }
            for e in catalog.values()
        ],
    }


@router.post("/{experiment_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_experiment(
    experiment_id: str,
    body: SweepRequest,
    request: Request,
    session: SessionDep,
    services: ServicesDep,
) -> dict[str, Any]:
    """Start a sweep. Trials that already have a stored result are skipped, so running it again
    continues where an earlier sweep stopped. One sweep runs at a time."""
    catalog = await _catalog(session, body.variants)
    experiment = catalog.get(experiment_id.upper())
    if experiment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such experiment")
    if experiment.blocked:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{experiment.id}: {experiment.blocked}")
    for variant_id in body.variants:
        try:
            await variants.get(session, variant_id)
        except variants.VariantError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
    sweeps = _sweeps(request)
    if any(s.state == "running" for s in sweeps.values()):
        raise HTTPException(status.HTTP_409_CONFLICT, "a sweep is already running")
    try:
        sweep = await exp.start_sweep(
            services,
            experiment,
            app_ids=body.apps or [a.id for a in missions.load_apps()],
            repeats=body.repeats,
            budget_usd=body.budget_usd,
            sweeps=sweeps,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return sweep.as_dict()


@router.get("/sweeps")
async def list_sweeps(request: Request) -> list[dict[str, Any]]:
    return [s.as_dict() for s in _sweeps(request).values()]


@router.post("/sweeps/{sweep_id}/stop")
async def stop_sweep(sweep_id: str, request: Request) -> dict[str, Any]:
    """Stop after cancelling the mission in flight; its trial is not stored."""
    sweep = _sweeps(request).get(sweep_id)
    if sweep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such sweep")
    if sweep.task is not None and sweep.state == "running":
        sweep.task.cancel()
        await asyncio.gather(sweep.task, return_exceptions=True)
    return sweep.as_dict()


@router.get("/safety")
async def get_safety() -> dict[str, Any]:
    """Safety negatives: each attack is tried against the real defense. Runs a short sandbox
    check, so it takes a few seconds."""
    found = await run_in_threadpool(safety.run_safety)
    return {"summary": safety.summary(found), "cases": [vars(r) for r in found]}


@router.get("/cache")
async def get_cache(services: ServicesDep) -> dict[str, Any]:
    """The response cache (PRD §15.2): its mode (set by HEXMIND_RESPONSE_CACHE) and entries."""
    cache = services.providers.cache
    if cache is None:
        return {"mode": "off", "entries": 0}
    return {"mode": cache.mode, **await cache.stats()}


@router.get("/results")
async def get_results(session: SessionDep) -> dict[str, Any]:
    catalog = await _catalog(session)
    collected = [await results.collect(session, e) for e in catalog]
    return {
        "experiments": [
            {
                **{k: v for k, v in c.items() if k != "conditions"},
                "title": catalog[c["experiment"]].title,
                "blocked": catalog[c["experiment"]].blocked,
                "conditions": [vars(s) for s in c["conditions"]],
            }
            for c in collected
        ]
    }


@router.get("/report")
async def get_report(session: SessionDep) -> dict[str, str]:
    """The dated markdown report of every experiment, generated from the stored trials."""
    catalog = await _catalog(session)
    collected = [await results.collect(session, e) for e in catalog]
    today = datetime.now(UTC).date()
    return {"date": today.isoformat(), "markdown": results.render(collected, catalog, today)}
