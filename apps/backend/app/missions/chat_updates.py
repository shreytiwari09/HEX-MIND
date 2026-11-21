"""A mission's progress in the chat (PRD D71 step 3).

Each mission gets its own conversation ("Mission: <title>") in the project's chat, created at the
first update. The updates are written from the mission's own state changes (feature status,
needs, mission status), never by a model, so nothing in them is invented. The user can ask the
PM questions in the same conversation. When a mission completes and the project is an app, it is
started from the mission's files and its link is posted there.
"""

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, Mission

if TYPE_CHECKING:
    from app.orchestration.services import Services

TITLE_PREFIX = "Mission: "


def conversation_title(mission: Mission) -> str:
    title = f"{TITLE_PREFIX}{mission.title}"
    return title if len(title) <= 255 else title[:254] + "…"


async def mission_conversation(session: AsyncSession, mission: Mission) -> Conversation:
    title = conversation_title(mission)
    existing = await session.scalar(
        select(Conversation)
        .where(Conversation.project_id == mission.project_id, Conversation.title == title)
        .order_by(Conversation.created_at)
        .limit(1)
    )
    if existing is not None:
        return existing
    conversation = Conversation(project_id=mission.project_id, title=title)
    session.add(conversation)
    await session.flush()
    return conversation


async def post(
    session: AsyncSession, mission: Mission, text: str, meta: dict[str, Any] | None = None
) -> None:
    conversation = await mission_conversation(session, mission)
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=text,
            meta={"kind": "mission_update", "mission_id": str(mission.id), **(meta or {})},
        )
    )
    conversation.updated_at = func.clock_timestamp()


def feature_text(title: str, persona: str | None, status: str, attempts: int) -> str | None:
    who = f" ({persona})" if persona else ""
    if status == "in_progress":
        if attempts:
            return f"🔁 Trying **{title}** again{who}: attempt {attempts + 1}."
        return f"🔨 Building **{title}**{who}…"
    if status == "done":
        return f"✅ **{title}** is done: its tests passed in the sandbox."
    if status == "failed":
        tries = "attempt" if attempts == 1 else "attempts"
        return f"❌ **{title}** failed after {attempts} {tries}."
    if status == "skipped":
        return f"⏭ **{title}** was skipped."
    return None


def need_text(summary: str, options: list[str]) -> str:
    choices = ", ".join(options)
    return f"⚠️ **Needs you:** {summary} Open the mission to choose ({choices})."


def mission_text(status: str, reason: str | None) -> str | None:
    why = f" ({reason})" if reason else ""
    texts = {
        "running": "▶️ The mission is running.",
        "paused": f"⏸ The mission is paused{why}.",
        "completed": (
            "🎉 **Mission complete:** every feature is done or skipped. Review the changes and "
            "Apply them to keep them in your project."
        ),
        "failed": f"The mission failed{why}.",
        "stopped": f"⏹ The mission was stopped{why}.",
        "applied": "📥 The changes were applied to your project.",
    }
    return texts.get(status)


async def mission_status(
    session: AsyncSession, run_id: uuid.UUID, status: str, reason: str | None
) -> None:
    text = mission_text(status, reason)
    if text is None:
        return
    mission = await session.scalar(select(Mission).where(Mission.run_id == run_id))
    if mission is not None:
        await post(session, mission, text, {"status": status})


async def run_after_mission(services: "Services", mission_id: uuid.UUID, folder: Path) -> None:
    """Start a completed mission's app from its files and post the link; a project with no
    `start` and `port` (a library, a command-line tool) is left alone."""
    from app.api.apps import link_text
    from app.preview.app_runner import AppError
    from app.sandbox.contract import load_contract

    apps = services.apps
    try:
        contract = load_contract(folder)
    except ValueError:
        return
    if apps is None or contract is None or not contract.start or not contract.port:
        return
    async with services.sessionmaker() as session:
        mission = await session.get(Mission, mission_id)
    if mission is None:
        return
    try:
        app = await apps.start(str(mission.project_id), folder)
        if app.status == "running":
            text = "Try it before you Apply. " + link_text(app)
            meta: dict[str, Any] = {"kind": "app", "status": "running", "url": app.url}
        else:
            text = f"The app did not start: {app.error}."
            meta = {"kind": "app", "status": app.status}
    except AppError as exc:
        text, meta = f"I could not start the app: {exc}", {"kind": "app", "status": "failed"}
    async with services.sessionmaker.begin() as session:
        mission = await session.get(Mission, mission_id)
        if mission is not None:
            await post(session, mission, text, meta)
