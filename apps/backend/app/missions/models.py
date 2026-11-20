"""Mission data shared by the orchestrator and the crew service (PRD §9.3, §9.4).

A `Feature` is one unit of work for one persona. A worker finishes with an `AgentReport`: only
what the agent can know and say (PRD: "agent-reported"). The orchestrator turns it into a
`Handoff` by adding the facts it measures itself: commands from the sandbox log, changed files
from git, and model and token usage from the provider layer. Agent claims are never trusted for
those.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

FeatureStatus = Literal["pending", "in_progress", "done", "failed", "skipped"]
# completed: every feature is done or skipped (validators, if any, have not passed it yet).
# passed: every required validator passed it. failed: a validator found problems the team could
# not fix. accepted: the user chose to go on despite that.
MilestoneStatus = Literal["pending", "active", "completed", "passed", "failed", "accepted"]
# PRD §8.1. Cancelled and failed can follow any other state.
# How a mission's agents share state (PRD §9.8).
Coordination = Literal["blackboard", "messaging"]

MissionStatus = Literal[
    "draft",
    "scoping",
    "awaiting_approval",
    "running",
    "paused",
    "needs_user",
    "completed",
    "applied",
    "kept",
    "discarded",
    "cancelled",
    "failed",
]


class Feature(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    title: str = Field(min_length=3, max_length=120)
    persona: str
    status: FeatureStatus = "pending"
    description: str = ""
    preconditions: list[str] = Field(default_factory=list)
    expected_behavior: list[str] = Field(min_length=1, max_length=12)
    contract_refs: list[str] = Field(default_factory=list)
    extra_skills: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list, max_length=12)
    attempts: int = 0
    commit: str | None = None


class CommandResult(BaseModel):
    command: str
    exit_code: int
    duration_s: float
    summary: str  # trimmed output


class AgentReport(BaseModel):
    """What the worker reports about its own work. The crew service validates this shape."""

    implemented: list[str] = Field(default_factory=list)
    left_undone: list[str] = Field(default_factory=list)
    issues_found: list[str] = Field(default_factory=list)
    procedures_followed: bool
    notes_for_next: list[str] = Field(default_factory=list)


class SkillUse(BaseModel):
    """A skill the agent was offered for a feature, and whether it loaded it (measured from the
    tool-call log, not from the agent's report)."""

    name: str
    version: str  # name@<first 12 hex of the skill's hash>
    loaded: bool = False


class PluginUse(BaseModel):
    """A plugin that was ready for the persona on this job, the exact configuration it ran with
    (hash), and whether the agent called any of its tools (measured from the tool-call log)."""

    id: str
    config_hash: str
    called: bool = False


class Handoff(AgentReport):
    feature_id: str
    persona_id: str
    model_used: str  # from the provider layer, not the agent
    commands: list[CommandResult] = Field(default_factory=list)  # from the sandbox log
    files_changed: list[str] = Field(default_factory=list)  # from git diff
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    skills: list[SkillUse] = Field(default_factory=list)
    persona_version: int = 1  # the version of the persona that did the work
    plugins: list[PluginUse] = Field(default_factory=list)
    variant_id: str | None = None  # the prompt variant the mission ran under

    @classmethod
    def assemble(
        cls,
        report: AgentReport,
        *,
        feature: Feature,
        model_used: str,
        commands: list[CommandResult],
        files_changed: list[str],
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        skills: list[SkillUse] | None = None,
        persona_version: int = 1,
        plugins: list[PluginUse] | None = None,
        variant_id: str | None = None,
    ) -> "Handoff":
        """Combine the agent's report with measured facts. The agent's own claims about files
        or commands are not part of `AgentReport`, so they cannot leak into the measured fields."""
        return cls(
            **report.model_dump(),
            feature_id=feature.id,
            persona_id=feature.persona,
            model_used=model_used,
            commands=commands,
            files_changed=files_changed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            skills=skills or [],
            persona_version=persona_version,
            plugins=plugins or [],
            variant_id=variant_id,
        )


@dataclass
class MissionContext:
    """What a worker is given besides its feature: where it works and what came before."""

    worktree: Path
    workspace: Path
    earlier_handoffs: list[Handoff] = field(default_factory=list)

    @property
    def mission_dir(self) -> Path:
        return self.worktree / ".hex" / "mission"


How = Literal["unit test", "api test", "browser", "typecheck", "security review"]
# What QA's acceptance tests can check. The rest is covered by other validators or by browser
# testing (not available in this build).
TESTABLE: tuple[str, ...] = ("unit test", "api test")


class Criterion(BaseModel):
    """One checkable statement in the validation contract (PRD §9.7)."""

    id: str = Field(pattern=r"^VC-\d+(\.\d+)*$")
    text: str = Field(min_length=3, max_length=300)
    how: How  # how it is checked
    feature: str | None = None  # the feature it belongs to


class MilestonePlan(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    title: str = Field(min_length=3, max_length=120)
    validators: list[str] = Field(default_factory=list)
    features: list[Feature] = Field(min_length=1, max_length=20)


class MissionPlan(BaseModel):
    """A hand-written mission plan (PRD decision D24). Features run in the order given."""

    title: str = Field(min_length=3, max_length=120)
    milestones: list[MilestonePlan] = Field(min_length=1, max_length=8)
    validation_contract: list[Criterion] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> "MissionPlan":
        from app.agents.persona import all_personas

        personas = all_personas()
        milestone_ids = [m.id for m in self.milestones]
        feature_ids = [f.id for m in self.milestones for f in m.features]
        criterion_ids = [c.id for c in self.validation_contract]
        for kind, ids in (
            ("milestone", milestone_ids),
            ("feature", feature_ids),
            ("criterion", criterion_ids),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{kind} ids must be unique within a mission")
        for criterion in self.validation_contract:
            if criterion.feature is not None and criterion.feature not in feature_ids:
                raise ValueError(f"criterion {criterion.id}: no feature {criterion.feature!r}")
        for milestone in self.milestones:
            for name in milestone.validators:
                if name not in personas or personas[name].kind != "validator":
                    raise ValueError(f"milestone {milestone.id}: {name!r} is not a validator")
            for feature in milestone.features:
                persona = personas.get(feature.persona)
                if persona is None or persona.kind != "worker":
                    raise ValueError(
                        f"feature {feature.id}: {feature.persona!r} is not a worker persona"
                    )
                if feature.status != "pending" or feature.attempts or feature.commit:
                    raise ValueError(f"feature {feature.id}: a new plan starts every feature fresh")
        return self


Severity = Literal["info", "minor", "major", "critical"]
Verdict = Literal["pass", "fail", "needs_user"]


class Finding(BaseModel):
    feature_id: str | None = None
    file: str | None = None
    line: int | None = None
    severity: Severity = "minor"
    message: str
    contract_ref: str | None = None  # e.g. "VC-2.3"
    evidence: str | None = None  # e.g. test output


class ValidatorReport(BaseModel):
    """What one validator found at the end of a milestone (PRD §9.5). `commands` come from the
    sandbox, not from the validator's say-so."""

    validator: str  # persona id
    milestone_id: str
    verdict: Verdict
    findings: list[Finding] = Field(default_factory=list)
    commands: list[CommandResult] = Field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("major", "critical")]
