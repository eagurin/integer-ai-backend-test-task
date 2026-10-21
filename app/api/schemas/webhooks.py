"""Webhook request schemas."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.api.schemas.common import ApiSchema
from app.api.schemas.generation import ProviderOutcome


class PaymentStatus(StrEnum):
    """Payment lifecycle states."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaymentWebhookRequest(ApiSchema):
    """Signed payment notification payload."""

    payment_id: UUID
    user_id: UUID
    tokens: Annotated[int, Field(gt=0)]
    status: PaymentStatus


class ProviderWebhookRequest(ApiSchema):
    """Signed provider result payload."""

    task_id: UUID
    attempt_no: Annotated[int, Field(gt=0)]
    outcome: ProviderOutcome
    output: str | None = None
    error: Annotated[str | None, StringConstraints(max_length=2_000)] = None
