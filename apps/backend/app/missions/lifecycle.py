"""What happens to a mission once it has run: review, apply, revert, keep, discard, and
restore a checkpoint (PRD §8.8). The user's project changes only in `apply_mission` and
`revert_mission`, both explicit user actions."""

import uuid
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Checkpoint,
    FeatureRow,
    HandoffRow,
    Milestone,
    Mission,
    Need,
    Project,
    Run,
)
from app.events.log import EventType, append_event
from app.missions import apply as applying
from app.missions import service
from app.missions.apply import Refused
from app.orchestration.services import Services
from app.workspace import git

REVIEWABLE = ("completed", "kept")
DISCARDABLE = (
    "awaiting_approval",
    "paused",
    "needs_user",
    "completed",
    "kept",
    "cancelled",
    "failed",
    "applied",
)
RESTORABLE = ("paused", "needs_user", "completed", "kept", "failed")


class Context:
    """A mission with its run and project, loaded in one transaction."""

    def __init__(self, mission: Mission, run: Run, project: Project) -> None:
        self.mission, self.run, self.project = mission, run, project
        self.workspace = Path(project.workspace_path)

    @property
    def worktree(self) -> Path:
        if not self.run.worktree_path:
            raise Refused(
                "the mission's working copy was cleaned up after it was applied; to build it "
                "again, start a new mission"
            )
        return Path(self.run.worktree_path)

    @property
    def base(self) -> str:
        if not self.run.base_commit:
            raise Refused("the mission has no starting snapshot")
        return self.run.base_commit


async def _load(session: AsyncSession, mission_id: uuid.UUID, *, lock: bool = False) -> Context:
    query = select(Mission).where(Mission.id == mission_id)
    mission = await session.scalar(query.with_for_update() if lock else query)
    if mission is None:
        raise Refused("mission not found", 404)
    run = await session.get(Run, mission.run_id)
    project = await session.get(Project, mission.project_id)
    assert run is not None and project is not None
    return Context(mission, run, project)


def _require(ctx: Context, services: Services, allowed: tuple[str, ...], action: str) -> None:
    if services.mission_active(ctx.mission.id):
        raise Refused("the mission is still finishing its current step; try again")
    if ctx.mission.status not in allowed:
        raise Refused(f"a {ctx.mission.status} mission cannot be {action}")


async def mission_diff(services: Services, mission_id: uuid.UUID) -> tuple[Context, list[dict]]:
    """The proposed changes: each file at the starting snapshot and in the mission worktree."""
    async with services.sessionmaker() as session:
        ctx = await _load(session, mission_id)

    record = ctx.mission.apply_record or {}
    applied_commit = record.get("commit") if record.get("state") == "applied" else None

    def read() -> list[dict]:
        files = []
        if not ctx.run.worktree_path and applied_commit:
            # Applied and cleaned up: the changes are the apply commit in the user's project.
            changes = git.diff_commits(ctx.workspace, ctx.base, applied_commit)
        else:
            changes = git.diff(ctx.worktree, ctx.base)
        for change in changes:
            original = git.show_file(ctx.workspace, ctx.base, change.path)
            if not ctx.run.worktree_path and applied_commit:
                modified = git.show_file(ctx.workspace, applied_commit, change.path)
            else:
                target = ctx.worktree / change.path
                modified = (
                    target.read_text(encoding="utf-8", errors="replace")
                    if target.is_file()
                    else None
                )
            files.append(
                {
                    "path": change.path,
                    "change_type": change.change_type,
                    "status": "applied"
                    if (ctx.mission.apply_record or {}).get("state") == "applied"
                    else "pending",
                    "original": original,
                    "modified": modified,
                    "diff": change.diff,
                }
            )
        return files

    return ctx, await run_in_threadpool(read)


async def apply_mission(
    services: Services,
    mission_id: uuid.UUID,
    *,
    include_mission_files: bool | None = None,
    commit: bool = True,
) -> None:
    include = (
        services.settings.apply_mission_files
        if include_mission_files is None
        else include_mission_files
    )
    # The row lock makes a double click safe: the second request waits, then sees "applied".
    async with services.sessionmaker.begin() as session:
        ctx = await _load(session, mission_id, lock=True)
        _require(ctx, services, REVIEWABLE, "applied")
        earlier = ctx.mission.apply_record or {}
        source, temporary = None, None
        if (
            not ctx.run.worktree_path
            and earlier.get("state") == "reverted"
            and earlier.get("commit")
        ):
            # Applied, cleaned up, then reverted: the work lives on in the apply commit.
            temporary = services.settings.data_dir / "worktrees" / f"{ctx.run.id}-reapply"
            source = await run_in_threadpool(
                git.checkout_commit, ctx.workspace, earlier["commit"], temporary
            )
        try:
            record = await run_in_threadpool(
                applying.apply_changes,
                ctx.workspace,
                source or ctx.worktree,
                ctx.base,
                include_mission_files=include,
                commit=commit,
                message=f"H.E.X Mind: {ctx.mission.title}",
            )
        finally:
            if temporary is not None:
                await run_in_threadpool(git.remove_worktree, ctx.workspace, temporary)
        await service.change_status(
            session, ctx.mission, "applied", reason="applied to your project"
        )
        ctx.mission.apply_record = record
        ctx.run.pre_apply_commit = record["pre_apply_commit"]
        if record.get("commit") and ctx.run.worktree_path:
            # The work is now a commit in the user's project: the working copy and its branch
            # are no longer needed (Revert uses the apply record; review reads the commit).
            await run_in_threadpool(git.remove_worktree, ctx.workspace, ctx.worktree)
            await run_in_threadpool(git.delete_branch, ctx.workspace, ctx.mission.branch)
            ctx.run.worktree_path = None


