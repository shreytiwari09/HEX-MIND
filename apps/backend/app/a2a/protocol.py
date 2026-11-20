"""What the ADK orchestrator and the CrewAI crew service agree on (plan §1, criterion 6).

Each A2A request carries the prompt as its message text and a `hexmind` object in the
request-level metadata: which run, task and worktree the crew works on, and an `exchange_id`
that both sides put on their `a2a_message` events so the UI can join them. W3C trace context
(`traceparent`) travels next to it, so the crew's spans join the orchestrator's trace.
"""

import uuid
from typing import Any, Literal

from opentelemetry import propagate, trace
from pydantic import BaseModel, Field

from app.agents.build import REPORT_EXPECTED
from app.agents.persona import Persona
from app.missions.models import Coordination, Feature, Handoff
from app.plugins.config import PluginSpec

# `planner` and `coder` are the fixed crews of the run workflow. `persona` serves any persona
# (PRD §12.3): the request names the persona and the feature, and the crew service builds the agent.
CrewRole = Literal["planner", "coder", "persona"]
ROLES: tuple[CrewRole, ...] = ("planner", "coder", "persona")
METADATA_KEY = "hexmind"


def card_path(role: CrewRole) -> str:
    return f"/{role}/.well-known/agent-card.json"


def agent_name(role: CrewRole) -> str:
    """The ADK RemoteA2aAgent name, also the A2A agent card name."""
    return f"{role}_crew"


class CrewRequest(BaseModel):
    exchange_id: uuid.UUID
    run_id: uuid.UUID
    task_id: uuid.UUID | None = None
    # The CrewAI agent id inside the crew (planner, coder_01, ...).
    agent_id: str
    worktree: str
    workspace: str
    complexity: str | None = None
    expected_output: str


class PersonaRequest(CrewRequest):
    """A request to the `persona` crew: which persona does which feature, and what came before.
    The crew service builds the prompt itself from these fields."""

    persona_id: str
    # The persona as the orchestrator has it now (the user may have edited it or made it): the
    # crew service has no database. Without it the built-in persona is used.
    persona: Persona | None = None
    # The plugins that are ready for this persona now (enabled, and approved if risky), with
    # their configuration: only these are ever started.
    plugins: list[PluginSpec] = Field(default_factory=list)
    # The prompt variant the mission runs under (already applied to `persona`); recorded on every
    # model call of this job.
    variant_id: str | None = None
    # How the mission shares state (PRD §9.8). With "messaging" the worker has no mission board:
    # this request is everything it learns about the mission, so the feature's validation
    # criteria travel in it too.
    coordination: Coordination = "blackboard"
    criteria: list[str] = Field(default_factory=list)
    feature: Feature
    earlier_handoffs: list[Handoff] = Field(default_factory=list)
    # The exact findings of a rejected attempt, for the retry (PRD §8.6).
    feedback: str | None = None
    # The last attempt runs on the persona's escalation model, if it has one (PRD §8.6, §10.5).
    escalate: bool = False
    # "acceptance": QA writes acceptance tests (PRD §8.5), confined to tests/acceptance/.
    mode: Literal["feature", "acceptance"] = "feature"
    expected_output: str = REPORT_EXPECTED


def trace_carrier() -> dict[str, str]:
    """The current span's W3C trace context, for request metadata."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def request_metadata(request: CrewRequest) -> dict[str, Any]:
    return {METADATA_KEY: request.model_dump(mode="json"), **trace_carrier()}
