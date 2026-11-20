"""A plugin is an MCP server attached to chosen personas (PRD §11.7).

A plugin is third-party code, so it is untrusted (CLAUDE.md hard rules). The H.E.X way to run
one is inside the same hardened sandbox as project checks:

  stdio  a command run in an allow-listed image (`docker run -i`: no capabilities, read-only
         root, no secrets, non-root), speaking MCP over stdin/stdout. It can see the mission
         worktree (`mount`: none, read or write) and reach the network only through the
         allowlist proxy (`network: allowlist` with `allow_hosts`), never directly.
  http   a remote MCP server at an https URL. It cannot be sandboxed: it is a network plugin.

**Permission labels are derived from this configuration, never from what the plugin says about
itself**: `runs commands` (any stdio plugin), `reads files` and `writes files` (the mount),
`network` (an allowlist or a remote server). `secrets` is a label H.E.X knows but does not grant:
a plugin that needs a secret is not supported yet, so no configuration asks for one.

Risk: a plugin needs the user's explicit approval when it has `network` (untrusted input plus
outside communication) or `writes files` (third-party code changing the project). A plugin
with neither (no network, no mount or a read-only one) is the low-risk case and needs none.
The approval is bound to the exact configuration: change anything that matters and it is gone.
"""

import hashlib
import ipaddress
import json
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

Transport = Literal["stdio", "http"]
Mount = Literal["none", "read", "write"]
Network = Literal["none", "allowlist"]
Label = Literal["runs commands", "reads files", "writes files", "network", "secrets"]

MAX_HOSTS = 10
_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class PluginConfigError(ValueError):
    """The configuration is not allowed; the message says what to change."""


class PluginConfig(BaseModel):
    """Everything that decides what a plugin can do. Its hash is what an approval is bound to."""

    transport: Transport
    # stdio
    image: str | None = Field(default=None, max_length=200)
    command: str | None = Field(default=None, max_length=500)
    mount: Mount = "none"
    network: Network = "none"
    allow_hosts: list[str] = Field(default_factory=list, max_length=MAX_HOSTS)
    # http
    url: str | None = Field(default=None, max_length=500)

    @field_validator("command")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text or "\n" in text or "\r" in text or "\x00" in text:
            raise ValueError("a command must be one non-empty line")
        return text

    @field_validator("allow_hosts")
    @classmethod
    def _hosts(cls, value: list[str]) -> list[str]:
        hosts = [h.strip().lower() for h in value]
        for host in hosts:
            if not _HOST.match(host):
                raise ValueError(f"'{host}' is not a host name (no scheme, port or wildcard)")
        return list(dict.fromkeys(hosts))

    @model_validator(mode="after")
    def _consistent(self) -> "PluginConfig":
        if self.transport == "stdio":
            if not self.image or not self.command:
                raise ValueError("a stdio plugin needs an image and a command")
            if self.url:
                raise ValueError("a stdio plugin has no url")
            if self.network == "allowlist" and not self.allow_hosts:
                raise ValueError("network access needs the hosts it may reach")
            if self.network == "none" and self.allow_hosts:
                raise ValueError("hosts are only used when network is 'allowlist'")
        else:
            if not self.url:
                raise ValueError("an http plugin needs a url")
            if self.image or self.command or self.mount != "none":
                raise ValueError("an http plugin runs elsewhere: no image, command or mount")
            host = _https_host(self.url)
            # A remote server is a network plugin that can reach exactly one host.
            object.__setattr__(self, "network", "allowlist")
            object.__setattr__(self, "allow_hosts", [host])
        return self


def _https_host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("the url must be https://host/path with no credentials")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host.endswith((".local", ".internal")):
            raise ValueError("the url must point at a public host, not this machine") from None
    else:
        if not address.is_global:
            raise ValueError("the url must point at a public host, not this machine")
    return host


def permissions(config: PluginConfig) -> list[Label]:
    """The labels shown to the user, from the configuration alone."""
    labels: list[Label] = []
    if config.transport == "stdio":
        labels.append("runs commands")
    if config.mount in ("read", "write"):
        labels.append("reads files")
    if config.mount == "write":
        labels.append("writes files")
    if config.network == "allowlist":
        labels.append("network")
    return labels


def approval_reasons(config: PluginConfig) -> list[str]:
    """Why this plugin needs the user's approval; empty for the low-risk case."""
    reasons: list[str] = []
    if config.network == "allowlist":
        hosts = ", ".join(config.allow_hosts)
        reasons.append(f"it can send data to {hosts}")
    if config.mount == "write":
        reasons.append("third-party code can change files in the project")
    return reasons


def config_hash(config: PluginConfig) -> str:
    """Identifies the configuration an approval was given for."""
    canonical = json.dumps(config.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def check_allowed(config: PluginConfig, allowed_images: list[str]) -> None:
    """Rules that depend on this installation, not on the configuration alone."""
    if config.transport == "stdio" and config.image not in allowed_images:
        raise PluginConfigError(
            f"image '{config.image}' is not allowed; allowed: {', '.join(allowed_images)}"
        )


def valid_id(plugin_id: str) -> bool:
    return bool(_ID.match(plugin_id))


class PluginSpec(BaseModel):
    """A plugin ready to run, as the orchestrator hands it to the crew service for one job
    (the crew service has no database). Only plugins that are `ready` are ever sent."""

    id: str
    name: str
    config: PluginConfig
    config_hash: str
