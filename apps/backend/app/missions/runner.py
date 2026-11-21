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
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import func, select

from app.a2a.client import CrewCallFailed, call_crew, call_crew_with_resend
from app.a2a.protocol import PersonaRequest
from app.agents import variants
from app.agents.mcp_bridge import McpWorkspace
from app.agents.persona import Persona, UnknownPersona, get_persona
from app.agents.variants import Variant
from app.db.models import (
    AgentEvent,
    CheckResult,
    Connection,
    FeatureRow,
    HandoffRow,
    LLMCall,
    Milestone,
    Mission,
    Project,
    Run,
    ValidatorReportRow,
)
from app.events.log import EventType, append_event
from app.missions import chat_updates, folder, service
from app.missions.models import (
    TESTABLE,
    AgentReport,
    CommandResult,
    Feature,
    Finding,
    Handoff,
    PluginUse,
    SkillUse,
    ValidatorReport,
)
from app.missions.validators import VALIDATORS, FeatureSnap, ValidationContext
from app.orchestration.adk import run_adk
from app.orchestration.run import NO_CHANGES_FEEDBACK, RunStep, _innermost, set_status
from app.orchestration.services import Services
from app.plugins import registry as plugin_registry
from app.plugins.config import PluginSpec, config_hash
from app.providers.assignments import has_escalation, route_for
from app.providers.privacy import privacy_for
from app.sandbox.contract import ContractError
from app.sandbox.profile import ProfileError, load_profile
from app.sandbox.runner import CheckOutcome, accepted, check_feedback
from app.skills.registry import SkillRegistry
from app.telemetry.hub import TelemetryHub
from app.workspace import git

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # the first try and two retries (PRD §8.6)
CHECK_NAME = "test"
# Run after every feature, in this order, when the project defines them (PRD §8.4 step 7).
QUICK_CHECKS = ("typecheck", CHECK_NAME)
# Files whose contents decide whether dependencies must be installed again.
DEPENDENCY_FILES = (
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
)
# Validators find problems, the builder fixes them, validators look again: at most this often.
MAX_VALIDATION_ROUNDS = 2
OUTPUT_IN_HANDOFF = 1500
PROVIDER_FAILURE_MARKER = "ProviderCallFailed"  # raised by HexLLM once the router gave up


def dependency_fingerprint(root: Path) -> str:
    """A hash of the files that say what to install; changes when dependencies change."""
    digest = hashlib.sha256()
    for name in DEPENDENCY_FILES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


_OWNER = re.compile(r"^\[([a-z0-9-]+)\] ")  # a plugin tool's call is logged as "[plugin-id] ..."


