import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import SessionDep, SettingsDep
from app.api.schemas import (
    FileOut,
    FileWrite,
    FileWritten,
    ProjectCreate,
    ProjectOut,
    TreeEntryOut,
)
from app.db.models import Connection, Project
from app.providers.presets import preset_for
from app.workspace import files, git
from app.workspace.paths import PathViolation

router = APIRouter(prefix="/projects", tags=["projects"])


def _validate_workspace(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "workspace_path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "workspace_path does not exist") from None
    if not resolved.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "workspace_path is not a directory")
    if resolved.parent == resolved:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "a drive or filesystem root cannot be a workspace"
        )
    return resolved


async def _get_project(session: SessionDep, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: SessionDep) -> list[Project]:
    result = await session.scalars(select(Project).order_by(Project.updated_at.desc()).limit(20))
    return list(result)


@router.post("", response_model=ProjectOut)
async def open_project(body: ProjectCreate, session: SessionDep) -> Project:
    """Register a workspace, or return the existing project for the same folder."""
    workspace = await run_in_threadpool(_validate_workspace, body.workspace_path)
    git_enabled = await run_in_threadpool((workspace / ".git").exists)

    project = await session.scalar(select(Project).where(Project.workspace_path == str(workspace)))
    if project is None:
        project = Project(name=workspace.name, workspace_path=str(workspace))
        session.add(project)
    project.git_enabled = git_enabled
    project.updated_at = func.clock_timestamp()
    await session.flush()
    await session.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, session: SessionDep) -> Project:
    return await _get_project(session, project_id)


@router.post("/{project_id}/git/init", response_model=ProjectOut)
async def init_git(project_id: uuid.UUID, session: SessionDep) -> Project:
    """Initialize a Git repository with one commit of the current files (explicit user action).
    Agent runs require Git so their changes stay isolated and revertible."""
    project = await _get_project(session, project_id)
    root = Path(project.workspace_path)
    if await run_in_threadpool(git.is_repo, root):
        raise HTTPException(status.HTTP_409_CONFLICT, "the workspace is already a Git repository")
    try:
        await run_in_threadpool(git.init_repo, root)
    except git.GitError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from None
    project.git_enabled = True
    project.updated_at = func.clock_timestamp()
    await session.flush()
    await session.refresh(project)
    return project


@router.get("/{project_id}/tree", response_model=list[TreeEntryOut])
async def get_tree(
    project_id: uuid.UUID, session: SessionDep, path: str = ""
) -> list[TreeEntryOut]:
    project = await _get_project(session, project_id)
    try:
        entries = await run_in_threadpool(files.list_directory, Path(project.workspace_path), path)
    except PathViolation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except (FileNotFoundError, NotADirectoryError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "directory not found") from None
    return [TreeEntryOut(**vars(e)) for e in entries]


@router.get("/{project_id}/file", response_model=FileOut)
async def read_file(
    project_id: uuid.UUID, path: str, session: SessionDep, settings: SettingsDep
) -> FileOut:
    project = await _get_project(session, project_id)
    try:
        content = await run_in_threadpool(
            files.read_file,
            Path(project.workspace_path),
            path,
            max_bytes=settings.max_editor_file_bytes,
        )
    except PathViolation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except (files.NotAFile, FileNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found") from None
    return FileOut(**vars(content))


@router.put(
    "/{project_id}/file",
    response_model=FileWritten,
    responses={409: {"description": "File changed on disk since it was read"}},
)
async def write_file(
    project_id: uuid.UUID, body: FileWrite, session: SessionDep
) -> FileWritten | JSONResponse:
    project = await _get_project(session, project_id)
    try:
        new_hash = await run_in_threadpool(
            files.write_file,
            Path(project.workspace_path),
            body.path,
            body.content,
            base_hash=body.base_hash,
        )
    except PathViolation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except files.NotAFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "path is a directory") from None
    except files.FileConflict as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "file changed on disk", "current_hash": exc.current_hash},
        )
    return FileWritten(path=body.path, hash=new_hash)


class PrivacyConnection(BaseModel):
    id: uuid.UUID
    name: str
    local: bool  # runs on this machine: always allowed


class PrivacyOut(BaseModel):
    mode: Literal["any", "trusted", "local"]
    trusted_connections: list[uuid.UUID]
    connections: list[PrivacyConnection]


class PrivacyIn(BaseModel):
    mode: Literal["any", "trusted", "local"]
    trusted_connections: list[uuid.UUID] = Field(default_factory=list, max_length=50)


async def _privacy_out(session: SessionDep, project: Project) -> PrivacyOut:
    connections = list(await session.scalars(select(Connection).order_by(Connection.name)))
    return PrivacyOut(
        mode=project.privacy_mode,  # type: ignore[arg-type]
        trusted_connections=[uuid.UUID(str(c)) for c in project.trusted_connections or []],
        connections=[
            PrivacyConnection(id=c.id, name=c.name, local=preset_for(c.provider_type).local)
            for c in connections
        ],
    )


@router.get("/{project_id}/privacy", response_model=PrivacyOut)
async def get_privacy(project_id: uuid.UUID, session: SessionDep) -> PrivacyOut:
    """Which providers may see this project's prompts (PRD §13.5)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return await _privacy_out(session, project)


@router.put("/{project_id}/privacy", response_model=PrivacyOut)
async def set_privacy(project_id: uuid.UUID, body: PrivacyIn, session: SessionDep) -> PrivacyOut:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    known = set(await session.scalars(select(Connection.id)))
    unknown = [str(c) for c in body.trusted_connections if c not in known]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"no such connection: {', '.join(unknown)}"
        )
    project.privacy_mode = body.mode
    # The list only matters for "trusted"; it is kept as given so switching modes loses nothing.
    project.trusted_connections = [str(c) for c in dict.fromkeys(body.trusted_connections)]
    await session.flush()
    return await _privacy_out(session, project)
