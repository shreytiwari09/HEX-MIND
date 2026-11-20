"""PostgreSQL schema (plan §8). PostgreSQL is the authoritative store for all lifecycle state.

Status-like columns are plain strings validated in application code, so adding a state
does not require an enum migration.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB, list[str]: JSONB}


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


# clock_timestamp(), not now(): now() is the transaction start time, so rows inserted in one
# transaction would share a timestamp and lose their order.
def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


# ---------- Projects and conversations ----------


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    workspace_path: Mapped[str] = mapped_column(Text, unique=True)
    git_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which providers may see this project's prompts (providers/privacy.py): any | trusted | local.
    privacy_mode: Mapped[str] = mapped_column(String(8), default="any", server_default="any")
    # For "trusted": the connection ids the user trusts with this project.
    trusted_connections: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    # Number of oldest messages already folded into `summary`.
    summary_message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = _fk("conversations.id")
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    mode: Mapped[str | None] = mapped_column(String(8))  # ask | edit | auto
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
    created_at: Mapped[datetime] = _created_at()


# ---------- Runs, routing and tasks ----------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    conversation_id: Mapped[uuid.UUID | None] = _fk("conversations.id", nullable=True)
    parent_run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    triggering_message_id: Mapped[uuid.UUID | None] = _fk(
        "messages.id", nullable=True, ondelete="SET NULL"
    )
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    complexity: Mapped[str | None] = mapped_column(String(8))
    strategy: Mapped[str | None] = mapped_column(String(32))
    base_commit: Mapped[str | None] = mapped_column(String(64))
    pre_apply_commit: Mapped[str | None] = mapped_column(String(64))
    worktree_path: Mapped[str | None] = mapped_column(Text)
    # Per-run event counter; incremented in the same transaction as each event insert.
    last_event_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouterDecision(Base):
    __tablename__ = "router_decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    message_id: Mapped[uuid.UUID] = _fk("messages.id")
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    decision: Mapped[dict[str, Any]] = mapped_column()
    valid: Mapped[bool] = mapped_column(Boolean)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at()


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_run_status", "run_id", "status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[str]] = mapped_column(default=list)
    target_files: Mapped[list[str]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    complexity: Mapped[str | None] = mapped_column(String(8))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    role: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


# ---------- Changes, checks and reviews ----------


class FileChange(Base):
    __tablename__ = "file_changes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    path: Mapped[str] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(16))  # added | modified | deleted
    base_hash: Mapped[str | None] = mapped_column(String(64))
    diff: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    created_at: Mapped[datetime] = _created_at()


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(64))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    output_tail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created_at()


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    verdict: Mapped[str] = mapped_column(String(32))
    findings: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = _created_at()


# ---------- Telemetry ----------


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_agent_events_run_seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(48))
    agent_id: Mapped[str | None] = mapped_column(String(64))
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ts: Mapped[datetime] = _created_at()
    # The audit chain (events/chain.py): hash = sha256(prev_hash + canonical(record)). Null for
    # events written before the chain existed.
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str | None] = mapped_column(String(64))


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    purpose: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))  # a connection's name, or a built-in provider
    model: Mapped[str] = mapped_column(String(128))
    # Which pool key served the call (routed calls only; never the secret itself).
    connection_id: Mapped[uuid.UUID | None] = _fk(
        "connections.id", nullable=True, ondelete="SET NULL"
    )
    key_label: Mapped[str | None] = mapped_column(String(64))
    # Which persona the call was made for (persona crews only), to budget and report per persona.
    persona_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # The prompt variant the call ran under (PRD §11.5, E5), for comparing configurations.
    variant_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # sha256 of exactly what was sent and what came back (the audit trail, PRD §14.2): proves
    # what a call was without keeping the text.
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    response_sha256: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    est_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    fallback_from: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    # Answered from the response cache (PRD §15.2): the figures are those measured when the call
    # was really made, and no provider was called this time.
    replayed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = _created_at()


class ResponseCacheRow(Base):
    """A stored model answer, keyed by provider, model and exact request (providers/cache.py)."""

    __tablename__ = "response_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    completion: Mapped[dict[str, Any]] = mapped_column()
    est_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


# ---------- Evaluation ----------


class EvalTask(Base):
    __tablename__ = "eval_tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    acceptance_tests: Mapped[list[Any]] = mapped_column(default=list)
    expected_complexity: Mapped[str] = mapped_column(String(8))
    # 'feature' (one function in the to-do core) or 'mission' (a whole app, PRD §15.1).
    kind: Mapped[str] = mapped_column(String(8), default="feature", server_default="feature")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    eval_task_id: Mapped[uuid.UUID] = _fk("eval_tasks.id")
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    provider: Mapped[str] = mapped_column(String(32))
    completed: Mapped[bool] = mapped_column(Boolean)
    tests_passed: Mapped[int | None] = mapped_column(Integer)
    tests_total: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column()
    judge_rationale: Mapped[str | None] = mapped_column(Text)
    human_score: Mapped[float | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    retries: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created_at()
    # Experiment trials (PRD §15.2): which experiment and condition, which repeat, and the
    # settings it ran under, so a result can be reproduced and compared.
    experiment: Mapped[str | None] = mapped_column(String(8), index=True)
    condition: Mapped[str | None] = mapped_column(String(64))
    repeat: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    benchmark_version: Mapped[str | None] = mapped_column(String(16))
    mission_id: Mapped[uuid.UUID | None] = _fk("missions.id", nullable=True, ondelete="SET NULL")
    # How the trial ended (the mission's status, or `error` when it could not be run) and
    # whether the hidden tests all passed (measured by the grader, not claimed by an agent).
    status: Mapped[str | None] = mapped_column(String(16))
    passed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    needs_you: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    escalations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class RoutingLabel(Base):
    __tablename__ = "routing_labels"

    id: Mapped[uuid.UUID] = _uuid_pk()
    prompt: Mapped[str] = mapped_column(Text)
    label_complexity: Mapped[str] = mapped_column(String(8))
    label_type: Mapped[str] = mapped_column(String(16))
    labeler: Mapped[str] = mapped_column(String(64))
    split: Mapped[str] = mapped_column(String(8))  # train | test


# ---------- Missions (PRD §12.5) ----------
# A mission owns one `runs` row, so its events, llm_calls and telemetry reuse the per-run event
# log. The mission folder in the worktree is a rendering of this state (PRD §9.1).


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), unique=True
    )
    title: Mapped[str] = mapped_column(String(255))
    idea: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval", index=True)
    branch: Mapped[str] = mapped_column(String(128))  # hex/mission-<id>
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What Apply wrote into the user's project (for revert); see missions/apply.py.
    apply_record: Mapped[dict[str, Any] | None] = mapped_column()
    # The approved validation contract: [{id, text, how, feature}] (PRD §9.7).
    validation_contract: Mapped[list[Any]] = mapped_column(default=list)
    # The prompt variant this mission runs under (prompt_variants.id), if any.
    variant_id: Mapped[str | None] = mapped_column(String(32))
    # How the team shares state (PRD §9.8): 'blackboard' (the mission board and folder, readable
    # through tools) or 'messaging' (workers get only what the orchestrator sends).
    coordination: Mapped[str] = mapped_column(
        String(16), default="blackboard", server_default="blackboard"
    )


class PluginRow(Base):
    """A plugin (an MCP server) the user added; see plugins/config.py for what the fields mean
    and how permissions and approval follow from them."""

    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column()  # a PluginConfig
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # The configuration hash the user approved, with when and which labels they saw.
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_labels: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class TraceSpan(Base):
    """A finished OpenTelemetry span, kept so traces render offline (telemetry/span_store.py).
    Attributes are sanitised before they are stored: no prompts, responses or secrets."""

    __tablename__ = "trace_spans"

    trace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    start_ns: Mapped[int] = mapped_column(BigInteger)
    end_ns: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(8), default="unset")
    status_message: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Set on the spans the hub touches; the rest of a trace is found through its trace id.
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)


class PromptVariantRow(Base):
    """A named set of changes to personas' instructions and skills, for comparing configurations
    (PRD §11.5, E5). A mission can run under one; every model call it makes records its id."""

    __tablename__ = "prompt_variants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    # {persona_id: {"instructions": str | None, "skills": [names] | None}}
    overrides: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class PersonaRow(Base):
    """A persona the user edited (a built-in one) or created. It overlays the built-in YAML
    persona with the same id; deleting the row resets a built-in persona to its default."""

    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    instructions: Mapped[str] = mapped_column(Text)
    skills: Mapped[list[Any]] = mapped_column(default=list)
    plugins: Mapped[list[Any]] = mapped_column(default=list)
    version: Mapped[int] = mapped_column(Integer)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)  # edits a built-in persona
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class PersonaVersion(Base):
    """Every version a persona has had, so an old mission's behaviour can be explained."""

    __tablename__ = "persona_versions"
    __table_args__ = (UniqueConstraint("persona_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    persona_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column()  # name, kind, instructions, skills, plugins
    created_at: Mapped[datetime] = _created_at()


class ScopingSession(Base):
    """The PM scoping chat for a new mission (PRD F2): the conversation, then the plan it
    produced, which the user may edit before it becomes a mission. Its run collects the PM's
    model calls and later becomes the mission's run, so the trail starts at the idea."""

    __tablename__ = "scoping_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    idea: Mapped[str] = mapped_column(Text)
    # asking: the PM is asking questions. planned: a valid plan is ready for review.
    # started: it became a mission. abandoned: the user dropped it.
    status: Mapped[str] = mapped_column(String(16), default="asking")
    # [{role: "user" | "pm", content, questions?, at}]
    messages: Mapped[list[Any]] = mapped_column(default=list)
    plan: Mapped[dict[str, Any] | None] = mapped_column()  # a valid MissionPlan
    prd: Mapped[str | None] = mapped_column(Text)
    # Why the last PM turn produced no usable answer (provider down, invalid plan), if it did not.
    error: Mapped[str | None] = mapped_column(Text)
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    mission_id: Mapped[uuid.UUID | None] = _fk("missions.id", nullable=True, ondelete="SET NULL")
    variant_id: Mapped[str | None] = mapped_column(String(32))  # the prompt variant it runs under
    coordination: Mapped[str] = mapped_column(
        String(16), default="blackboard", server_default="blackboard"
    )
    # Advanced research (PRD D62): researchers looked things up before the PM planned. The notes
    # are what they found (questions, findings with the sources they really read), or None.
    research: Mapped[bool] = mapped_column(default=False, server_default="false")
    research_notes: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("mission_id", "key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    mission_id: Mapped[uuid.UUID] = _fk("missions.id")
    key: Mapped[str] = mapped_column(String(64))  # the plan's id, e.g. "m2-backend"
    title: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    validators: Mapped[list[str]] = mapped_column(default=list)
    # QA has written this milestone's acceptance tests (before its features are built).
    acceptance_ready: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class FeatureRow(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("mission_id", "key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    mission_id: Mapped[uuid.UUID] = _fk("missions.id")
    milestone_id: Mapped[uuid.UUID] = _fk("milestones.id")
    key: Mapped[str] = mapped_column(String(64))  # the plan's feature id
    title: Mapped[str] = mapped_column(String(255))
    persona_id: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)  # execution order within the mission
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    commit: Mapped[str | None] = mapped_column(String(64))
    # description, preconditions, expected_behavior, contract_refs, extra_skills, target_files
    spec: Mapped[dict[str, Any]] = mapped_column(default=dict)


class HandoffRow(Base):
    __tablename__ = "handoffs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mission_id: Mapped[uuid.UUID] = _fk("missions.id")
    feature_id: Mapped[uuid.UUID] = _fk("features.id")
    persona_id: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column()  # the Handoff, as validated JSON
    created_at: Mapped[datetime] = _created_at()


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("mission_id", "commit"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    mission_id: Mapped[uuid.UUID] = _fk("missions.id")
    feature_id: Mapped[uuid.UUID | None] = _fk("features.id", nullable=True, ondelete="SET NULL")
    commit: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()


class Need(Base):
    """Something the mission cannot continue without: a "Needs you" item (PRD §8.6)."""

    __tablename__ = "needs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mission_id: Mapped[uuid.UUID] = _fk("missions.id")
    feature_id: Mapped[uuid.UUID | None] = _fk("features.id", nullable=True, ondelete="SET NULL")
    kind: Mapped[str] = mapped_column(String(32))  # e.g. feature_failed, budget_reached
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    options: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | answered
    answer: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = _created_at()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Model connections (PRD §10.2, §12.5) ----------
# Secrets are never stored here: a key row holds only a reference into the OS keychain.


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(64), unique=True)
    provider_type: Mapped[str] = mapped_column(String(32))  # see providers/presets.py
    base_url: Mapped[str] = mapped_column(Text)
    # Extra request headers that are not secrets (for example OpenRouter's app attribution).
    extra_headers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # The last connection test, and the models it found reachable.
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_error: Mapped[str | None] = mapped_column(Text)
    models: Mapped[list[str]] = mapped_column(default=list)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ConnectionKey(Base):
    """One key in a connection's pool. `key_ref` names the secret in the key store."""

    __tablename__ = "connection_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    connection_id: Mapped[uuid.UUID] = _fk("connections.id")
    label: Mapped[str] = mapped_column(String(64))
    key_ref: Mapped[str] = mapped_column(String(128), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = _created_at()


class ModelAssignment(Base):
    """Which models a persona uses (PRD §10.4): a primary, a fallback chain, and an escalation
    model, each a (connection, model) pair. `set_by` says whether the user chose it or Auto did."""

    __tablename__ = "model_assignments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    persona_id: Mapped[str] = mapped_column(String(32), unique=True)
    primary_connection_id: Mapped[uuid.UUID] = _fk("connections.id")
    primary_model: Mapped[str] = mapped_column(String(128))
    # [{"connection_id": "...", "model": "..."}, ...], tried in order after the primary.
    fallbacks: Mapped[list[Any]] = mapped_column(default=list)
    escalate: Mapped[dict[str, Any] | None] = mapped_column()
    set_by: Mapped[str] = mapped_column(String(8), default="user")  # user | auto
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _updated_at()


class PersonaBudget(Base):
    """The most a persona may spend in one mission (PRD §11.1). Independent of which model the
    persona uses; a persona without a row has no cap of its own."""

    __tablename__ = "persona_budgets"

    persona_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    updated_at: Mapped[datetime] = _updated_at()


class ValidatorReportRow(Base):
    """A validator's report for a milestone, one per validator per round (PRD §9.5)."""

    __tablename__ = "validator_reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mission_id: Mapped[uuid.UUID] = _fk("missions.id")
    milestone_id: Mapped[uuid.UUID] = _fk("milestones.id")
    validator: Mapped[str] = mapped_column(String(32))
    round: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict[str, Any]] = mapped_column()  # the ValidatorReport, as JSON
    created_at: Mapped[datetime] = _created_at()
