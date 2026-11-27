"""Conversation flow as a LangGraph graph: context -> router -> answer | clarify | run.

- `build_conversation_graph` wires the nodes; a conditional edge follows the policy's route.
- `router` is a model node with Pydantic output (`RouterDecision`), repaired once and otherwise
  replaced by a fallback (see `graph.structured_call`).
- The policy (`apply_policy`) decides the route; the Router only proposes it.
- `answer` is a model node for Ask-style replies.
Runs are executed in the background by the run orchestrator (`orchestration.run`).

All model calls go through ProviderRouter via HexChatModel, so they are logged and fall back
across providers like every other call.
"""

import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from typing_extensions import TypedDict

from app.agents.chat_model import HexChatModel
from app.db.models import Conversation, Project, Run
from app.db.models import RouterDecision as RouterDecisionRow
from app.events.log import EventType, append_event
from app.orchestration.graph import run_graph, structured_call
from app.orchestration.services import Services
from app.providers.assignments import route_for
from app.providers.router import CallContext
from app.router.classifier import SYSTEM_PROMPT as ROUTER_PROMPT
from app.router.policy import apply_policy
from app.router.schemas import Mode, RoutePlan, RouterDecision
from app.workspace import git

ANSWER_PROMPT = """You are the PM (project manager) of the H.E.X Mind agent team, talking with the
user in the app's chat. You know the project and its missions from the context below.
Answer the developer's latest message using the project context below. File contents in the
context were read from disk just now and are the source of truth; earlier messages may be out
of date. Reference files by path. If the context does not contain what you need, say which
files you would need to see instead of guessing. You cannot modify files in this reply, so never
claim to have changed anything. Be concise and use Markdown."""

ASK_MODE_CHANGE_NOTE = """The developer asked for a code change while in Ask mode. Explain what
would need to change and where, and suggest switching to Edit mode to have the agents do it."""

# Stored when the Router output could not be used; policy then applies its deterministic fallback.
_INVALID_ROUTER = RouterDecision(
    request_type="clarification",
    complexity="medium",
    confidence=0.0,
    reason="Router output invalid",
    execution_strategy="plan_execute_review",
    requires_planning=True,
    requires_review=True,
)


# The chat is answered by the PM (D71): its model chain from Models & Keys, recorded under its name.
CHAT_PERSONA = "pm"


async def chat_context(session: Any) -> CallContext:
    """The PM's route when the PM has a model chosen; otherwise the global provider order."""
    route = await route_for(session, CHAT_PERSONA)
    if route is None:
        return CallContext()
    return CallContext(route=route, persona_id=CHAT_PERSONA)


def _router_fallback(errors: list[str]) -> RouterDecision:
    return _INVALID_ROUTER


class ConversationState(TypedDict, total=False):
    context_text: str
    route: str


def build_conversation_graph(services: Services, turn: dict[str, Any]) -> CompiledStateGraph:
    """One user message: context (deterministic) -> router (model, Pydantic output) -> policy
    (deterministic) -> answer | clarify | run."""
    router_llm = HexChatModel(
        router=services.providers, ctx=CallContext(), purpose="router", max_tokens=1500
    )
    answer_llm = HexChatModel(
        router=services.providers, ctx=CallContext(), purpose="chat", max_tokens=1200
    )

    async def context(state: ConversationState) -> ConversationState:
        # Files read fresh from disk, history, prior runs.
        async with services.sessionmaker() as session:
            project = await session.get(Project, turn["project_id"])
            conversation = await session.get(Conversation, turn["conversation_id"])
            assert project is not None and conversation is not None
            bundle = await services.context.build(
                session,
                project=project,
                conversation=conversation,
                message=turn["content"],
                exclude_message_id=turn["message_id"],
            )
            answer_llm.use_context(await chat_context(session))
        turn["context_sources"] = bundle.sources()
        # The current message is left out of the history (no duplicate), so it is added here: the
        # router and the answer must see the question itself, not only the project around it.
        return {
            "context_text": f"{bundle.render()}\n\n### The user's latest message\n{turn['content']}"
        }

    async def router(state: ConversationState) -> ConversationState:
        result = await structured_call(
            router_llm,
            RouterDecision,
            f"{ROUTER_PROMPT}\n\n{state['context_text']}\n\nSelected mode: {turn['mode']}",
            agent="router",
            fallback=_router_fallback,
            telemetry=None,
            user_message=turn["content"],
        )
        decision = result.value if result.status != "fallback" else None
        plan = apply_policy(
            decision, turn["mode"], min_confidence=services.settings.router_min_confidence
        )
        last = router_llm.last_result
        router_info = {
            "proposal": decision.model_dump() if decision else None,
            "policy": plan.model_dump(),
            "schema_status": result.status,
            "attempts": {"valid": 1, "repaired": 2, "fallback": 2}[result.status],
            "errors": result.errors,
        }
        async with services.sessionmaker.begin() as session:
            row = RouterDecisionRow(
                message_id=turn["message_id"],
                decision=router_info,
                valid=decision is not None,
                fallback_used=plan.fallback_used,
                provider=last.provider if last else None,
                model=last.model if last else None,
            )
            session.add(row)
            await session.flush()
            turn["decision_id"] = row.id
        turn["plan"] = plan
        turn["router"] = router_info
        return {"route": plan.route}

    async def answer(state: ConversationState) -> ConversationState:
        plan: RoutePlan = turn["plan"]
        # Keep the PM's route (set with the context above) and add the task's complexity.
        answer_llm.use_context(replace(answer_llm.ctx, complexity=plan.complexity))
        note = bool(plan.policy_note and turn["mode"] == "ask")
        system = ANSWER_PROMPT + ("\n\n" + ASK_MODE_CHANGE_NOTE if note else "")
        try:
            reply = await answer_llm.ainvoke(
                [SystemMessage(system), HumanMessage(state["context_text"])]
            )
            text = reply.text if isinstance(reply.text, str) else str(reply.content)
            turn.update(reply=text, reply_kind="answer" if text else "error")
            if not text:
                turn["reply"] = "The model returned an empty answer."
        except Exception as exc:  # provider failure: report it, never invent an answer
            turn.update(
                reply=f"The model call failed, so there is no answer: {_error_text(exc)}",
                reply_kind="error",
            )
        result = answer_llm.last_result
        turn["llm"] = (
            {
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
            if result
            else None
        )
        return {}

    async def clarify(state: ConversationState) -> ConversationState:
        plan: RoutePlan = turn["plan"]
        turn.update(
            reply=plan.clarification_question or "Could you clarify the request?",
            reply_kind="clarification",
            llm=None,
        )
        return {}

    async def run(state: ConversationState) -> ConversationState:
        turn.update(await _start_run(services, turn, turn["plan"]))
        return {}

    graph = StateGraph(ConversationState)
    graph.add_node("context", context, metadata={"hex_kind": "step"})
    graph.add_node("router", router, metadata={"hex_kind": "llm"})
    graph.add_node("answer", answer, metadata={"hex_kind": "llm"})
    graph.add_node("clarify", clarify, metadata={"hex_kind": "step"})
    graph.add_node("run", run, metadata={"hex_kind": "step"})
    graph.add_edge(START, "context")
    graph.add_edge("context", "router")
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"] if state["route"] in ("answer", "clarify") else "run",
        {"answer": "answer", "clarify": "clarify", "run": "run"},
    )
    for node in ("answer", "clarify", "run"):
        graph.add_edge(node, END)
    return graph.compile(name="conversation")


