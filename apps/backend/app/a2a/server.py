"""The CrewAI crew service: the Planner and Coder crews served as A2A agents (a2a-sdk 0.3).

Each crew is its own A2A agent with an Agent Card, mounted at `/planner` and `/coder`. A request
runs a single-agent crew exactly as the in-process version did (HexLLM through ProviderRouter,
MCP workspace tools on the run's worktree, TelemetryHub callbacks), and reports through the A2A
task lifecycle: submitted -> working -> completed (artifact) | failed.

The service writes to the same database as the backend, so its model calls, tool calls and
callbacks land in the run's event log. It accepts only bearer-authenticated requests and only
worktrees under the app's data directory.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Literal

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TaskState, TextPart
from a2a.utils import new_agent_text_message, new_task
from crewai.tools import BaseTool
from fastapi.concurrency import run_in_threadpool
from opentelemetry import propagate, trace
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

from app import __version__
from app.a2a.protocol import (
    METADATA_KEY,
    ROLES,
    CrewRequest,
    CrewRole,
    PersonaRequest,
    agent_name,
)
from app.agents import roles
from app.agents.build import build_agent, feature_prompt, tool_names_for
from app.agents.llm import HexLLM
from app.agents.mcp_bridge import McpWorkspace
from app.agents.persona import Persona, UnknownPersona, get_persona
from app.agents.tools import CODER, READ_ONLY, make_tools, tool_summary
from app.context.preload import preload_files
from app.context.repo_map import build_repo_map
from app.events.log import EventType
from app.guardrails.injection import MARK, signals_of
from app.missions.models import AgentReport, MissionContext
from app.orchestration.services import Services
from app.plugins.runtime import PluginHost
from app.providers.assignments import route_for
from app.providers.router import CallContext
from app.sandbox.contract import CONTRACT_PATH, DOCKERFILE_PATH
from app.skills.registry import Skill, SkillRegistry
from app.telemetry.hub import TelemetryHub
from app.workspace.paths import ACCEPTANCE_DIR

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("hexmind.a2a")

REMEMBERED_EXCHANGES = 64

SKILLS: dict[CrewRole, AgentSkill] = {
    "planner": AgentSkill(
        id="plan",
        name="Plan a code change",
        description="Break a developer request into small Blackboard tasks with acceptance "
        "criteria and target files (JSON). Reads the worktree with read-only MCP tools.",
        tags=["planning", "crewai"],
    ),
    "coder": AgentSkill(
        id="code",
        name="Implement a task",
        description="Edit files in the run's isolated worktree with MCP tools until the task's "
        "acceptance criteria and tests pass; returns a short summary.",
        tags=["coding", "crewai"],
    ),
    "persona": AgentSkill(
        id="persona-feature",
        name="Work on a feature as a persona",
        description="Build a fresh agent from any built-in persona and run one feature in the "
        "mission worktree; returns the agent's report (JSON) for the orchestrator to turn into "
        "a handoff. Only worker personas can change files.",
        tags=["personas", "crewai"],
    ),
}
PARENTS: dict[CrewRole, str] = {role: agent_name(role) for role in ROLES}


def agent_card(role: CrewRole, base_url: str) -> AgentCard:
    return AgentCard(
        name=agent_name(role),
        description=f"CrewAI {role.title()} crew served over A2A by H.E.X Mind.",
        url=f"{base_url.rstrip('/')}/{role}/",
        version=__version__,
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[SKILLS[role]],
    )


class CrewExecutor(AgentExecutor):
    """Runs one crew per A2A request."""

    def __init__(self, services: Services, role: CrewRole) -> None:
        self.services = services
        self.role = role
        # Work by exchange id: a request sent again (after a timeout) joins the work already
        # done or in flight instead of doing it twice. Remembers the most recent exchanges only.
        self._work: dict[str, asyncio.Future[str]] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        assert context.message is not None
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        metadata: dict[str, Any] = dict(context.metadata or {})
        request_model = PersonaRequest if self.role == "persona" else CrewRequest
        request = request_model.model_validate(metadata.get(METADATA_KEY) or {})
        hub = TelemetryHub(self.services, request.run_id, asyncio.get_running_loop())
        parent_ctx = propagate.extract(metadata)
        started = time.monotonic()
        with tracer.start_as_current_span(
            f"a2a.server {agent_name(self.role)}", context=parent_ctx
        ) as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            span.set_attributes(
                {
                    "hexmind.run_id": str(request.run_id),
                    "a2a.task_id": task.id,
                    "agent.framework": "crewai",
                }
            )

            async def note(direction: str, state: str, summary: str | None = None) -> None:
                await hub.record(
                    EventType.A2A_MESSAGE,
                    task_id=request.task_id,
                    agent_id=agent_name(self.role),
                    direction=direction,
                    side="server",
                    agent=agent_name(self.role),
                    peer="orchestrator",
                    exchange_id=str(request.exchange_id),
                    a2a_task_id=task.id,
                    context_id=task.context_id,
                    task_state=state,
                    trace_id=trace_id,
                    duration_ms=int((time.monotonic() - started) * 1000)
                    if state in ("completed", "failed")
                    else None,
                    summary=summary[:300] if summary else None,
                )

            await note("received", "submitted", context.get_user_input()[:200])
            await updater.update_status(TaskState.working)
            await note("sent", "working")
            try:
                result = await self._once(request, context.get_user_input(), hub)
            except Exception as exc:
                logger.exception("crew %s failed for run %s", self.role, request.run_id)
                await updater.failed(
                    new_agent_text_message(f"{type(exc).__name__}: {exc}", task.context_id, task.id)
                )
                await note("sent", "failed", f"{type(exc).__name__}: {exc}")
                return
            await updater.add_artifact([Part(root=TextPart(text=result))], name="result")
            await updater.complete()
            await note("sent", "completed", result)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("crew runs cannot be cancelled mid-task")

    async def _once(self, request: CrewRequest, prompt: str, hub: TelemetryHub) -> str:
        key = str(request.exchange_id)
        work = self._work.get(key)
        if work is None:
            work = asyncio.ensure_future(self._run_crew(request, prompt, hub))
            self._work[key] = work
            while len(self._work) > REMEMBERED_EXCHANGES:
                del self._work[next(iter(self._work))]
        # Shielded: the first caller giving up (its connection timed out) must not stop the work.
        return await asyncio.shield(work)

    async def _route(self, persona: Any, escalate: bool = False) -> Any:
        """The persona's assigned models, or None to use the global provider order."""
        if persona is None:
            return None
        async with self.services.sessionmaker() as session:
            return await route_for(session, persona.id, escalate=escalate)

    def _note_injection(
        self, hub: TelemetryHub, request: CrewRequest, tool: str, text: str
    ) -> None:
        """A tool result the injection guardrail labelled becomes a `guardrail_triggered` event."""
        signals = _marked_source(text)
        if signals is None:
            return
        hub.record_threadsafe(
            EventType.GUARDRAIL_TRIGGERED,
            task_id=request.task_id,
            agent_id=request.agent_id,
            guardrail="prompt_injection",
            action="warned",
            reason=f"{tool}: {signals}"[:300],
        )

    async def _run_crew(self, request: CrewRequest, prompt: str, hub: TelemetryHub) -> str:
        settings = self.services.settings
        worktree = _checked_worktree(Path(request.worktree), settings.data_dir)
        registry = SkillRegistry(settings.data_dir / "skills")
        offered = _offered_skills(registry, request)
        mcp = McpWorkspace(
            root=worktree,
            workspace=Path(request.workspace),
            allowed_images=settings.sandbox_images,
            check_timeout_s=settings.sandbox_timeout_s,
            writable=_writable_for(request),
            write_only=_write_only_for(request),
            skills=tuple(s.name for s in offered),
            skills_dir=registry.user_dir,
            coordination=coordination_of(request),
        )
        await run_in_threadpool(mcp.start)
        plugin_host: PluginHost | None = None
        try:
            loop = asyncio.get_running_loop()
            persona = _persona_for(request) if isinstance(request, PersonaRequest) else None
            llm = HexLLM(
                router=self.services.providers,
                loop=loop,
                ctx=CallContext(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    complexity=request.complexity,
                    route=await self._route(persona, getattr(request, "escalate", False)),
                    persona_id=persona.id if persona else None,
                    variant_id=getattr(request, "variant_id", None),
                ),
                # Writing tests is coding work, whatever the persona's usual role.
                purpose=(
                    "coder"
                    if isinstance(request, PersonaRequest) and request.mode == "acceptance"
                    else persona.purpose
                    if persona
                    else _crew_purpose(self.role)
                ),
                native_tools=settings.native_tool_calling,
            )

            def listener(name: str, args: dict[str, Any], ok: bool, text: str) -> None:
                self._note_injection(hub, request, name, text)
                hub.record_threadsafe(
                    EventType.TOOL_CALLED,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    tool=name,
                    ok=ok,
                    summary=_with_owner(
                        plugin_host.owner_of(name) if plugin_host else None,
                        tool_summary(name, args, text),
                    ),
                )

            if persona is not None:
                assert isinstance(request, PersonaRequest)
                ctx = MissionContext(
                    worktree=worktree,
                    workspace=Path(request.workspace),
                    earlier_handoffs=request.earlier_handoffs,
                )
                # Plugins the orchestrator found ready for this persona. They run in the sandbox
                # (or are reached over https), never on the host, and never for acceptance tests.
                plugin_tools: list[BaseTool] = []
                if request.plugins and request.mode == "feature":
                    host = PluginHost(request.plugins, worktree=worktree, listener=listener)
                    plugin_host = host
                    plugin_tools = await run_in_threadpool(host.start)
                agent = build_agent(
                    persona,
                    request.feature,
                    ctx,
                    llm=llm,
                    tools=[
                        *make_tools(
                            mcp,
                            tool_names_for(
                                persona,
                                acceptance=request.mode == "acceptance",
                                coordination=request.coordination,
                            ),
                            listener,
                        ),
                        *plugin_tools,
                    ],
                    max_iter=settings.agent_max_iterations,
                )
                focus = [
                    *request.feature.target_files,
                    *(f for h in ctx.earlier_handoffs for f in h.files_changed),
                ]
                prompt = feature_prompt(
                    persona,
                    request.feature,
                    ctx,
                    request.feedback,
                    acceptance=request.mode == "acceptance",
                    skills=offered,
                    plugin_tools=[t.name for t in plugin_tools],
                    criteria=request.criteria,
                    repo_map=await run_in_threadpool(build_repo_map, ctx.worktree, focus),
                    # Builders get their target files up front. Not QA's acceptance tests (they
                    # must not be written from the implementation) and not validators.
                    files_text=(
                        await run_in_threadpool(preload_files, ctx.worktree, focus)
                        if persona.kind == "worker" and request.mode == "feature"
                        else ""
                    ),
                )
            else:
                factory = roles.planner if self.role == "planner" else roles.coder
                names = READ_ONLY if self.role == "planner" else CODER
                agent = factory(
                    llm, make_tools(mcp, names, listener), settings.agent_max_iterations
                )
            raw = await roles.run_agent(
                agent,
                prompt,
                request.expected_output,
                hub.crew_callbacks(
                    request.agent_id, parent=PARENTS[self.role], task_id=request.task_id
                ),
            )
            if persona is None:
                return raw
            # A worker's answer must be a valid report; anything else fails the task so the
            # orchestrator's escalation ladder can react.
            return roles.parse_json_output(raw, AgentReport).model_dump_json()
        finally:
            if plugin_host is not None:
                await run_in_threadpool(plugin_host.close)
            await run_in_threadpool(mcp.close)


