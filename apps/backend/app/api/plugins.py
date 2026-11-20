"""The plugin manager (PRD §11.7): what is installed, what each can do, and your approval."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, SettingsDep
from app.db.models import PluginRow
from app.plugins import registry
from app.plugins.config import approval_reasons, config_hash, permissions

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginIn(BaseModel):
    id: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=registry.MAX_NAME)
    description: str = Field(default="", max_length=registry.MAX_DESCRIPTION)
    config: dict[str, Any]


class PluginEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=registry.MAX_NAME)
    description: str | None = Field(default=None, max_length=registry.MAX_DESCRIPTION)
    config: dict[str, Any] | None = None


class ApproveIn(BaseModel):
    # The permission labels the user was shown; they must match the plugin's current ones.
    permissions: list[str]


class PluginOut(BaseModel):
    id: str
    name: str
    description: str
    config: dict[str, Any]
    permissions: list[str]  # derived from the configuration, never from the plugin
    needs_approval: bool
    reasons: list[str]  # why it needs approval
    approved: bool  # approved for exactly its current configuration
    approved_at: datetime | None
    enabled: bool
    status: str  # disabled | needs_approval | ready
    personas: list[str]  # the personas it is attached to
    config_hash: str


def _out(row: PluginRow) -> PluginOut:
    config = registry.config_of(row)
    reasons = approval_reasons(config)
    return PluginOut(
        id=row.id,
        name=row.name,
        description=row.description,
        config=config.model_dump(),
        permissions=list(permissions(config)),
        needs_approval=bool(reasons),
        reasons=reasons,
        approved=row.approved_hash == config_hash(config),
        approved_at=row.approved_at,
        enabled=row.enabled,
        status=registry.status_of(row),
        personas=registry.personas_with(row.id),
        config_hash=config_hash(config),
    )


def _refused(exc: registry.PluginError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


class OptionsOut(BaseModel):
    images: list[str]  # the images a stdio plugin may run in


@router.get("/options", response_model=OptionsOut)
async def plugin_options(settings: SettingsDep) -> OptionsOut:
    return OptionsOut(images=settings.sandbox_images)


@router.get("", response_model=list[PluginOut])
async def list_plugins(session: SessionDep) -> list[PluginOut]:
    return [_out(row) for row in await registry.all_rows(session)]


@router.get("/{plugin_id}", response_model=PluginOut)
async def get_plugin(plugin_id: str, session: SessionDep) -> PluginOut:
    try:
        return _out(await registry.get(session, plugin_id))
    except registry.PluginError as exc:
        raise _refused(exc) from None


@router.post("", response_model=PluginOut, status_code=status.HTTP_201_CREATED)
async def add_plugin(body: PluginIn, session: SessionDep, settings: SettingsDep) -> PluginOut:
    try:
        row = await registry.add(
            session,
            plugin_id=body.id,
            name=body.name,
            description=body.description,
            config=body.config,
            allowed_images=settings.sandbox_images,
        )
    except registry.PluginError as exc:
        raise _refused(exc) from None
    return _out(row)


@router.put("/{plugin_id}", response_model=PluginOut)
async def edit_plugin(
    plugin_id: str, body: PluginEditIn, session: SessionDep, settings: SettingsDep
) -> PluginOut:
    try:
        row = await registry.update(
            session,
            plugin_id,
            name=body.name,
            description=body.description,
            config=body.config,
            allowed_images=settings.sandbox_images,
        )
    except registry.PluginError as exc:
        raise _refused(exc) from None
    return _out(row)


@router.post("/{plugin_id}/approve", response_model=PluginOut)
async def approve_plugin(plugin_id: str, body: ApproveIn, session: SessionDep) -> PluginOut:
    try:
        return _out(await registry.approve(session, plugin_id, body.permissions))
    except registry.PluginError as exc:
        raise _refused(exc) from None


@router.post("/{plugin_id}/enable", response_model=PluginOut)
async def enable_plugin(plugin_id: str, session: SessionDep) -> PluginOut:
    try:
        return _out(await registry.set_enabled(session, plugin_id, True))
    except registry.PluginError as exc:
        raise _refused(exc) from None


@router.post("/{plugin_id}/disable", response_model=PluginOut)
async def disable_plugin(plugin_id: str, session: SessionDep) -> PluginOut:
    try:
        return _out(await registry.set_enabled(session, plugin_id, False))
    except registry.PluginError as exc:
        raise _refused(exc) from None


@router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plugin(plugin_id: str, session: SessionDep) -> Response:
    try:
        await registry.remove(session, plugin_id)
    except registry.PluginError as exc:
        raise _refused(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
