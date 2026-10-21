"""Persist generation input for provider failover.

Revision ID: 0002_generation_input
Revises: 0001_initial_catalog
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_generation_input"
down_revision: str | None = "0001_initial_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("prompt", sa.String(length=10000), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("ref_images", postgresql.JSONB(), nullable=True),
    )
    op.execute("UPDATE generation_tasks SET prompt = '', ref_images = '[]'::jsonb")
    op.alter_column("generation_tasks", "prompt", nullable=False)
    op.alter_column("generation_tasks", "ref_images", nullable=False)


def downgrade() -> None:
    op.drop_column("generation_tasks", "ref_images")
    op.drop_column("generation_tasks", "prompt")