def coordination_of(request: CrewRequest) -> str:
    return request.coordination if isinstance(request, PersonaRequest) else "blackboard"


def _writable_for(request: CrewRequest) -> tuple[str, ...]:
    """Files an agent may write inside the read-only `.hex/` area: the DevOps persona writes the
    run contract and its Dockerfile (PRD §9.6), nobody else writes anything there."""
    if isinstance(request, PersonaRequest) and request.persona_id == "devops":
        return (CONTRACT_PATH, DOCKERFILE_PATH)
    return ()


def _write_only_for(request: CrewRequest) -> tuple[str, ...]:
    """QA writing acceptance tests may write nothing but `tests/acceptance/`."""
    if isinstance(request, PersonaRequest) and request.mode == "acceptance":
        return (ACCEPTANCE_DIR,)
    return ()


def _marked_source(text: str) -> str | None:
    """If a tool's result was labelled by the injection guardrail, why (else None). The label may
    sit after the plugin wrapper line, so the start of the text is searched."""
    index = text[:400].find(MARK)
    return signals_of(text[index:]) if index >= 0 else None


def _with_owner(plugin_id: str | None, summary: str) -> str:
    """A plugin tool's call is logged as `[plugin-id] ...`, so the log says whose code ran."""
    return f"[{plugin_id}] {summary}" if plugin_id else summary


