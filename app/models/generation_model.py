"""Generation model catalog and ordered provider legs."""

from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GenerationModel(Base):
    """A public generation model with its token price."""

    __tablename__ = "generation_models"
    __table_args__ = (CheckConstraint("price_tokens > 0", name="positive_price"),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    price_tokens: Mapped[int] = mapped_column(nullable=False)


class ProviderLeg(Base):
    """One provider's ordered and reference-limited model route."""

    __tablename__ = "provider_legs"
    __table_args__ = (
        UniqueConstraint("generation_model_id", "priority", name="model_priority"),
        CheckConstraint("priority > 0", name="positive_priority"),
        CheckConstraint("max_refs > 0", name="positive_max_refs"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    generation_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("generation_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    max_refs: Mapped[int] = mapped_column(Integer, nullable=False)
    skip_on_moderation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