def _check_ok(name: str, outcome: CheckOutcome) -> bool:
    """Tests must pass *and* have run some (exit 0 with no tests proves nothing); any other
    check just has to pass."""
    return accepted(outcome) if name == CHECK_NAME else outcome.passed


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
        # The dependency files the last successful `install` was run for (reinstall on change).
        self._installed: str | None = None
        # The prompt variant this mission runs under, if any (agents/variants.py).
        self.variant: Variant | None = None
        # How this mission shares state (PRD §9.8): 'blackboard' or 'messaging'.
        self.coordination = "blackboard"

    # ---------- lifecycle ----------

    async def load(self) -> None:
        async with self.services.sessionmaker() as session:
            mission = await session.get(Mission, self.mission_id)
            if mission is None:
                raise MissionAborted("mission not found")
            run = await session.get(Run, mission.run_id)
            project = await session.get(Project, mission.project_id)
            assert run is not None and project is not None and run.worktree_path
            try:
                self.variant = await variants.get(session, mission.variant_id)
            except variants.VariantError as exc:
                raise MissionAborted(str(exc)) from None
        self.coordination = mission.coordination
        self.run_id = run.id
        self.workspace = Path(project.workspace_path)
        self.worktree = Path(run.worktree_path)
        if not self.worktree.is_dir():
            raise MissionAborted("the mission worktree no longer exists")
        self.telemetry = TelemetryHub(self.services, self.run_id, self.loop)

    def persona(self, persona_id: str) -> Persona:
        """A persona as it is for this mission: the user's current version, with the mission's
        prompt variant applied."""
        return variants.apply(get_persona(persona_id), self.variant)

    @property
    def variant_id(self) -> str | None:
        return self.variant.id if self.variant else None

    async def _announce_variant(self) -> None:
        """Record once, when the mission starts, which roles the variant changes."""
        if self.variant is None:
            return
        async with self.services.sessionmaker.begin() as session:
            seen = await session.scalar(
                select(AgentEvent.id)
                .where(
                    AgentEvent.run_id == self.run_id,
                    AgentEvent.type == EventType.PROMPT_VARIANT_SELECTED,
                )
                .limit(1)
            )
            if seen is not None:
                return  # a resumed mission: already said
            for role in self.variant.personas:
                await append_event(
                    session,
                    self.run_id,
                    EventType.PROMPT_VARIANT_SELECTED,
                    payload={"role": role, "variant": self.variant.id},
                )

    async def _call_worker(self, **kwargs: Any) -> str:
        """One request to a persona crew. In messaging mode a request that times out is sent
        again with the same exchange id (PRD §9.8: timeout + resend with an idempotency key)."""
        if self.coordination == "messaging":
            return await call_crew_with_resend(
                resends=self.services.settings.messaging_resends, **kwargs
            )
        return await call_crew(**kwargs)

    def _criteria_for(self, mission: Mission, key: str) -> list[str]:
        """The validation criteria of one feature, sent in the request in messaging mode (a
        blackboard worker reads them from the mission folder instead)."""
        if self.coordination != "messaging":
            return []
        return [
            f"{c['id']}: {c['text']}   [{c['how']}]"
            for c in mission.validation_contract or []
            if c.get("feature") == key
        ]

    async def close(self) -> None:
        if self.mcp is not None:
            await run_in_threadpool(self.mcp.close)

    async def run(self) -> None:
        settings = self.services.settings
        try:
            profile = await run_in_threadpool(
                load_profile, self.workspace, self.worktree, settings.sandbox_images
            )
        except (ProfileError, ContractError) as exc:
            raise MissionAborted(str(exc)) from exc
        del profile  # checks are read again for every attempt: DevOps may change the contract
        self.mcp = McpWorkspace(
            root=self.worktree,
            workspace=self.workspace,
            allowed_images=settings.sandbox_images,
            check_timeout_s=settings.sandbox_timeout_s,
        )
        await run_in_threadpool(self.mcp.start)
        await set_status(self.services, self.run_id, "running")
        await self._announce_variant()
        await self._back_to_last_checkpoint()

        for milestone_id in await self._milestone_ids():
            status = await self._milestone_status(milestone_id)
            if status in ("passed", "accepted"):
                continue
            if status not in ("completed", "failed"):  # features still to build
                await self._set_milestone(milestone_id, "active")
                await self._write_acceptance_tests(milestone_id)
                for key in await self._open_feature_keys(milestone_id):
                    if await self._build_feature(key) != "done":
                        return await self._settle()
                await self._set_milestone(milestone_id, "completed")
            if await self._validate(milestone_id) != "ok":
                return await self._settle()
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

    async def _milestone_status(self, milestone_id: uuid.UUID) -> str:
        async with self.services.sessionmaker() as session:
            milestone = await session.get(Milestone, milestone_id)
            assert milestone is not None
            return milestone.status

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

    async def _build_feature(
        self, key: str, feedback: str | None = None
    ) -> Literal["done", "stopped"]:
        """Build one feature, retrying with findings. `feedback` starts a validator's findings."""
        while True:
            if not await self._running():
                return "stopped"
            if await self._budget_stops(key):
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
            criteria = self._criteria_for(mission, key)
        before = await run_in_threadpool(git.head, self.worktree)
        try:
            persona = self.persona(feature.persona)  # the user's edits, and this mission's variant
        except UnknownPersona:
            raise MissionAborted(f"the persona '{feature.persona}' no longer exists") from None

        if number >= MAX_ATTEMPTS:
            await self._note_escalation(feature, number)
        # Only plugins that are ready now (enabled; approved for their exact configuration if
        # risky) are sent; the crew service starts nothing else.
        async with self.services.sessionmaker() as session:
            ready = await plugin_registry.ready_for(session, persona.plugins)
        privacy = await privacy_for(self.services.sessionmaker, self.run_id)
        if privacy.mode == "local":  # nothing leaves the machine: no plugin with network access
            ready = [r for r in ready if plugin_registry.config_of(r).network == "none"]
        plugins = [
            PluginSpec(
                id=row.id,
                name=row.name,
                config=plugin_registry.config_of(row),
                config_hash=config_hash(plugin_registry.config_of(row)),
            )
            for row in ready
        ]
        request = PersonaRequest(
            exchange_id=uuid.uuid4(),
            run_id=self.run_id,
            agent_id=f"{feature.persona}_{number:02d}",
            worktree=str(self.worktree),
            workspace=str(self.workspace),
            persona_id=feature.persona,
            persona=persona,
            plugins=plugins,
            variant_id=self.variant_id,
            coordination=self.coordination,
            criteria=criteria,
            feature=feature,
            earlier_handoffs=earlier,
            feedback=feedback,
            # Cascade principle (PRD §10.5): escalate only when earlier attempts failed.
            escalate=number >= MAX_ATTEMPTS,
        )
        try:
            text = await self._call_worker(
                role="persona",
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
        results, problem = await self._quick_checks()
        if problem is not None:
            return await self._rejected(key, problem, "the project defines no usable checks")
        failed = next((o for name, _, o in results if not _check_ok(name, o)), None)
        if failed is not None:
            return await self._rejected(key, check_feedback(failed), "the quick check failed")

        model_used, tokens_in, tokens_out, cost = await self._usage(started)
        handoff = Handoff.assemble(
            report,
            feature=feature,
            model_used=model_used,
            commands=[
                CommandResult(
                    command=command,
                    exit_code=outcome.exit_code if outcome.exit_code is not None else -1,
                    duration_s=outcome.duration_ms / 1000,
                    summary=outcome.output_tail[-OUTPUT_IN_HANDOFF:],
                )
                for _, command, outcome in results
            ],
            files_changed=files_changed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=float(cost),
            skills=await self._skills_used(persona, feature, request.agent_id, started),
            persona_version=persona.version,
            variant_id=self.variant_id,
            plugins=await self._plugins_used(plugins, request.agent_id, started),
        )
        await self._checkpoint(key, handoff)
        return Attempt("accepted")

    async def _skills_used(
        self, persona: Persona, feature: Feature, agent_id: str, since: object
    ) -> list[SkillUse]:
        """The skills the persona was offered for this feature (name and version) and which of
        them it actually loaded, read from the tool-call log. `persona` is the one the job ran as
        (the user's edits and the mission's variant applied)."""
        registry = SkillRegistry(self.services.settings.data_dir / "skills")
        offered, _ = await run_in_threadpool(
            registry.resolve, [*persona.skills, *feature.extra_skills]
        )
        async with self.services.sessionmaker() as session:
            payloads = list(
                await session.scalars(
                    select(AgentEvent.payload).where(
                        AgentEvent.run_id == self.run_id,
                        AgentEvent.type == EventType.TOOL_CALLED,
                        AgentEvent.agent_id == agent_id,
                        AgentEvent.ts >= since,
                    )
                )
            )
        loaded = {
            str(p.get("summary", "")).partition(":")[0]
            for p in payloads
            if p.get("tool") == "load_skill" and p.get("ok")
        }
        return [SkillUse(name=s.name, version=s.version, loaded=s.name in loaded) for s in offered]

    async def _plugins_used(
        self, plugins: list[PluginSpec], agent_id: str, since: object
    ) -> list[PluginUse]:
        """The plugins that were ready on this job and whether any of their tools was called,
        read from the tool-call log (a plugin tool is named `<plugin>__<tool>`)."""
        if not plugins:
            return []
        async with self.services.sessionmaker() as session:
            payloads = list(
                await session.scalars(
                    select(AgentEvent.payload).where(
                        AgentEvent.run_id == self.run_id,
                        AgentEvent.type == EventType.TOOL_CALLED,
                        AgentEvent.agent_id == agent_id,
                        AgentEvent.ts >= since,
                    )
                )
            )
        called = {
            match.group(1)
            for p in payloads
            if str(p.get("tool", "")).startswith("plugin_")
            and (match := _OWNER.match(str(p.get("summary", ""))))
        }
        return [
            PluginUse(id=p.id, config_hash=p.config_hash, called=p.id in called) for p in plugins
        ]

    async def _note_escalation(self, feature: Feature, attempt: int) -> None:
        """Record in the delegation log that this attempt runs on the escalation model."""
        async with self.services.sessionmaker.begin() as session:
            if not await has_escalation(session, feature.persona):
                return  # no escalation model: the attempt repeats the normal route
            route = await route_for(session, feature.persona, escalate=True)
            assert route is not None
            target = route.targets[0]
            connection = await session.get(Connection, target.connection_id)
            await append_event(
                session,
                self.run_id,
                EventType.ESCALATED,
                agent_id=f"{feature.persona}_{attempt:02d}",
                payload={
                    "persona": feature.persona,
                    "feature_id": feature.id,
                    "attempt": attempt,
                    "connection": connection.name if connection else "?",
                    "model": target.model,
                    "reason": f"attempts 1 to {attempt - 1} were rejected",
                },
            )

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

    async def _quick_checks(self) -> tuple[list[tuple[str, str, CheckOutcome]], str | None]:
        """Run the project's quick checks (typecheck, then tests) in the sandbox, stopping at the
        first failure. The commands come from the run contract *as it is now*, since DevOps may
        have written it during this mission. Returns (name, command, outcome) per check run, and
        a message for the agent when the project has nothing usable to run."""
        settings = self.services.settings
        try:
            profile = await run_in_threadpool(
                load_profile, self.workspace, self.worktree, settings.sandbox_images
            )
        except (ProfileError, ContractError) as exc:
            return [], f"The project's checks could not be read: {exc}"
        if CHECK_NAME not in profile.checks:
            return [], (
                f"The project defines no `{CHECK_NAME}` check, so nothing can show the work "
                f"passes. Add one to {profile.source}."
            )
        results: list[tuple[str, str, CheckOutcome]] = []
        if "install" in profile.checks:
            fingerprint = await run_in_threadpool(dependency_fingerprint, self.worktree)
            if fingerprint != self._installed:
                outcome = await self._run_check("install")
                results.append(("install", profile.checks["install"], outcome))
                if not outcome.passed:
                    return results, None
                self._installed = fingerprint
        for name in QUICK_CHECKS:
            if name not in profile.checks:
                continue
            outcome = await self._run_check(name)
            results.append((name, profile.checks[name], outcome))
            if not _check_ok(name, outcome):
                break
        return results, None

    async def _run_check(self, name: str) -> CheckOutcome:
        assert self.mcp is not None
        async with self.services.sessionmaker.begin() as session:
            await append_event(
                session,
                self.run_id,
                EventType.CHECK_STARTED,
                agent_id="sandbox",
                payload={"name": name},
            )
        ok, text = await run_in_threadpool(self.mcp.call_tool, "run_check", {"name": name})
        if ok:
            outcome = CheckOutcome(**json.loads(text))
        else:
            outcome = CheckOutcome(name, None, 0, "", error=text.removeprefix("ERROR: "))
        async with self.services.sessionmaker.begin() as session:
            session.add(
                CheckResult(
                    run_id=self.run_id,
                    name=name,
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
                    "name": name,
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

    async def _budget_stops(self, key: str) -> bool:
        """Warn at 80% of a budget and stop in Needs you at 100% (PRD §8.6), for the mission as a
        whole and for the persona about to work. Spending is the real total from llm_calls."""
        async with self.services.sessionmaker.begin() as session:
            mission = await session.get(Mission, self.mission_id)
            feature = await self._feature(session, key)
            assert mission is not None
            spent = await service.spent_usd(session, self.run_id)
            if mission.budget_usd is not None:
                if spent >= mission.budget_usd:
                    await self._stop_for_budget(
                        session,
                        mission,
                        None,
                        kind="budget_reached",
                        summary=f"The mission has spent {spent} USD of its "
                        f"{mission.budget_usd} USD budget.",
                        evidence={
                            "spent_usd": float(spent),
                            "budget_usd": float(mission.budget_usd),
                        },
                    )
                    return True
                await service.warn_if_near(session, mission, "mission", spent, mission.budget_usd)

            cap = await service.persona_budget(session, feature.persona_id)
            if cap is not None:
                persona_spent = await service.persona_spent(
                    session, self.run_id, feature.persona_id
                )
                if persona_spent >= cap:
                    await self._stop_for_budget(
                        session,
                        mission,
                        feature,
                        kind="persona_budget_reached",
                        summary=f"{feature.persona_id} has spent {persona_spent} USD of its "
                        f"{cap} USD budget for this mission.",
                        evidence={
                            "persona_id": feature.persona_id,
                            "spent_usd": float(persona_spent),
                            "budget_usd": float(cap),
                        },
                    )
                    return True
                await service.warn_if_near(session, mission, feature.persona_id, persona_spent, cap)
        return False

    async def _stop_for_budget(
        self,
        session,  # type: ignore[no-untyped-def]
        mission: Mission,
        feature: FeatureRow | None,
        *,
        kind: str,
        summary: str,
        evidence: dict,  # type: ignore[type-arg]
    ) -> None:
        if await service.set_status(
            session, self.mission_id, "needs_user", only_from=("running",), reason="budget reached"
        ):
            await service.create_need(
                session, mission, kind=kind, summary=summary, feature=feature, evidence=evidence
            )

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

    # ---------- QA acceptance tests (PRD §8.5) ----------

    async def _write_acceptance_tests(self, milestone_id: uuid.UUID) -> None:
        """Before a milestone is built, QA writes acceptance tests from the validation contract,
        independently of the builders. They go in `tests/acceptance/`, which only QA can write,
        and are committed so builders start from them."""
        assert self.telemetry is not None and self.services.a2a_http is not None
        async with self.services.sessionmaker() as session:
            milestone = await session.get(Milestone, milestone_id)
            mission = await session.get(Mission, self.mission_id)
            assert milestone is not None and mission is not None
            if "qa" not in milestone.validators or milestone.acceptance_ready:
                return
            keys = set(
                await session.scalars(
                    select(FeatureRow.key).where(FeatureRow.milestone_id == milestone_id)
                )
            )
            criteria = [
                c
                for c in mission.validation_contract or []
                if c.get("feature") in keys and c.get("how") in TESTABLE
            ]
            key, title = milestone.key, milestone.title
        if not criteria:
            return  # nothing testable to write tests for
        before = await run_in_threadpool(git.head, self.worktree)
        feature = Feature(
            id=f"acceptance-{key}",
            title=f"Acceptance tests: {title}",
            persona="qa",
            description="Write acceptance tests for this milestone from its validation contract.",
            expected_behavior=[f"{c['id']}: {c['text']}  [{c['how']}]" for c in criteria],
        )
        for attempt in range(1, 3):
            request = PersonaRequest(
                exchange_id=uuid.uuid4(),
                run_id=self.run_id,
                agent_id=f"qa_acceptance_{attempt:02d}",
                worktree=str(self.worktree),
                workspace=str(self.workspace),
                persona_id="qa",
                persona=self.persona("qa"),
                variant_id=self.variant_id,
                coordination=self.coordination,
                feature=feature,
                mode="acceptance",
            )
            try:
                await self._call_worker(
                    role="persona",
                    hub=self.telemetry,
                    http=self.services.a2a_http,
                    settings=self.services.settings,
                    prompt=f"Acceptance tests for {key}",
                    request=request,
                    parent="mission_runner",
                )
            except CrewCallFailed as exc:
                logger.warning("QA could not write acceptance tests for %s: %s", key, exc)
                continue
            changes = [
                c
                for c in await run_in_threadpool(git.diff, self.worktree, before)
                if not c.path.startswith(".hex/")
            ]
            if any(not c.path.startswith("tests/acceptance/") for c in changes):
                await run_in_threadpool(git.reset_to, self.worktree, before)  # not QA's to change
                continue
            if not changes:
                continue
            async with self.services.sessionmaker.begin() as session:
                mission = await session.get(Mission, self.mission_id)
                milestone = await session.get(Milestone, milestone_id)
                assert mission is not None and milestone is not None
                sha = await run_in_threadpool(
                    git.commit_all, self.worktree, f"Acceptance tests: {key}"
                )
                await service.add_checkpoint(
                    session, mission, commit=sha, label=f"Acceptance tests: {title}"
                )
                milestone.acceptance_ready = True
            return
        # No acceptance tests were written; the QA validator will say so rather than pass.

    # ---------- validators (PRD §8.5) ----------

    async def _validate(self, milestone_id: uuid.UUID) -> Literal["ok", "stopped"]:
        """Run the milestone's validators; findings go back to the builder; after
        MAX_VALIDATION_ROUNDS the user decides."""
        async with self.services.sessionmaker() as session:
            milestone = await session.get(Milestone, milestone_id)
            assert milestone is not None
            key, required = milestone.key, list(milestone.validators)
        runnable = [name for name in required if name in VALIDATORS]
        if not runnable:
            return "ok"  # none required (or none built yet): the milestone stays "completed"

        for round_no in range(1, MAX_VALIDATION_ROUNDS + 1):
            if not await self._running():
                return "stopped"
            reports = await self._run_validators(milestone_id, key, runnable, round_no)
            failed = [r for r in reports if r.verdict == "fail"]
            unavailable = [r for r in reports if r.verdict == "needs_user"]
            if not failed and not unavailable:
                await self._set_milestone(milestone_id, "passed")
                return "ok"
            if not failed:
                await self._need_validation(
                    milestone_id,
                    key,
                    "validator_unavailable",
                    "A validator could not check this milestone: "
                    + "; ".join(r.validator for r in unavailable)
                    + ". Nothing was marked as passing.",
                    unavailable,
                )
                return "stopped"
            if round_no == MAX_VALIDATION_ROUNDS:
                break
            if await self._send_back(milestone_id, failed) != "done":
                return "stopped"
        await self._set_milestone(milestone_id, "failed")
        await self._need_validation(
            milestone_id,
            key,
            "milestone_failed",
            f"The milestone “{key}” still fails validation after {MAX_VALIDATION_ROUNDS} rounds.",
            failed,
        )
        return "stopped"

    async def _run_validators(
        self, milestone_id: uuid.UUID, key: str, names: list[str], round_no: int
    ) -> list[ValidatorReport]:
        assert self.telemetry is not None
        snaps = await self._feature_snaps(milestone_id)
        async with self.services.sessionmaker.begin() as session:
            for name in names:
                await append_event(
                    session,
                    self.run_id,
                    EventType.VALIDATOR_STARTED,
                    agent_id=name,
                    payload={"validator": name, "milestone_id": key, "round": round_no},
                )

        async def load_checks() -> dict[str, str]:
            profile = await run_in_threadpool(
                load_profile, self.workspace, self.worktree, self.services.settings.sandbox_images
            )
            return profile.checks

        async with self.services.sessionmaker() as session:
            milestone_row = await session.get(Milestone, milestone_id)
            mission_row = await session.get(Mission, self.mission_id)
            assert milestone_row is not None and mission_row is not None
            ready = milestone_row.acceptance_ready
            keys = set(
                await session.scalars(
                    select(FeatureRow.key).where(FeatureRow.milestone_id == milestone_id)
                )
            )
            criteria = [
                c for c in mission_row.validation_contract or [] if c.get("feature") in keys
            ]
        vc = ValidationContext(
            criteria=criteria,
            acceptance_ready=ready,
            services=self.services,
            mission_id=self.mission_id,
            run_id=self.run_id,
            worktree=self.worktree,
            telemetry=self.telemetry,
            run_check=self._run_check,
            load_checks=load_checks,
            variant=self.variant,
        )
        outcomes = await asyncio.gather(
            *(VALIDATORS[name](vc, key, snaps) for name in names), return_exceptions=True
        )
        reports: list[ValidatorReport] = []
        for name, outcome in zip(names, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.error("validator %s crashed", name, exc_info=outcome)
                outcome = ValidatorReport(
                    validator=name,
                    milestone_id=key,
                    verdict="needs_user",
                    findings=[
                        Finding(
                            severity="info",
                            message=f"The {name} validator failed to run "
                            f"({type(outcome).__name__}): nothing was checked.",
                        )
                    ],
                )
            reports.append(outcome)
        await self._store_reports(milestone_id, reports, round_no)
        return reports

    async def _feature_snaps(self, milestone_id: uuid.UUID) -> list[FeatureSnap]:
        async with self.services.sessionmaker() as session:
            rows = list(
                await session.scalars(
                    select(FeatureRow)
                    .where(FeatureRow.milestone_id == milestone_id)
                    .order_by(FeatureRow.position)
                )
            )
        return [
            FeatureSnap(
                key=r.key,
                title=r.title,
                persona=r.persona_id,
                expected_behavior=list(r.spec.get("expected_behavior", [])),
                commit=r.commit if r.status == "done" else None,
            )
            for r in rows
        ]

    async def _store_reports(
        self, milestone_id: uuid.UUID, reports: list[ValidatorReport], round_no: int
    ) -> None:
        async with self.services.sessionmaker.begin() as session:
            for report in reports:
                session.add(
                    ValidatorReportRow(
                        mission_id=self.mission_id,
                        milestone_id=milestone_id,
                        validator=report.validator,
                        round=round_no,
                        verdict=report.verdict,
                        data=report.model_dump(mode="json"),
                    )
                )
                await run_in_threadpool(
                    folder.write_validator_report, self.worktree, report, round_no
                )
                await append_event(
                    session,
                    self.run_id,
                    EventType.VALIDATOR_REPORTED,
                    agent_id=report.validator,
                    payload={
                        "validator": report.validator,
                        "milestone_id": report.milestone_id,
                        "round": round_no,
                        "verdict": report.verdict,
                        "findings": len(report.findings),
                        "blocking": len(report.blocking),
                    },
                )

    async def _send_back(
        self, milestone_id: uuid.UUID, failed: list[ValidatorReport]
    ) -> Literal["done", "stopped"]:
        """Give each feature its validators' blocking findings, exactly as reported (PRD §8.6:
        the same persona gets the findings). Findings about the milestone as a whole go to its
        last feature."""
        snaps = await self._feature_snaps(milestone_id)
        built = [s.key for s in snaps if s.commit]
        if not built:
            return "stopped"
        by_feature: dict[str, list[str]] = {}
        for report in failed:
            for finding in report.blocking:
                target = finding.feature_id if finding.feature_id in built else built[-1]
                by_feature.setdefault(target, []).append(
                    f"[{report.validator}, {finding.severity}] "
                    + (f"{finding.file}:{finding.line}: " if finding.file else "")
                    + finding.message
                    + (f"\n{finding.evidence}" if finding.evidence else "")
                )
        for key in built:
            if key not in by_feature:
                continue
            async with self.services.sessionmaker.begin() as session:
                mission = await session.get(Mission, self.mission_id)
                row = await self._feature(session, key)
                assert mission is not None
                row.attempts = 0
                await service.set_feature(session, mission, row, "pending")
            feedback = "A validator found problems with this feature:\n" + "\n".join(
                by_feature[key]
            )
            if await self._build_feature(key, feedback) != "done":
                return "stopped"
        return "done"

    async def _need_validation(
        self,
        milestone_id: uuid.UUID,
        key: str,
        kind: str,
        summary: str,
        reports: list[ValidatorReport],
    ) -> None:
        async with self.services.sessionmaker.begin() as session:
            mission = await session.get(Mission, self.mission_id)
            assert mission is not None
            if await service.set_status(
                session, self.mission_id, "needs_user", only_from=("running",), reason="validation"
            ):
                await service.create_need(
                    session,
                    mission,
                    kind=kind,
                    summary=summary,
                    evidence={
                        "milestone_id": key,
                        "findings": [
                            f"[{r.validator}, {f.severity}] {f.message}"
                            for r in reports
                            for f in r.findings
                            if f.severity != "info"
                        ][:20],
                    },
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
            if self.services.apps is not None and self.services.settings.app_autorun_after_mission:
                self.services.background.spawn(
                    chat_updates.run_after_mission(self.services, self.mission_id, self.worktree),
                    name=f"app-after-{self.mission_id}",
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