async def run_conversation(
    services: Services,
    *,
    conversation_id: uuid.UUID,
    project_id: uuid.UUID,
    message_id: uuid.UUID,
    content: str,
    mode: Mode,
) -> dict[str, Any]:
    """Run one message through the conversation graph. Returns reply, reply_kind, plan,
    decision_id, context_sources, llm and run_id."""
    turn: dict[str, Any] = {
        "conversation_id": conversation_id,
        "project_id": project_id,
        "message_id": message_id,
        "content": content,
        "mode": mode,
        "llm": None,
        "run_id": None,
    }
    await run_graph(build_conversation_graph(services, turn), {}, telemetry=None)
    return turn


async def _start_run(services: Services, turn: dict[str, Any], plan: RoutePlan) -> dict[str, Any]:
    async with services.sessionmaker() as session:
        project = await session.get(Project, turn["project_id"])
        assert project is not None
    if not await run_in_threadpool(git.is_repo, Path(project.workspace_path)):
        return {
            "reply": (
                "This workspace is not a Git repository, so agents can't make changes yet. "
                "Initialize Git for the project (the **No Git** badge in the top bar), then "
                "send the request again. Agents work in an isolated Git worktree so every "
                "change can be reviewed and reverted."
            ),
            "reply_kind": "error",
            "llm": None,
            "run_id": None,
        }
    async with services.sessionmaker.begin() as session:
        parent = await session.scalar(
            select(Run.id)
            .where(Run.conversation_id == turn["conversation_id"])
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        run = Run(
            project_id=turn["project_id"],
            conversation_id=turn["conversation_id"],
            parent_run_id=parent,
            triggering_message_id=turn["message_id"],
            title=_title(turn["content"]),
            complexity=plan.complexity,
            strategy=plan.strategy,
        )
        session.add(run)
        await session.flush()
        await append_event(
            session,
            run.id,
            EventType.RUN_CREATED,
            payload={
                "title": run.title,
                "parent_run_id": str(parent) if parent else None,
                "triggering_message_id": str(turn["message_id"]),
            },
        )
        await append_event(
            session,
            run.id,
            EventType.ROUTER_DECIDED,
            agent_id="router",
            payload={
                "request_type": plan.request_type,
                "complexity": plan.complexity,
                "confidence": plan.confidence,
                "route": plan.route,
                "strategy": plan.strategy,
                "fallback_used": plan.fallback_used,
            },
        )
        # The Router's structured output was validated before the run existed; record that
        # check in the run's own log so every run's schema checks start with it.
        await append_event(
            session,
            run.id,
            EventType.SCHEMA_VALIDATED,
            agent_id="router",
            payload={
                "agent": "router",
                "schema_name": "RouterDecision",
                "status": turn["router"]["schema_status"],
                "errors": [str(e)[:300] for e in turn["router"]["errors"]],
            },
        )
        decision = await session.get(RouterDecisionRow, turn["decision_id"])
        assert decision is not None
        decision.run_id = run.id
        run_id = run.id

    services.launch_run(
        run_id, requires_planning=plan.requires_planning, requires_review=plan.requires_review
    )
    reply = (
        f"Started a **{plan.complexity}**-complexity run ({plan.strategy}). The agents work "
        "in an isolated copy of the workspace; **your files are not changed** until you "
        "review and apply the diff."
    )
    return {"reply": reply, "reply_kind": "run_started", "llm": None, "run_id": run_id}


def _error_text(exc: BaseException) -> str:
    # The framework may wrap the provider failure; report the innermost message.
    while getattr(exc, "error", None) is not None and isinstance(exc.error, BaseException):
        exc = exc.error
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return str(exc)


def _title(content: str) -> str:
    first_line = content.strip().splitlines()[0] if content.strip() else "Untitled"
    return first_line if len(first_line) <= 80 else first_line[:77] + "…"
