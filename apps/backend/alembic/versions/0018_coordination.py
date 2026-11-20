"""coordination backend per mission

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-20 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("missions", "scoping_sessions"):
        op.add_column(
            table,
            sa.Column(
                "coordination",
                sa.String(length=16),
                server_default="blackboard",
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in ("scoping_sessions", "missions"):
        op.drop_column(table, "coordination")
