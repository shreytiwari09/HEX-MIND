"""The plugin registry (PRD §11.7): add, approve, enable and attach plugins.

Nothing here runs a plugin; `plugins/runtime.py` does, and only for plugins that are `ready`:
enabled, and (when the configuration is risky) approved for exactly this configuration.
"""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.persona import all_personas
from app.db.models import PluginRow
from app.plugins.config import (
    PluginConfig,
    PluginConfigError,
    approval_reasons,
    check_allowed,
    config_hash,
    permissions,
    valid_id,
)

Status = Literal["disabled", "needs_approval", "ready"]
MAX_NAME = 80
MAX_DESCRIPTION = 300


class PluginError(ValueError):
    """The change is not allowed; `status_code` suits an HTTP answer."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def config_of(row: PluginRow) -> PluginConfig:
    return PluginConfig.model_validate(row.config)


def status_of(row: PluginRow) -> Status:
    """`ready` means it may be started for the personas it is attached to."""
    config = config_of(row)
    if approval_reasons(config) and row.approved_hash != config_hash(config):
        return "needs_approval"
    return "ready" if row.enabled else "disabled"


def personas_with(plugin_id: str) -> list[str]:
    return sorted(p.id for p in all_personas().values() if plugin_id in p.plugins)


async def get(session: AsyncSession, plugin_id: str) -> PluginRow:
    row = await session.get(PluginRow, plugin_id)
    if row is None:
        raise PluginError("plugin not found", 404)
    return row


async def all_rows(session: AsyncSession) -> list[PluginRow]:
    return list(await session.scalars(select(PluginRow).order_by(PluginRow.id)))


def _validated(raw: dict[str, object], allowed_images: list[str]) -> PluginConfig:
    try:
        config = PluginConfig.model_validate(raw)
        check_allowed(config, allowed_images)
    except PluginConfigError as exc:
        raise PluginError(str(exc)) from None
    except ValueError as exc:  # a pydantic ValidationError
        errors = getattr(exc, "errors", lambda: [])()
        parts = []
        for error in errors[:3]:
            message = str(error.get("msg", ""))
            if message.startswith("Value error, "):  # our own rules already say what is wrong
                parts.append(message.removeprefix("Value error, "))
            else:
                field = ".".join(str(part) for part in error.get("loc", ()))
                parts.append(f"{field}: {message}" if field else message)
        raise PluginError("; ".join(parts) or str(exc)) from None
    return config


def _check_text(name: str, description: str) -> None:
    if not 2 <= len(name.strip()) <= MAX_NAME:
        raise PluginError(f"the name must be 2 to {MAX_NAME} characters")
    if len(description) > MAX_DESCRIPTION:
        raise PluginError(f"the description is longer than {MAX_DESCRIPTION} characters")


async def add(
    session: AsyncSession,
    *,
    plugin_id: str,
    name: str,
    description: str,
    config: dict[str, object],
    allowed_images: list[str],
) -> PluginRow:
    """A new plugin. It starts disabled; a risky one also starts unapproved."""
    if not valid_id(plugin_id):
        raise PluginError("the id must be lowercase letters, digits and '-' (2 to 32)")
    if await session.get(PluginRow, plugin_id) is not None:
        raise PluginError(f"a plugin '{plugin_id}' already exists", 409)
    _check_text(name, description)
    validated = _validated(config, allowed_images)
    row = PluginRow(
        id=plugin_id,
        name=name.strip(),
        description=description.strip(),
        config=validated.model_dump(),
        enabled=False,
    )
    session.add(row)
    await session.flush()
    return row


async def update(
    session: AsyncSession,
    plugin_id: str,
    *,
    name: str | None,
    description: str | None,
    config: dict[str, object] | None,
    allowed_images: list[str],
) -> PluginRow:
    """Edit a plugin. Changing what it can do removes its approval and disables it."""
    row = await get(session, plugin_id)
    _check_text(name if name is not None else row.name, description or "")
    if name is not None:
        row.name = name.strip()
    if description is not None:
        row.description = description.strip()
    if config is not None:
        validated = _validated(config, allowed_images)
        if config_hash(validated) != config_hash(config_of(row)):
            row.config = validated.model_dump()
            row.approved_hash = None
            row.approved_at = None
            row.approved_labels = []
            row.enabled = False  # it must be enabled again, and approved again if it is risky
    await session.flush()
    return row


async def approve(session: AsyncSession, plugin_id: str, labels: list[str]) -> PluginRow:
    """The user approves this plugin's current configuration. They send the labels they were
    shown; if the plugin's permissions are not exactly those, the approval is refused (they
    approved something else)."""
    row = await get(session, plugin_id)
    config = config_of(row)
    if not approval_reasons(config):
        raise PluginError("this plugin does not need approval", 409)
    if sorted(labels) != sorted(permissions(config)):
        raise PluginError("its permissions are not the ones you were shown: review them again", 409)
    row.approved_hash = config_hash(config)
    row.approved_at = datetime.now(UTC)
    row.approved_labels = list(permissions(config))
    await session.flush()
    return row


async def set_enabled(session: AsyncSession, plugin_id: str, enabled: bool) -> PluginRow:
    row = await get(session, plugin_id)
    if enabled and status_of(row) == "needs_approval":
        reasons = "; ".join(approval_reasons(config_of(row)))
        raise PluginError(f"it needs your approval first: {reasons}", 409)
    row.enabled = enabled
    await session.flush()
    return row


async def remove(session: AsyncSession, plugin_id: str) -> None:
    row = await get(session, plugin_id)
    attached = personas_with(plugin_id)
    if attached:
        raise PluginError(f"it is still attached to: {', '.join(attached)}; detach it first", 409)
    await session.delete(row)
    await session.flush()


async def ready_for(session: AsyncSession, plugin_ids: list[str]) -> list[PluginRow]:
    """The plugins among `plugin_ids` that may run now, in the order given. A plugin that is
    missing, disabled, or risky and unapproved is never started."""
    rows = {row.id: row for row in await all_rows(session)}
    return [
        rows[i] for i in dict.fromkeys(plugin_ids) if i in rows and status_of(rows[i]) == "ready"
    ]


async def known_ids(session: AsyncSession) -> set[str]:
    return {row.id for row in await all_rows(session)}
