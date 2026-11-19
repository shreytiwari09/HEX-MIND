"""Routes: which models a persona's calls go to (PRD §10.4, §10.6).

A route is an ordered list of targets. The router tries the first; if it cannot serve the call
(every key of its connection is cooling down, or the provider fails) it falls back to the next.
A `Route` on the `CallContext` replaces the global provider order for that call.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    connection_id: uuid.UUID
    model: str


@dataclass(frozen=True)
class Route:
    targets: tuple[Target, ...]
    persona_id: str | None = None

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("a route needs at least one target")
