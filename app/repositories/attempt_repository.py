"""Provider attempt history persistence queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_attempt import GenerationAttempt


class AttemptRepository:
    """Stores numbered provider attempts and returns task history."""

    async def add(
        self, session: AsyncSession, attempt: GenerationAttempt
    ) -> GenerationAttempt:
        """Add and flush an attempt without committing the caller's transaction."""
        session.add(attempt)
        await session.flush()
        return attempt

    async def for_task(
        self, session: AsyncSession, task_id: UUID
    ) -> list[GenerationAttempt]:
        """Return task attempts in ascending attempt order."""
        result = await session.execute(
            select(GenerationAttempt)
            .where(GenerationAttempt.task_id == task_id)
            .order_by(GenerationAttempt.attempt_no)
        )
        return list(result.scalars())