def _persona_for(request: PersonaRequest) -> Persona:
    """The persona a job runs as: the snapshot the orchestrator sent (it may be edited or
    custom), else the built-in one. Raises UnknownPersona."""
    if request.persona is not None:
        if request.persona.id != request.persona_id:
            raise UnknownPersona(request.persona_id)
        return request.persona
    return get_persona(request.persona_id)


def _offered_skills(registry: SkillRegistry, request: CrewRequest) -> list[Skill]:
    """The skills a persona is offered for this feature: its own plus the feature's extras,
    keeping only those that exist and are valid."""
    if not isinstance(request, PersonaRequest):
        return []
    try:
        persona = _persona_for(request)
    except UnknownPersona:
        return []  # the job fails with a clear error further on
    found, _ = registry.resolve([*persona.skills, *request.feature.extra_skills])
    return found


def _crew_purpose(role: CrewRole) -> Literal["planner", "coder"]:
    return "planner" if role == "planner" else "coder"


def _checked_worktree(path: Path, data_dir: Path) -> Path:
    """Crews may only work in run worktrees the backend created."""
    root = (data_dir / "worktrees").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise PermissionError(f"not a run worktree: {path}")
    return resolved


class _BearerAuth(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_crew_app(services: Services) -> Starlette:
    base_url = services.settings.crew_service_url
    mounts = []
    for role in ROLES:
        a2a = A2AStarletteApplication(
            agent_card=agent_card(role, base_url),
            http_handler=DefaultRequestHandler(
                agent_executor=CrewExecutor(services, role), task_store=InMemoryTaskStore()
            ),
        )
        mounts.append(Mount(f"/{role}", app=a2a.build()))
    app = Starlette(routes=mounts)
    app.add_middleware(_BearerAuth, token=services.settings.api_token)
    return app
