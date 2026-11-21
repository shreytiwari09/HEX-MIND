"""Run a project's app and get a link to open it (PRD D71). The link goes into the chat too."""

import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func

from app.api.deps import SessionDep
from app.db.models import Conversation, Message, Mission, Project, Run
from app.preview.app_runner import AppError, AppRunner, RunningApp

router = APIRouter(prefix="/projects/{project_id}/app", tags=["apps"])


class AppStart(BaseModel):
    # Run the files of a mission that has not been applied yet (its worktree); otherwise the
    # project folder itself.
    mission_id: uuid.UUID | None = None
    # Post the link (or the reason it failed) in this chat.
    conversation_id: uuid.UUID | None = None


class AppOut(BaseModel):
    status: Literal["starting", "running", "failed", "stopped", "none"]
    url: str | None = None
    port: int | None = None
    source: str | None = None
    error: str | None = None
    logs: str | None = None


def _runner(request: Request) -> AppRunner:
    return request.app.state.apps


def _out(app: RunningApp | None, logs: str | None = None) -> AppOut:
    if app is None:
        return AppOut(status="none")
    return AppOut(
        status=app.status,
        url=app.url if app.status == "running" else None,
        port=app.host_port,
        source=app.folder,
        error=app.error,
        logs=logs,
    )


async def _folder(session: SessionDep, project: Project, mission_id: uuid.UUID | None) -> Path:
    if mission_id is None:
        return Path(project.workspace_path)
    mission = await session.get(Mission, mission_id)
    if mission is None or mission.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    run = await session.get(Run, mission.run_id)
    if run is None or not run.worktree_path or not Path(run.worktree_path).is_dir():
        raise HTTPException(status.HTTP_409_CONFLICT, "the mission's files are no longer there")
    return Path(run.worktree_path)


async def post_to_chat(
    session: SessionDep, conversation_id: uuid.UUID, project_id: uuid.UUID, text: str, meta: dict
) -> None:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project_id:
        return
    session.add(Message(conversation_id=conversation_id, role="assistant", content=text, meta=meta))
    conversation.updated_at = func.clock_timestamp()


def link_text(app: RunningApp) -> str:
    return (
        f"Your app is running: **[{app.url}]({app.url})**\n\n"
        "It runs in the sandbox and opens only on this computer. Say “stop the app” to stop it."
    )


@router.post("", response_model=AppOut)
async def start_app(
    project_id: uuid.UUID, body: AppStart, request: Request, session: SessionDep
) -> AppOut:
    """Start (or restart) the project's app and wait until it answers."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    folder = await _folder(session, project, body.mission_id)
    runner = _runner(request)
    try:
        app = await runner.start(str(project_id), folder)
    except AppError as exc:
        if body.conversation_id:
            await post_to_chat(
                session, body.conversation_id, project_id,
                f"I could not start the app: {exc}", {"kind": "app", "status": "failed"},
            )  # fmt: skip
            await session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    logs = None if app.status == "running" else runner.logs(str(project_id))
    if body.conversation_id:
        text = (
            link_text(app)
            if app.status == "running"
            else f"The app did not start: {app.error}.\n\n```\n{(logs or '')[-1500:]}\n```"
        )
        url = app.url if app.status == "running" else None
        meta = {"kind": "app", "status": app.status, "url": url}
        await post_to_chat(session, body.conversation_id, project_id, text, meta)
        await session.commit()
    return _out(app, logs)


@router.get("", response_model=AppOut)
async def app_status(project_id: uuid.UUID, request: Request) -> AppOut:
    runner = _runner(request)
    app = runner.get(str(project_id))
    return _out(app, runner.logs(str(project_id)) if app else None)


@router.delete("", response_model=AppOut)
async def stop_app(project_id: uuid.UUID, request: Request) -> AppOut:
    stopped = await _runner(request).stop(str(project_id))
    return AppOut(status="stopped" if stopped else "none")
