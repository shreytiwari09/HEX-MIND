"""The MissionRunner: a deterministic loop over a mission's features (PRD §8.3, §8.4, §8.6,
§12.3; decision D25: a custom ADK `BaseAgent`, not Sequential/Loop agents).

Features run **one at a time**, each starting from the code the previous one committed. For
each feature the runner:

1. calls the feature's persona over A2A (the CrewAI `persona` crew) in the mission worktree;
2. fills in the facts the agent cannot be trusted with: changed files from git, the quick check
   from the sandbox, model, tokens and cost from `llm_calls`;
3. rejects the attempt if no files changed, or the check failed or ran zero tests;
4. on acceptance records a Handoff and makes a checkpoint commit named after the feature.

A rejected attempt is retried with the exact findings, up to `MAX_ATTEMPTS`. When attempts run
out the mission stops in "Needs you" with the evidence. Provider outages (the provider layer
has already retried and fallen back) do not count as attempts. Budget exhaustion also stops the
mission in "Needs you". The last attempt runs on the persona's escalation model when it has one
(PRD §10.5); a persona without one repeats its normal model. PM re-planning arrives with P5.

Pause and stop are honoured between steps: the step in flight finishes, then the runner exits.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import func, select

from app.a2a.client import CrewCallFailed, call_crew
from app.a2a.protocol import PersonaRequest
from app.agents.mcp_bridge import McpWorkspace
from app.db.models import (
    CheckResult,
    FeatureRow,
    HandoffRow,
    LLMCall,
    Milestone,
    Mission,
    Project,
    Run,
)
from app.events.log import EventType, append_event
from app.missions import service
from app.missions.models import AgentReport, CommandResult, Feature, Handoff
from app.orchestration.adk import run_adk
from app.orchestration.run import NO_CHANGES_FEEDBACK, RunStep, _innermost, set_status
from app.orchestration.services import Services
from app.sandbox.profile import ProfileError, load_profile
from app.sandbox.runner import CheckOutcome, accepted, check_feedback
from app.telemetry.hub import TelemetryHub
from app.workspace import git

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # the first try and two retries (PRD §8.6)
CHECK_NAME = "test"
OUTPUT_IN_HANDOFF = 1500
PROVIDER_FAILURE_MARKER = "ProviderCallFailed"  # raised by HexLLM once the router gave up


class MissionAborted(RuntimeError):
    """The mission cannot proceed for a reason the user can fix (shown in run_failed)."""


@dataclass
class Attempt:
    outcome: Literal["accepted", "rejected", "outage"]
    feedback: str | None = None
    detail: str = ""


class MissionRunner:
    def __init__(self, services: Services, mission_id: uuid.UUID) -> None:
        self.services = services
        self.mission_id = mission_id
        self.loop = asyncio.get_running_loop()
        self.run_id: uuid.UUID
        self.workspace: Path
        self.worktree: Path
        self.telemetry: TelemetryHub | None = None
        self.mcp: McpWorkspace | None = None
        self.check_command = CHECK_NAME

    # ---------- lifecycle ----------

    async def load(self) -> None:
        async with self.services.sessionmaker() as session:
            mission = await session.get(Mission, self.mission_id)
            if mission is None:
                raise MissionAborted("mission not found")
            run = await session.get(Run, mission.run_id)
            project = await session.get(Project, mission.project_id)
            assert run is not None and project is not None and run.worktree_path
        self.run_id = run.id
        self.workspace = Path(project.workspace_path)
        self.worktree = Path(run.worktree_path)
        if not self.worktree.is_dir():
            raise MissionAborted("the mission worktree no longer exists")
        self.telemetry = TelemetryHub(self.services, self.run_id, self.loop)

    async def close(self) -> None:
        if self.mcp is not None:
            await run_in_threadpool(self.mcp.close)

    async def run(self) -> None:
        settings = self.services.settings
        try:
            profile = await run_in_threadpool(
                load_profile, self.workspace, self.worktree, settings.sandbox_images
            )
        except ProfileError as exc:
            raise MissionAborted(str(exc)) from exc
        if CHECK_NAME in profile.checks:
            self.check_command = profile.checks[CHECK_NAME]
        self.mcp = McpWorkspace(
            root=self.worktree,
            workspace=self.workspace,
            allowed_images=settings.sandbox_images,
            check_timeout_s=settings.sandbox_timeout_s,
        )
        await run_in_threadpool(self.mcp.start)
        await set_status(self.services, self.run_id, "running")
        await self._back_to_last_checkpoint()

        for milestone_id in await self._milestone_ids():
            await self._set_milestone(milestone_id, "active")
            for key in await self._open_feature_keys(milestone_id):
                if await self._build_feature(key) != "done":
                    return await self._settle()
            await self._set_milestone(milestone_id, "completed")
        await self._complete()

    async def _back_to_last_checkpoint(self) -> None:
        """Start from the last committed state: work that was in flight when the mission was
        paused or interrupted is discarded, and its feature starts over."""
        head = await run_in_threadpool(git.head, self.worktree)
        await run_in_threadpool(git.reset_to, self.worktree, head)
        async with self.services.sessionmaker.begin() as session:
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            for feature in await session.scalars(
                select(FeatureRow).where(
                    FeatureRow.mission_id == self.mission_id, FeatureRow.status == "in_progress"
                )
            ):
                await service.set_feature(session, mission, feature, "pending")
            await session.flush()
            await service.sync_mission_folder(session, mission, self.worktree)

    # ---------- plan traversal ----------

    async def _milestone_ids(self) -> list[uuid.UUID]:
        async with self.services.sessionmaker() as session:
            return list(
                await session.scalars(
                    select(Milestone.id)
                    .where(Milestone.mission_id == self.mission_id)
                    .order_by(Milestone.position)
                )
            )

    async def _open_feature_keys(self, milestone_id: uuid.UUID) -> list[str]:
        async with self.services.sessionmaker() as session:
            return list(
                await session.scalars(
                    select(FeatureRow.key)
                    .where(
                        FeatureRow.milestone_id == milestone_id,
                        FeatureRow.status.in_(("pending", "in_progress")),
                    )
                    .order_by(FeatureRow.position)
                )
            )

    async def _set_milestone(self, milestone_id: uuid.UUID, status: str) -> None:
        async with self.services.sessionmaker.begin() as session:
            milestone = await session.get(Milestone, milestone_id)
            mission = await session.get(Mission, self.mission_id)
            assert milestone is not None and mission is not None
            await service.set_milestone(session, mission, milestone, status)
            await session.flush()
            await service.sync_mission_folder(session, mission, self.worktree)

    async def _running(self) -> bool:
        async with self.services.sessionmaker() as session:
            status = await session.scalar(
                select(Mission.status).where(Mission.id == self.mission_id)
            )
        return status == "running"

    # ---------- one feature ----------

    async def _build_feature(self, key: str) -> Literal["done", "stopped"]:
        feedback: str | None = None
        while True:
            if not await self._running():
                return "stopped"
            if await self._budget_reached():
                return "stopped"
            attempts = await self._attempts(key)
            if attempts >= MAX_ATTEMPTS:
                await self._need_feature_failed(key, feedback)
                return "stopped"
            attempt = await self._attempt(key, attempts + 1, feedback)
            if attempt.outcome == "accepted":
                return "done"
            if attempt.outcome == "outage":
                await self._need_provider_outage(key, attempt.detail)
                return "stopped"
            feedback = attempt.feedback

    async def _attempts(self, key: str) -> int:
        async with self.services.sessionmaker() as session:
            row = await self._feature(session, key)
            return row.attempts

    async def _feature(self, session, key: str) -> FeatureRow:  # type: ignore[no-untyped-def]
        row = await session.scalar(
            select(FeatureRow).where(
                FeatureRow.mission_id == self.mission_id, FeatureRow.key == key
            )
        )
        assert row is not None
        return row

    async def _attempt(self, key: str, number: int, feedback: str | None) -> Attempt:
        assert self.telemetry is not None and self.services.a2a_http is not None
        async with self.services.sessionmaker.begin() as session:
            row = await self._feature(session, key)
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            await service.set_feature(session, mission, row, "in_progress")
            feature = Feature.model_validate(
                {
                    "id": row.key,
                    "title": row.title,
                    "persona": row.persona_id,
                    **row.spec,
                }
            )
            earlier = [
                Handoff.model_validate(h.data)
                for h in await session.scalars(
                    select(HandoffRow)
                    .where(HandoffRow.mission_id == self.mission_id)
                    .order_by(HandoffRow.created_at)
                )
            ]
            started = await session.scalar(select(func.clock_timestamp()))
            await service.sync_mission_folder(session, mission, self.worktree)
        before = await run_in_threadpool(git.head, self.worktree)

        request = PersonaRequest(
            exchange_id=uuid.uuid4(),
            run_id=self.run_id,
            agent_id=f"{feature.persona}_{number:02d}",
            worktree=str(self.worktree),
            workspace=str(self.workspace),
            persona_id=feature.persona,
            feature=feature,
            earlier_handoffs=earlier,
            feedback=feedback,
            # Cascade principle (PRD §10.5): escalate only when earlier attempts failed.
            escalate=number >= MAX_ATTEMPTS,
        )
        try:
            text = await call_crew(
                "persona",
                hub=self.telemetry,
                http=self.services.a2a_http,
                settings=self.services.settings,
                prompt=f"Feature {feature.id}: {feature.title}",
                request=request,
                parent="mission_runner",
            )
        except CrewCallFailed as exc:
            message = str(exc)
            if PROVIDER_FAILURE_MARKER in message:
                await self._reset_feature(key)
                return Attempt("outage", detail=message[:500])
            return await self._rejected(
                key, f"The previous attempt failed: {message[:600]}", message[:500]
            )
        try:
            report = AgentReport.model_validate_json(text)
        except ValidationError as exc:
            return await self._rejected(
                key, f"Your report was not valid: {str(exc)[:400]}", "invalid report"
            )

        changes = await run_in_threadpool(git.diff, self.worktree, before)
        files_changed = [c.path for c in changes if not c.path.startswith(".hex/")]
        if not files_changed:
            return await self._rejected(key, NO_CHANGES_FEEDBACK, "no files were changed")
        outcome = await self._quick_check()
        if not accepted(outcome):
            return await self._rejected(key, check_feedback(outcome), "the quick check failed")

        model_used, tokens_in, tokens_out, cost = await self._usage(started)
        handoff = Handoff.assemble(
            report,
            feature=feature,
            model_used=model_used,
            commands=[
                CommandResult(
                    command=self.check_command,
                    exit_code=outcome.exit_code if outcome.exit_code is not None else -1,
                    duration_s=outcome.duration_ms / 1000,
                    summary=outcome.output_tail[-OUTPUT_IN_HANDOFF:],
                )
            ],
            files_changed=files_changed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=float(cost),
        )
        await self._checkpoint(key, handoff)
        return Attempt("accepted")

    async def _rejected(self, key: str, feedback: str, detail: str) -> Attempt:
        async with self.services.sessionmaker.begin() as session:
            row = await self._feature(session, key)
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            row.attempts += 1
            await service.set_feature(session, mission, row, "pending")
        return Attempt("rejected", feedback=feedback, detail=detail)

    async def _reset_feature(self, key: str) -> None:
        """An outage is not the agent's fault: no attempt is counted."""
        async with self.services.sessionmaker.begin() as session:
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            await service.set_feature(
                session, mission, await self._feature(session, key), "pending"
            )

    async def _checkpoint(self, key: str, handoff: Handoff) -> None:
        """Accept the feature: handoff, mission files, then a commit named after the feature."""
        async with self.services.sessionmaker.begin() as session:
            mission = await session.get(Mission, self.mission_id)
            row = await self._feature(session, key)
            assert mission is not None
            row.status, row.attempts = "done", row.attempts + 1
            await session.flush()
            await service.record_handoff(session, mission, row, handoff, self.worktree)
            await service.sync_mission_folder(session, mission, self.worktree)
            sha = await run_in_threadpool(git.commit_all, self.worktree, f"{row.key}: {row.title}")
            row.commit = sha
            await service.add_checkpoint(
                session, mission, commit=sha, label=f"{row.key}: {row.title}", feature=row
            )
            await service.set_feature(session, mission, row, "done")
            await session.flush()
            await service.sync_mission_folder(session, mission, self.worktree)

    # ---------- measured facts ----------

    async def _quick_check(self) -> CheckOutcome:
        assert self.mcp is not None
        async with self.services.sessionmaker.begin() as session:
            await append_event(
                session,
                self.run_id,
                EventType.CHECK_STARTED,
                agent_id="sandbox",
                payload={"name": CHECK_NAME},
            )
        ok, text = await run_in_threadpool(self.mcp.call_tool, "run_check", {"name": CHECK_NAME})
        if ok:
            outcome = CheckOutcome(**json.loads(text))
        else:
            outcome = CheckOutcome(CHECK_NAME, None, 0, "", error=text.removeprefix("ERROR: "))
        async with self.services.sessionmaker.begin() as session:
            session.add(
                CheckResult(
                    run_id=self.run_id,
                    name=CHECK_NAME,
                    exit_code=outcome.exit_code,
                    duration_ms=outcome.duration_ms,
                    output_tail=(outcome.error or "") + outcome.output_tail,
                )
            )
            await append_event(
                session,
                self.run_id,
                EventType.CHECK_COMPLETED,
                agent_id="sandbox",
                payload={
                    "name": CHECK_NAME,
                    "exit_code": outcome.exit_code,
                    "duration_ms": outcome.duration_ms,
                },
            )
        return outcome

    async def _usage(self, since: object) -> tuple[str, int, int, Decimal]:
        """Model, tokens and cost of the calls made since `since` (features build serially, so
        the window belongs to this feature)."""
        async with self.services.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(
                        LLMCall.provider,
                        LLMCall.model,
                        func.count(),
                        func.coalesce(func.sum(LLMCall.input_tokens), 0),
                        func.coalesce(func.sum(LLMCall.output_tokens), 0),
                        func.coalesce(func.sum(LLMCall.est_cost_usd), 0),
                    )
                    .where(
                        LLMCall.run_id == self.run_id,
                        LLMCall.created_at >= since,
                        LLMCall.error.is_(None),
                    )
                    .group_by(LLMCall.provider, LLMCall.model)
                    .order_by(func.count().desc())
                )
            ).all()
        models = ", ".join(f"{provider}:{model}" for provider, model, *_ in rows)
        return (
            models or "none recorded",
            sum(int(r[3]) for r in rows),
            sum(int(r[4]) for r in rows),
            sum((Decimal(r[5]) for r in rows), Decimal(0)),
        )

    async def _budget_reached(self) -> bool:
        async with self.services.sessionmaker.begin() as session:
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            if mission.budget_usd is None:
                return False
            spent = await service.spent_usd(session, self.run_id)
            if spent < mission.budget_usd:
                return False
            if await service.set_status(
                session, self.mission_id, "needs_user", only_from=("running",)
            ):
                await service.create_need(
                    session,
                    mission,
                    kind="budget_reached",
                    summary=f"The mission has spent {spent} USD of its {mission.budget_usd} USD "
                    "budget.",
                    evidence={"spent_usd": float(spent), "budget_usd": float(mission.budget_usd)},
                )
            return True

    # ---------- Needs you ----------

    async def _need_feature_failed(self, key: str, feedback: str | None) -> None:
        async with self.services.sessionmaker.begin() as session:
            row = await self._feature(session, key)
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            await service.set_feature(session, mission, row, "failed")
            if await service.set_status(
                session, self.mission_id, "needs_user", only_from=("running",)
            ):
                await service.create_need(
                    session,
                    mission,
                    kind="feature_failed",
                    feature=row,
                    summary=f"{row.persona_id} could not finish “{row.title}” after "
                    f"{row.attempts} attempts.",
                    evidence={"attempts": row.attempts, "last_findings": feedback or ""},
                )
            await service.sync_mission_folder(session, mission, self.worktree)

    async def _need_provider_outage(self, key: str, detail: str) -> None:
        async with self.services.sessionmaker.begin() as session:
            row = await self._feature(session, key)
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            if await service.set_status(
                session, self.mission_id, "needs_user", only_from=("running",)
            ):
                await service.create_need(
                    session,
                    mission,
                    kind="provider_unavailable",
                    feature=row,
                    summary="No model provider could answer. This did not count as an attempt.",
                    evidence={"error": detail},
                )

    # ---------- finishing ----------

    async def _complete(self) -> None:
        if await run_in_threadpool(git.is_dirty, self.worktree):
            sha = await run_in_threadpool(
                git.commit_all, self.worktree, "Mission complete: update mission files"
            )
            async with self.services.sessionmaker.begin() as session:
                mission = await session.get(Mission, self.mission_id)
                assert mission is not None
                await service.add_checkpoint(session, mission, commit=sha, label="Mission complete")
        async with self.services.sessionmaker.begin() as session:
            done = await service.set_status(
                session,
                self.mission_id,
                "completed",
                only_from=("running",),
                reason="every feature is done or skipped",
            )
        if done:
            await set_status(self.services, self.run_id, "completed", finished=True)
            async with self.services.sessionmaker.begin() as session:
                await append_event(
                    session,
                    self.run_id,
                    EventType.RUN_COMPLETED,
                    payload={"summary": "Every feature is done or skipped."},
                )
        await self._settle()

    async def _settle(self) -> None:
        await service.settle_cancelled(self.services, self.mission_id)

    async def fail(self, error: str) -> None:
        if self.telemetry is not None:
            await self.telemetry.abort_open(error=error)
        async with self.services.sessionmaker.begin() as session:
            moved = await service.set_status(
                session, self.mission_id, "failed", only_from=service.OPEN_STATES
            )
        if moved:
            await set_status(self.services, self.run_id, "failed", finished=True)
            async with self.services.sessionmaker.begin() as session:
                await append_event(
                    session, self.run_id, EventType.RUN_FAILED, payload={"error": error[:1000]}
                )


async def execute_mission(services: Services, mission_id: uuid.UUID) -> None:
    """Run (or resume) a mission to its next stopping point. Unexpected failures mark the
    mission failed with a run_failed event."""
    runner = MissionRunner(services, mission_id)
    try:
        await runner.load()
        assert runner.telemetry is not None
        await run_adk(
            runner.telemetry.instrument(
                RunStep("mission_runner", "Serial features, checks and checkpoints.", runner.run)
            ),
            message=f"Run mission {mission_id}",
        )
    except Exception as exc:
        exc = _innermost(exc)
        if not isinstance(exc, MissionAborted):
            logger.exception("mission %s failed", mission_id, exc_info=exc)
        if runner.telemetry is not None:
            await runner.fail(str(exc))
        else:
            async with services.sessionmaker.begin() as session:
                await service.set_status(
                    session, mission_id, "failed", only_from=service.OPEN_STATES
                )
    finally:
        await runner.close()
