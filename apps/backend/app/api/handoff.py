"""After a project is built: prepare it as a normal repository, and publish it to GitHub
(PRD D84). Both run only when the user clicks."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep
from app.db.models import Project
from app.handoff import prepare as preparing
from app.handoff import publish as publishing
from app.sandbox.contract import load_contract
from app.workspace import git

router = APIRouter(prefix="/projects/{project_id}/handoff", tags=["handoff"])


class HandoffStatus(BaseModel):
    stack: str
    missing: list[str]
    gh_installed: bool
    gh_logged_in: bool
    gh_account: str | None
    remote: str | None
    problems: list[str]


class PrepareOut(BaseModel):
    stack: str
    created: list[str]
    updated: list[str]
    commit: str | None


class PublishIn(BaseModel):
    name: str
    private: bool = True


class PublishOut(BaseModel):
    url: str


async def _root(session: SessionDep, project_id: uuid.UUID) -> Path:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    root = Path(project.workspace_path)
    if not await run_in_threadpool(git.is_repo, root):
        raise HTTPException(status.HTTP_409_CONFLICT, "initialize Git for this project first")
    return root


def _status(root: Path) -> HandoffStatus:
    try:
        contract = load_contract(root)
    except ValueError:
        contract = None
    stack = preparing.stack_of(root, contract)
    wanted = [".env.example", ".github/workflows/ci.yml", ".github/dependabot.yml"]
    if stack == "streamlit":
        wanted.append(".streamlit/config.toml")
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8", errors="replace") if readme.is_file() else ""
    missing = [rel for rel in wanted if not (root / rel).exists()]
    if "## Deploy" not in text:
        missing.append("README: Deploy section")
    gh = publishing.gh_status()
    return HandoffStatus(
        stack=stack, missing=missing, gh_installed=gh.installed, gh_logged_in=gh.logged_in,
        gh_account=gh.account, remote=publishing.existing_remote(root),
        problems=publishing.problems(root),
    )  # fmt: skip


@router.get("", response_model=HandoffStatus)
async def handoff_status(project_id: uuid.UUID, session: SessionDep) -> HandoffStatus:
    return await run_in_threadpool(_status, await _root(session, project_id))


@router.post("/prepare", response_model=PrepareOut)
async def prepare(project_id: uuid.UUID, session: SessionDep) -> PrepareOut:
    root = await _root(session, project_id)
    done = await run_in_threadpool(preparing.prepare, root)
    return PrepareOut(
        stack=done.stack, created=done.created, updated=done.updated, commit=done.commit
    )


@router.post("/publish", response_model=PublishOut)
async def publish(project_id: uuid.UUID, body: PublishIn, session: SessionDep) -> PublishOut:
    root = await _root(session, project_id)
    try:
        url = await run_in_threadpool(publishing.publish, root, body.name, private=body.private)
    except publishing.PublishError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return PublishOut(url=url)
