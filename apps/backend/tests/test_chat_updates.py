"""A mission's progress in the chat (PRD D71 step 3): written from its state, never by a model."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import Conversation, Message
from app.missions import chat_updates
from app.preview.app_runner import RunningApp
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import GOOD, Script, approve, finish, new_mission

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


def test_each_update_says_only_what_the_mission_state_says() -> None:
    assert chat_updates.feature_text("Todo model", "backend", "in_progress", 0) == (
        "🔨 Building **Todo model** (backend)…"
    )
    assert "attempt 2" in (chat_updates.feature_text("Todo model", "backend", "in_progress", 1))
    assert "tests passed in the sandbox" in chat_updates.feature_text("T", None, "done", 1)
    assert chat_updates.feature_text("T", None, "failed", 3) == "❌ **T** failed after 3 attempts."
    assert chat_updates.feature_text("T", None, "pending", 0) is None  # nothing worth a message
    assert "Needs you:" in chat_updates.need_text("Tests failed.", ["retry", "skip", "stop"])
    assert "retry, skip, stop" in chat_updates.need_text("x", ["retry", "skip", "stop"])
    assert chat_updates.mission_text("completed", None).startswith("🎉 **Mission complete:**")
    assert chat_updates.mission_text("awaiting_approval", None) is None


async def messages_of(app: FastAPI, title: str) -> list[Message]:
    async with app.state.sessionmaker() as session:
        conversation = await session.scalar(
            select(Conversation).where(Conversation.title == f"Mission: {title}")
        )
        assert conversation is not None, "the mission has its own conversation"
        return list(
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at)
            )
        )


@needs_docker
async def test_a_mission_posts_its_progress_in_its_own_conversation(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    texts = [m.content for m in await messages_of(app, "Todo app")]
    assert texts[0] == "▶️ The mission is running."
    assert texts.index("🔨 Building **Todo model** (backend)…") < texts.index(
        "✅ **Todo model** is done: its tests passed in the sandbox."
    )
    assert "✅ **Filter helper** is done: its tests passed in the sandbox." in texts
    assert texts[-1].startswith("🎉 **Mission complete:**")
    for message in await messages_of(app, "Todo app"):
        assert message.role == "assistant" and message.meta["kind"] == "mission_update"


@needs_docker
async def test_a_mission_that_needs_the_user_says_so_in_the_chat(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    broken = [("src/todos.js", "module.exports = {}\n")]  # no tests: never accepted
    script = Script(
        {("Todo model", n): broken for n in range(3)}
        | {("Filter helper", 0): GOOD["Filter helper"]}
    )
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    texts = [m.content for m in await messages_of(app, "Todo app")]
    assert any(t.startswith("❌ **Todo model** failed after 3 attempts") for t in texts)
    assert any(t.startswith("⚠️ **Needs you:**") and "retry, skip, stop" in t for t in texts)


class FakeApps:
    def __init__(self) -> None:
        self.started: list[tuple[str, Path]] = []

    async def start(self, project_id: str, folder: Path) -> RunningApp:
        self.started.append((project_id, folder))
        return RunningApp(
            project_id=project_id, folder=str(folder), container="c", port=3000,
            host_port=3000, url="http://localhost:3000", status="running",
        )  # fmt: skip


@needs_docker
async def test_a_completed_app_is_started_from_the_mission_files_and_its_link_posted(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    contract = {"stack": "node", "image": "node:22-alpine", "test": "node --test",
                "start": "node src/todos.js", "port": 3000}  # fmt: skip
    (repo / ".hex").mkdir()
    (repo / ".hex" / "project.json").write_text(json.dumps(contract))
    from app.workspace import git

    git.commit_all(repo, "contract")
    apps = FakeApps()
    app.state.services.apps = apps
    app.state.settings.app_autorun_after_mission = True
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    [(_, folder)] = apps.started
    assert folder != repo  # the mission's own files, before any Apply
    last = (await messages_of(app, "Todo app"))[-1]
    assert last.meta == {"kind": "app", "status": "running", "url": "http://localhost:3000",
                         "mission_id": mission["id"]}  # fmt: skip
    assert (
        last.content.startswith("Try it before you Apply.")
        and "http://localhost:3000" in last.content
    )
