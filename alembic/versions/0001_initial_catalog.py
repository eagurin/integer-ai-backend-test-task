"""Create the database schema and seed the generation catalog.

Revision ID: 0001_initial_catalog
Revises:
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_catalog"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMAGE_FAST_ID = UUID("08bd2a41-848d-4f48-a385-f8e03d135ea1")
VIDEO_LONG_ID = UUID("111f1030-c64f-41c5-b18c-ce6053edfc4f")
IMAGE_ALPHA_LEG_ID = UUID("f1f1b759-2db3-40e8-9ea4-8ad6fe830802")
IMAGE_BETA_LEG_ID = UUID("cf6bc738-ebaa-4bb0-a2db-539bf1ab5a9e")
VIDEO_BETA_LEG_ID = UUID("c4bb2272-189b-4159-83fd-42c51631cf58")
VIDEO_ALPHA_LEG_ID = UUID("cb0b4d7c-7153-4810-907d-810bcf77a081")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "generation_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("price_tokens", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "price_tokens > 0",
            name="ck_generation_models_positive_price",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generation_models"),
        sa.UniqueConstraint("key", name="uq_generation_models_key"),
    )
    op.create_table(
        "payment_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_payment_identities_valid_status",
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name="ck_payment_identities_positive_token_count",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payment_identities_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_identities"),
        sa.UniqueConstraint("payment_id", name="payment_id"),
    )
    op.create_table(
        "token_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(length=192), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "delta <> 0",
            name="ck_token_ledger_entries_nonzero_delta",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_token_ledger_entries_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_token_ledger_entries"),
        sa.UniqueConstraint("operation_key", name="operation_key"),
    )
    op.create_index(
        "ix_token_ledger_entries_user_created",
        "token_ledger_entries",
        ["user_id", "created_at"],
    )
    op.create_table(
        "provider_legs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_refs", sa.Integer(), nullable=False),
        sa.Column(
            "skip_on_moderation",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_refs > 0",
            name="ck_provider_legs_positive_max_refs",
        ),
        sa.CheckConstraint(
            "priority > 0",
            name="ck_provider_legs_positive_priority",
        ),
        sa.ForeignKeyConstraint(
            ["generation_model_id"],
            ["generation_models.id"],
            name="fk_provider_legs_generation_model_id_generation_models",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_legs"),
        sa.UniqueConstraint("generation_model_id", "priority", name="model_priority"),
    )
    op.create_table(
        "generation_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="queued", nullable=False
        ),
        sa.Column(
            "current_provider_leg_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("current_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="ck_generation_tasks_valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["generation_model_id"],
            ["generation_models.id"],
            name="fk_generation_tasks_generation_model_id_generation_models",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_provider_leg_id"],
            ["provider_legs.id"],
            name="fk_generation_tasks_current_provider_leg_id_provider_legs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_generation_tasks_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generation_tasks"),
    )
    op.create_index(
        "ix_generation_tasks_active_user",
        "generation_tasks",
        ["user_id"],
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
    )
    op.create_table(
        "generation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_leg_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="queued", nullable=False
        ),
        sa.Column("external_id", sa.String(length=256), nullable=True),
        sa.Column("error_type", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_no > 0",
            name="ck_generation_attempts_positive_attempt_no",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed', 'timed_out')",
            name="ck_generation_attempts_valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["provider_leg_id"],
            ["provider_legs.id"],
            name="fk_generation_attempts_provider_leg_id_provider_legs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["generation_tasks.id"],
            name="fk_generation_attempts_task_id_generation_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generation_attempts"),
        sa.UniqueConstraint("task_id", "attempt_no", name="task_attempt_no"),
    )
    op.create_foreign_key(
        "fk_generation_tasks_current_attempt_id_generation_attempts",
        "generation_tasks",
        "generation_attempts",
        ["current_attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        CREATE FUNCTION reject_token_ledger_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'token ledger entries are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER token_ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON token_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_token_ledger_mutation()
        """
    )

    models = sa.table(
        "generation_models",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.String()),
        sa.column("price_tokens", sa.Integer()),
    )
    legs = sa.table(
        "provider_legs",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("generation_model_id", postgresql.UUID(as_uuid=True)),
        sa.column("provider_name", sa.String()),
        sa.column("priority", sa.Integer()),
        sa.column("max_refs", sa.Integer()),
        sa.column("skip_on_moderation", sa.Boolean()),
    )
    op.bulk_insert(
        models,
        [
            {
                "id": IMAGE_FAST_ID,
                "key": "image-fast",
                "price_tokens": 2,
            },
            {
                "id": VIDEO_LONG_ID,
                "key": "video-long",
                "price_tokens": 25,
            },
        ],
    )
    op.bulk_insert(
        legs,
        [
            {
                "id": IMAGE_ALPHA_LEG_ID,
                "generation_model_id": IMAGE_FAST_ID,
                "provider_name": "alpha",
                "priority": 1,
                "max_refs": 4,
                "skip_on_moderation": False,
            },
            {
                "id": IMAGE_BETA_LEG_ID,
                "generation_model_id": IMAGE_FAST_ID,
                "provider_name": "beta",
                "priority": 2,
                "max_refs": 10,
                "skip_on_moderation": False,
            },
            {
                "id": VIDEO_BETA_LEG_ID,
                "generation_model_id": VIDEO_LONG_ID,
                "provider_name": "beta",
                "priority": 1,
                "max_refs": 2,
                "skip_on_moderation": False,
            },
            {
                "id": VIDEO_ALPHA_LEG_ID,
                "generation_model_id": VIDEO_LONG_ID,
                "provider_name": "alpha",
                "priority": 2,
                "max_refs": 1,
                "skip_on_moderation": True,
            },
        ],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER token_ledger_entries_immutable ON token_ledger_entries")
    op.execute("DROP FUNCTION reject_token_ledger_mutation()")
    op.drop_constraint(
        "fk_generation_tasks_current_attempt_id_generation_attempts",
        "generation_tasks",
        type_="foreignkey",
    )
    op.drop_index("ix_generation_tasks_active_user", table_name="generation_tasks")
    op.drop_index(
        "ix_token_ledger_entries_user_created", table_name="token_ledger_entries"
    )
    op.drop_table("generation_attempts")
    op.drop_table("generation_tasks")
    op.drop_table("provider_legs")
    op.drop_table("token_ledger_entries")
    op.drop_table("payment_identities")
    op.drop_table("generation_models")
    op.drop_table("users")
