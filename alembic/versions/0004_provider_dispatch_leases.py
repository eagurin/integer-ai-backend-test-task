"""Persist ownership and bounded expiry for provider HTTP dispatch.

Revision ID: 0004_provider_dispatch_leases
Revises: 0003_provider_attempt_deadlines
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_provider_dispatch_leases"
down_revision: str | None = "0003_provider_attempt_deadlines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_attempts",
        sa.Column("dispatch_lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "generation_attempts",
        sa.Column(
            "dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_check_constraint(
        "dispatch_lease_owner_matches_expiry",
        "generation_attempts",
        "(dispatch_lease_token IS NULL) = (dispatch_lease_expires_at IS NULL)",
    )
    op.create_index(
        "ix_generation_attempts_queued_dispatch_lease",
        "generation_attempts",
        ["dispatch_lease_expires_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generation_attempts_queued_dispatch_lease",
        table_name="generation_attempts",
    )
    op.drop_constraint(
        "dispatch_lease_owner_matches_expiry",
        "generation_attempts",
        type_="check",
    )
    op.drop_column("generation_attempts", "dispatch_lease_expires_at")
    op.drop_column("generation_attempts", "dispatch_lease_token")
