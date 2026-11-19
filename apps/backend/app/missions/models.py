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
# "completed": every feature is done or skipped. Validators arrive in P5 and will add "passed".
MilestoneStatus = Literal["pending", "active", "completed", "failed"]
# PRD §8.1. Cancelled and failed can follow any other state.
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


class Handoff(AgentReport):
    feature_id: str
    persona_id: str
    model_used: str  # from the provider layer, not the agent
    commands: list[CommandResult] = Field(default_factory=list)  # from the sandbox log
    files_changed: list[str] = Field(default_factory=list)  # from git diff
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

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


class MilestonePlan(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    title: str = Field(min_length=3, max_length=120)
    validators: list[str] = Field(default_factory=list)
    features: list[Feature] = Field(min_length=1, max_length=20)


class MissionPlan(BaseModel):
    """A hand-written mission plan (PRD decision D24). Features run in the order given."""

    title: str = Field(min_length=3, max_length=120)
    milestones: list[MilestonePlan] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _check(self) -> "MissionPlan":
        from app.agents.persona import builtin_personas

        personas = builtin_personas()
        milestone_ids = [m.id for m in self.milestones]
        feature_ids = [f.id for m in self.milestones for f in m.features]
        for kind, ids in (("milestone", milestone_ids), ("feature", feature_ids)):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{kind} ids must be unique within a mission")
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
