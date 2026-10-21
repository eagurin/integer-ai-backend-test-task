"""Persist deadlines for unresolved provider attempts.

Revision ID: 0003_provider_attempt_deadlines
Revises: 0002_generation_input
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_provider_attempt_deadlines"
down_revision: str | None = "0002_generation_input"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_attempts",
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE generation_attempts
        SET deadline_at = created_at + INTERVAL '60 seconds'
        WHERE status IN ('queued', 'processing')
        """
    )
    op.create_index(
        "ix_generation_attempts_unresolved_deadline",
        "generation_attempts",
        ["deadline_at"],
        postgresql_where=sa.text(
            "status IN ('queued', 'processing') AND deadline_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generation_attempts_unresolved_deadline",
        table_name="generation_attempts",
    )
    op.drop_column("generation_attempts", "deadline_at")
