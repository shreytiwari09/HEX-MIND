"""Resume after a restart (PRD §18.1, P7).

A mission's runner lives inside the backend process. If the backend stops (a crash, a restart,
the laptop closing), a mission that was `running` has no runner any more, and nothing would ever
move it. At startup every such mission is **paused**, with the reason recorded in its event log,
and the user resumes it when they choose: it is never resumed on its own, because that would
spend money without anyone asking. Resuming starts from the last checkpoint (the work that was in
flight is discarded and its feature starts again), which the runner already does.

Missions waiting for the user (`needs_user`, `awaiting_approval`, `paused`) need nothing: their
state is all in the database.
"""

import logging

from sqlalchemy import select

from app.db.models import Mission
from app.missions import service
from app.orchestration.services import Services

logger = logging.getLogger(__name__)
REASON = (
    "the backend stopped while this mission was running; "
    "resume to continue from the last checkpoint"
)


async def pause_interrupted_missions(services: Services) -> int:
    """Pause every `running` mission that has no runner. Returns how many were paused."""
    async with services.sessionmaker() as session:
        running = list(await session.scalars(select(Mission.id).where(Mission.status == "running")))
    paused = 0
    for mission_id in running:
        if services.mission_active(mission_id):
            continue  # a runner is alive in this process: not interrupted
        async with services.sessionmaker.begin() as session:
            if await service.set_status(
                session, mission_id, "paused", only_from=("running",), reason=REASON
            ):
                paused += 1
    if paused:
        logger.warning("paused %d mission(s) that were running when the backend stopped", paused)
    return paused
