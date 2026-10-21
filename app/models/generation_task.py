"""Generation task state."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GenerationTask(Base):
    """Durable task record; status and ledger remain separate concerns."""

    __tablename__ = "generation_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="valid_status",
        ),
        Index(
            "ix_generation_tasks_active_user",
            "user_id",
            postgresql_where=text("status IN ('queued', 'processing')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    generation_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("generation_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    current_provider_leg_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("provider_legs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    current_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "generation_attempts.id",
            name="fk_generation_tasks_current_attempt_id_generation_attempts",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    result_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
