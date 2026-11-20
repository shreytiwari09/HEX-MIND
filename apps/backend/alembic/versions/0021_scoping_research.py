"""Advanced research on a scoping session

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scoping_sessions",
        sa.Column("research", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "scoping_sessions",
        sa.Column("research_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scoping_sessions", "research_notes")
    op.drop_column("scoping_sessions", "research")