async def revert_mission(services: Services, mission_id: uuid.UUID) -> None:
    async with services.sessionmaker.begin() as session:
        ctx = await _load(session, mission_id, lock=True)
        _require(ctx, services, ("applied",), "reverted")
        record = await run_in_threadpool(
            applying.revert_changes,
            ctx.workspace,
            ctx.mission.apply_record or {},
            message=f"Revert H.E.X Mind: {ctx.mission.title}",
        )
        await service.change_status(
            session, ctx.mission, "completed", reason="reverted in your project"
        )
        ctx.mission.apply_record = record


async def keep_mission(services: Services, mission_id: uuid.UUID) -> None:
    """Leave the result in its worktree to decide later."""
    async with services.sessionmaker.begin() as session:
        ctx = await _load(session, mission_id, lock=True)
        _require(ctx, services, ("completed",), "kept")
        await service.change_status(session, ctx.mission, "kept", reason="kept for later")


async def discard_mission(services: Services, mission_id: uuid.UUID) -> None:
    """Throw the mission's worktree and branch away. An applied mission can still be
    reverted afterwards: revert needs only the apply record and the pre-apply snapshot."""
    async with services.sessionmaker.begin() as session:
        ctx = await _load(session, mission_id, lock=True)
        _require(ctx, services, DISCARDABLE, "discarded")
        if ctx.run.worktree_path:
            await run_in_threadpool(git.remove_worktree, ctx.workspace, Path(ctx.run.worktree_path))
        await run_in_threadpool(git.delete_branch, ctx.workspace, ctx.mission.branch)
        ctx.run.worktree_path = None
        previous = ctx.mission.status
        await service.change_status(session, ctx.mission, "discarded", reason="discarded")
        if ctx.mission.finished_at is None:
            ctx.mission.finished_at = func.clock_timestamp()
        if ctx.run.status in ("queued", "running", "paused"):
            ctx.run.status = "cancelled"
            await append_event(
                session,
                ctx.run.id,
                EventType.RUN_CANCELLED,
                payload={"reason": f"discarded while {previous}"},
            )
        await session.execute(
            Need.__table__.update()
            .where(Need.mission_id == mission_id, Need.status == "open")
            .values(status="answered", answer={"action": "discarded"})
        )


async def list_checkpoints(services: Services, mission_id: uuid.UUID) -> list[Checkpoint]:
    async with services.sessionmaker() as session:
        await _load(session, mission_id)
        return list(
            await session.scalars(
                select(Checkpoint)
                .where(Checkpoint.mission_id == mission_id)
                .order_by(Checkpoint.created_at)
            )
        )


async def restore_checkpoint(services: Services, mission_id: uuid.UUID, commit: str) -> None:
    """Reset the mission branch to a feature's checkpoint and rewind the plan to match: later
    features start over, their handoffs and checkpoints are dropped, and the mission is paused
    so the user can resume from there."""
    async with services.sessionmaker.begin() as session:
        ctx = await _load(session, mission_id, lock=True)
        _require(ctx, services, RESTORABLE, "restored")
        target = await session.scalar(
            select(Checkpoint).where(
                Checkpoint.mission_id == mission_id, Checkpoint.commit == commit
            )
        )
        feature = (
            await session.get(FeatureRow, target.feature_id)
            if target and target.feature_id
            else None
        )
        if target is None or feature is None:
            raise Refused("only a feature's checkpoint can be restored", 404)

        await run_in_threadpool(git.reset_to, ctx.worktree, commit)

        later = list(
            await session.scalars(
                select(FeatureRow).where(
                    FeatureRow.mission_id == mission_id, FeatureRow.position > feature.position
                )
            )
        )
        later_ids = [f.id for f in later]
        for row in later:
            row.attempts, row.commit = 0, None
            await service.set_feature(session, ctx.mission, row, "pending")
        if later_ids:
            await session.execute(delete(HandoffRow).where(HandoffRow.feature_id.in_(later_ids)))
        await session.execute(
            delete(Checkpoint).where(
                Checkpoint.mission_id == mission_id,
                (Checkpoint.feature_id.in_(later_ids)) | (Checkpoint.feature_id.is_(None)),
            )
        )
        await session.execute(
            Need.__table__.update()
            .where(Need.mission_id == mission_id, Need.status == "open")
            .values(status="answered", answer={"action": "restored_checkpoint"})
        )
        await session.flush()
        await _recompute_milestones(session, ctx.mission)

        ctx.mission.finished_at = None
        await service.change_status(
            session, ctx.mission, "paused", reason="restored to a checkpoint"
        )
        ctx.mission.apply_record = None
        previous_run = ctx.run.status
        ctx.run.status, ctx.run.finished_at = "paused", None
        await append_event(
            session,
            ctx.run.id,
            EventType.RUN_STATUS_CHANGED,
            payload={"status": "paused", "previous": previous_run, "stub": False},
        )
        await session.flush()
        await service.sync_mission_folder(session, ctx.mission, ctx.worktree)


async def _recompute_milestones(session: AsyncSession, mission: Mission) -> None:
    milestones = list(
        await session.scalars(
            select(Milestone).where(Milestone.mission_id == mission.id).order_by(Milestone.position)
        )
    )
    for milestone in milestones:
        statuses = list(
            await session.scalars(
                select(FeatureRow.status).where(FeatureRow.milestone_id == milestone.id)
            )
        )
        finished = [s in ("done", "skipped") for s in statuses]
        await service.set_milestone(
            session,
            mission,
            milestone,
            "completed" if all(finished) else "active" if any(finished) else "pending",
        )
