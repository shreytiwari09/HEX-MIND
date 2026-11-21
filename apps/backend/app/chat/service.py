import asyncio
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func

from app.context.summary import maybe_update_summary
from app.db.models import Conversation, Message
from app.orchestration.conversation import run_conversation
from app.orchestration.services import Services
from app.router.schemas import Mode

if TYPE_CHECKING:
    from app.preview.app_runner import AppRunner

DEFAULT_TITLE = "New conversation"

# Short commands the chat answers itself, with no model call (D71): run or stop the project's app.
_RUN = re.compile(
    r"^\s*(?:please\s+)?(?:run|start|launch|open)(?:\s+(?:it|this|the\s+app|my\s+app|"
    r"the\s+project|the\s+calculator))?\s*(?:please)?\s*[.!]?\s*$",
    re.IGNORECASE,
)
_STOP = re.compile(
    r"^\s*(?:please\s+)?stop(?:\s+(?:it|the\s+app|my\s+app|running))?\s*[.!]?\s*$",
    re.IGNORECASE,
)


# "run 2 + 3": run a command-line project with these arguments (D78). Only used when the
# project is a command-line program; otherwise the message goes to the PM as usual.
_RUN_WITH = re.compile(r"^\s*run\s+(?P<args>\S.{0,500})$", re.IGNORECASE | re.DOTALL)


def run_arguments(content: str) -> str | None:
    match = _RUN_WITH.match(content)
    return match.group("args").strip() if match and "\n" not in content.strip() else None


_TERMINAL = re.compile(
    r"^\s*(?:please\s+)?open\s+(?:a\s+|the\s+)?(?:terminal|shell)(?:\s+(?:here|for\s+it))?"
    r"\s*(?:please)?\s*[.!]?\s*$",
    re.IGNORECASE,
)


def app_command(content: str) -> str | None:
    """'run', 'stop' or 'terminal' when the whole message is one of those short commands."""
    if _TERMINAL.match(content):
        return "terminal"
    if _RUN.match(content):
        return "run"
    if _STOP.match(content):
        return "stop"
    return None


@dataclass
class Exchange:
    user_message: Message
    assistant_message: Message
    run_id: uuid.UUID | None


class ChatService:
    def __init__(self, services: Services, apps: "AppRunner | None" = None) -> None:
        self._services = services
        self._apps = apps

    async def handle_message(
        self, conversation_id: uuid.UUID, content: str, mode: Mode
    ) -> Exchange:
        sessionmaker = self._services.sessionmaker

        # Persist the user's message first so it survives any later failure.
        async with sessionmaker.begin() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                raise LookupError("conversation not found")
            user_message = Message(
                conversation_id=conversation_id, role="user", mode=mode, content=content
            )
            session.add(user_message)
            if conversation.title == DEFAULT_TITLE:
                conversation.title = _title(content)
            conversation.updated_at = func.clock_timestamp()
            await session.flush()
            project_id = conversation.project_id

        command = app_command(content) if self._apps is not None else None
        reply_meta = None
        if command is not None:
            reply_meta = await self._app_reply(project_id, command)
        elif self._apps is not None and (args := run_arguments(content)) is not None:
            reply_meta = await self._cli_reply(project_id, args)  # None: not a CLI project
        if reply_meta is not None:
            reply, meta = reply_meta
            async with sessionmaker.begin() as session:
                assistant_message = Message(
                    conversation_id=conversation_id, role="assistant", content=reply, meta=meta
                )
                session.add(assistant_message)
                await session.flush()
            return Exchange(user_message, assistant_message, None)

        state = await run_conversation(
            self._services,
            conversation_id=conversation_id,
            project_id=project_id,
            message_id=user_message.id,
            content=content,
            mode=mode,
        )

        plan = state["plan"]
        async with sessionmaker.begin() as session:
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=state["reply"],
                meta={
                    "kind": state["reply_kind"],
                    "route": {
                        "route": plan.route,
                        "request_type": plan.request_type,
                        "complexity": plan.complexity,
                        "confidence": plan.confidence,
                        "strategy": plan.strategy,
                        "fallback_used": plan.fallback_used,
                        "policy_note": plan.policy_note,
                        "reason": plan.reason,
                        "decision_id": str(state["decision_id"]),
                    },
                    "context": state["context_sources"],
                    "llm": state.get("llm"),
                    "run_id": str(state["run_id"]) if state.get("run_id") else None,
                },
            )
            session.add(assistant_message)
            await session.flush()

        self._services.background.spawn(
            maybe_update_summary(self._services, conversation_id),
            name=f"summary-{conversation_id}",
        )
        return Exchange(user_message, assistant_message, state.get("run_id"))

    async def _app_reply(self, project_id: uuid.UUID, command: str) -> tuple[str, dict]:
        from app.api.apps import link_text
        from app.db.models import Project
        from app.preview.app_runner import AppError

        assert self._apps is not None
        if command == "stop":
            stopped = await self._apps.stop(str(project_id))
            text = "Stopped the app." if stopped else "No app is running for this project."
            return text, {"kind": "app", "status": "stopped" if stopped else "none"}
        async with self._services.sessionmaker() as session:
            project = await session.get(Project, project_id)
        assert project is not None
        if command == "terminal":
            return await self._terminal_reply(Path(project.workspace_path))
        cli = await self._cli_reply(project_id, "", folder=Path(project.workspace_path))
        if cli is not None:
            return cli
        try:
            app = await self._apps.start(str(project_id), Path(project.workspace_path))
        except AppError as exc:
            return f"I could not start the app: {exc}", {"kind": "app", "status": "failed"}
        if app.status != "running":
            logs = self._apps.logs(str(project_id))[-1500:]
            text = f"The app did not start: {app.error}.\n\n```\n{logs}\n```"
            return text, {"kind": "app", "status": app.status}
        return link_text(app), {"kind": "app", "status": "running", "url": app.url}

    async def _terminal_reply(self, folder: Path) -> tuple[str, dict]:
        from app.preview import terminal

        assert self._apps is not None
        try:
            steps = await asyncio.to_thread(terminal.open_terminal, folder, self._apps.images)
        except terminal.TerminalError as exc:
            return f"I could not open a terminal: {exc}", {"kind": "app", "status": "failed"}
        tried = "".join(f"\n\n```\n{s}\n```" for s in steps)
        text = (
            "Opened a terminal in this project's sandbox: it has this project folder and "
            "nothing else from your computer. Type `exit` there to close it."
            + (f"\n\nTry:{tried}" if steps else "")
        )
        return text, {"kind": "app", "status": "terminal"}

    async def _cli_reply(
        self, project_id: uuid.UUID, args: str, folder: Path | None = None
    ) -> tuple[str, dict] | None:
        """Run a command-line project in the sandbox and show its output; None when the
        project is not one (a web app gets a link instead)."""
        from app.db.models import Project
        from app.preview.cli_runner import cli_plan, cli_reply, run_cli

        if folder is None:
            async with self._services.sessionmaker() as session:
                project = await session.get(Project, project_id)
            assert project is not None
            folder = Path(project.workspace_path)
        plan = await asyncio.to_thread(cli_plan, folder)
        if plan is None:
            return None
        outcome = await run_cli(folder, plan, args)
        meta = {"kind": "app", "status": "ran", "exit_code": outcome.exit_code}
        return cli_reply(plan, args, outcome), meta


def _title(content: str) -> str:
    line = content.strip().splitlines()[0] if content.strip() else DEFAULT_TITLE
    return line if len(line) <= 60 else line[:57] + "…"
