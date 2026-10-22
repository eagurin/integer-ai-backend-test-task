"""Read task state and ordered provider attempt history."""

from typing import final
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.generation import (
    ProviderOutcome,
    TaskHistoryEntry,
    TaskStatus,
    TaskStatusResponse,
)
from app.models.generation_attempt import GenerationAttempt
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.generation_catalog_repository import (
    GenerationCatalogRepository,
)
from app.repositories.task_repository import TaskRepository


@final
class TaskStatusService:
    """Build the public task status view from persisted task history."""

    def __init__(self) -> None:
        self.catalog = GenerationCatalogRepository()
        self.attempts = AttemptRepository()
        self.tasks = TaskRepository()

    async def status(self, session: AsyncSession, task_id: UUID) -> TaskStatusResponse:
        """Return stored task state and provider attempt history."""
        task = await self.tasks.get(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        current_leg = (
            await self.catalog.get_leg(session, task.current_provider_leg_id)
            if task.current_provider_leg_id is not None
            else None
        )
        attempts = await self.attempts.for_task_with_providers(session, task_id)
        history = [
            TaskHistoryEntry(
                provider=provider_name,
                outcome=self._outcome(attempt),
                error=attempt.error_type,
                created_at=attempt.created_at,
            )
            for attempt, provider_name in attempts
        ]
        return TaskStatusResponse(
            task_id=task.id,
            status=TaskStatus(task.status),
            current_provider=current_leg.provider_name if current_leg else None,
            output=task.result_url,
            history=history,
        )

    @staticmethod
    def _outcome(attempt: GenerationAttempt) -> ProviderOutcome | None:
        if attempt.status == "succeeded":
            return ProviderOutcome.COMPLETED
        if attempt.error_type is not None:
            try:
                return ProviderOutcome(attempt.error_type)
            except ValueError:
                pass
        if attempt.status in {"failed", "timed_out"}:
            return ProviderOutcome.TECHNICAL_ERROR
        return None
