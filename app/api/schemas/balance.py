"""User balance response schemas."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.api.schemas.common import ApiSchema


class LedgerEntryResponse(ApiSchema):
    """One balance movement returned in recent history."""

    operation: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    delta: int
    created_at: datetime


class BalanceResponse(ApiSchema):
    """Ledger-derived user token balance."""

    user_id: UUID
    balance: Annotated[int, Field(ge=0)]
    history: list[LedgerEntryResponse] = Field(max_length=20)
