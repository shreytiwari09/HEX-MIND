"""Remove working copies that are no longer needed (PRD D83).

A mission works in its own git worktree under the app's data folder. Once its work is applied
as a commit in the user's project (or the mission is discarded), the worktree and its branch
only take space: Revert uses the apply record, and the review reads the apply commit. Apply
removes them straight away; this sweep at startup clears the ones left by older versions.
"""

import logging
from pathlib import Path

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.db.models import Mission, Project, Run
from app.orchestration.services import Services
from app.workspace import git

logger = logging.getLogger(__name__)


async def clean_finished_worktrees(services: Services) -> int:
    """Remove the worktree and branch of every applied (with a commit) or discarded mission.
    Returns how many were removed."""
    async with services.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Mission, Run, Project)
                .join(Run, Run.id == Mission.run_id)
                .join(Project, Project.id == Mission.project_id)
                .where(Mission.status.in_(("applied", "discarded")), Run.worktree_path.is_not(None))
            )
        ).all()
    removed = 0
    for mission, run, project in rows:
        if mission.status == "applied" and not (mission.apply_record or {}).get("commit"):
            continue  # applied without a commit: the worktree is still the only copy of the history
        if services.mission_active(mission.id):
            continue
        worktree = Path(run.worktree_path or "")
        owned = (services.settings.data_dir / "worktrees").resolve()
        if not run.worktree_path or not worktree.resolve().is_relative_to(owned):
            continue  # never delete anything outside the app's own worktrees folder
        root = Path(project.workspace_path)
        await run_in_threadpool(git.remove_worktree, root, worktree)
        await run_in_threadpool(git.delete_branch, root, mission.branch)
        async with services.sessionmaker.begin() as session:
            fresh = await session.get(Run, run.id)
            if fresh is not None:
                fresh.worktree_path = None
        removed += 1
    if removed:
        logger.info("removed %d working copies of applied or discarded missions", removed)
    return removed
