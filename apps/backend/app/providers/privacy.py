"""Privacy modes per project (PRD §13.5): which providers may see a project's prompts.

  any      every connection (the default)
  trusted  local models, plus the connections the user listed for this project
  local    local models only (Ollama, LM Studio): nothing leaves the machine

What leaves the machine is only the prompt of each model call. This is enforced where calls are
made (the route executor and the policy chain), per run, and **fails closed**: a connection
that is not allowed is skipped with the reason, and when nothing on a route is allowed the call
fails saying so; it is never sent anyway. A call that belongs to no run (connection tests, model
discovery) carries none of a project's content and is not restricted.
"""

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Project, Run

PrivacyMode = Literal["any", "trusted", "local"]
MODES: tuple[PrivacyMode, ...] = ("any", "trusted", "local")
# The policy-chain providers read from .env that run on this machine.
LOCAL_LEGACY_PROVIDERS = frozenset({"ollama"})


@dataclass(frozen=True)
class Privacy:
    mode: PrivacyMode = "any"
    trusted: frozenset[str] = field(default_factory=frozenset)  # connection ids

    def allows_connection(self, connection_id: uuid.UUID, *, local: bool) -> bool:
        if self.mode == "any" or local:
            return True
        return self.mode == "trusted" and str(connection_id) in self.trusted

    def allows_legacy(self, provider: str) -> bool:
        return self.mode == "any" or provider in LOCAL_LEGACY_PROVIDERS

    def why_blocked(self) -> str:
        return {
            "local": "blocked by this project's privacy mode (local models only)",
            "trusted": "blocked by this project's privacy mode (only trusted providers)",
        }.get(self.mode, "blocked")


ANY = Privacy()


async def privacy_for(
    sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID | None
) -> Privacy:
    """The privacy of the project a run belongs to; `any` when there is no run."""
    if run_id is None:
        return ANY
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(Project.privacy_mode, Project.trusted_connections)
                .join(Run, Run.project_id == Project.id)
                .where(Run.id == run_id)
            )
        ).one_or_none()
    if row is None:
        return ANY
    mode, trusted = row
    if mode not in MODES:  # an unknown value is never read as permissive
        return Privacy("local")
    return Privacy(mode, frozenset(str(t) for t in trusted or []))
