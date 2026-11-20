"""experiment trials on eval_runs

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-20 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_tasks",
        sa.Column("kind", sa.String(length=8), server_default="feature", nullable=False),
    )
    op.add_column("eval_runs", sa.Column("experiment", sa.String(length=8), nullable=True))
    op.add_column("eval_runs", sa.Column("condition", sa.String(length=64), nullable=True))
    op.add_column(
        "eval_runs", sa.Column("repeat", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column("eval_runs", sa.Column("benchmark_version", sa.String(length=16), nullable=True))
    op.add_column("eval_runs", sa.Column("mission_id", sa.Uuid(), nullable=True))
    op.add_column("eval_runs", sa.Column("status", sa.String(length=16), nullable=True))
    op.add_column(
        "eval_runs", sa.Column("passed", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        "eval_runs", sa.Column("needs_you", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "eval_runs", sa.Column("escalations", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("eval_runs", sa.Column("tokens_in", sa.Integer(), nullable=True))
    op.add_column("eval_runs", sa.Column("tokens_out", sa.Integer(), nullable=True))
    op.add_column("eval_runs", sa.Column("error", sa.Text(), nullable=True))
    op.create_index(op.f("ix_eval_runs_experiment"), "eval_runs", ["experiment"], unique=False)
    op.create_index(op.f("ix_eval_runs_mission_id"), "eval_runs", ["mission_id"], unique=False)
    op.create_foreign_key(
        "eval_runs_mission_id_fkey", "eval_runs", "missions", ["mission_id"], ["id"],
        ondelete="SET NULL",
    )  # fmt: skip


def downgrade() -> None:
    op.drop_constraint("eval_runs_mission_id_fkey", "eval_runs", type_="foreignkey")
    op.drop_index(op.f("ix_eval_runs_mission_id"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_experiment"), table_name="eval_runs")
    for column in (
        "error", "tokens_out", "tokens_in", "escalations", "needs_you", "passed", "status",
        "mission_id", "benchmark_version", "config", "repeat", "condition", "experiment",
    ):  # fmt: skip
        op.drop_column("eval_runs", column)
    op.drop_column("eval_tasks", "kind")
