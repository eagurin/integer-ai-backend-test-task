"""Append-only token ledger entries."""

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
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TokenLedgerEntry(Base):
    """Immutable token delta; account balances are sums of these rows."""

    __tablename__ = "token_ledger_entries"
    __table_args__ = (
        UniqueConstraint("operation_key", name="operation_key"),
        CheckConstraint("delta <> 0", name="nonzero_delta"),
        Index("ix_token_ledger_entries_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_key: Mapped[str] = mapped_column(String(192), nullable=False)
    delta: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
