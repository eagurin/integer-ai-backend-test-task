"""Generation request and task query response schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, HttpUrl, StringConstraints

from app.api.schemas.common import ApiSchema

Prompt = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]
TaskIdentifier = UUID


class TaskStatus(StrEnum):
    """Public generation task states."""

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerateRequest(ApiSchema):
    """Input accepted by POST /generate."""

    user_id: UUID
    model: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    prompt: Prompt
    ref_images: list[HttpUrl] = Field(default_factory=list, max_length=10)


class GenerateResponse(ApiSchema):
    """Accepted asynchronous generation response."""

    task_id: TaskIdentifier


class ProviderOutcome(StrEnum):
    """Accepted provider callback outcomes."""

    COMPLETED = "completed"
    TECHNICAL_ERROR = "technical_error"
    MODERATION = "moderation"
    PAYLOAD = "payload"


class TaskHistoryEntry(ApiSchema):
    """One provider attempt exposed in task history."""

    provider: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    outcome: ProviderOutcome | None
    error: str | None
    created_at: datetime


class TaskStatusResponse(ApiSchema):
    """Current state and attempt history for a generation."""

    task_id: TaskIdentifier
    status: TaskStatus
    current_provider: str | None
    output: str | None
    history: list[TaskHistoryEntry]
