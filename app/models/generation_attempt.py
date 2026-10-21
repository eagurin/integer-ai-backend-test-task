"""Provider attempt history."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GenerationAttempt(Base):
    """A numbered provider attempt belonging to one generation task."""

    __tablename__ = "generation_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="task_attempt_no"),
        CheckConstraint("attempt_no > 0", name="positive_attempt_no"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed', 'timed_out')",
            name="valid_status",
        ),
        Index(
            "ix_generation_attempts_unresolved_deadline",
            "deadline_at",
            postgresql_where=text(
                "status IN ('queued', 'processing') AND deadline_at IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("generation_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_leg_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("provider_legs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
