"""Provider attempt history persistence queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_attempt import GenerationAttempt
from app.models.generation_model import ProviderLeg


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

    async def for_task_with_providers(
        self, session: AsyncSession, task_id: UUID
    ) -> list[tuple[GenerationAttempt, str]]:
        """Return attempts with provider names in attempt order."""
        result = await session.execute(
            select(GenerationAttempt, ProviderLeg.provider_name)
            .join(ProviderLeg, ProviderLeg.id == GenerationAttempt.provider_leg_id)
            .where(GenerationAttempt.task_id == task_id)
            .order_by(GenerationAttempt.attempt_no)
        )
        return list(result.tuples())

    async def get_for_update(
        self, session: AsyncSession, task_id: UUID, attempt_no: int
    ) -> GenerationAttempt | None:
        """Return and lock one numbered attempt."""
        result = await session.execute(
            select(GenerationAttempt)
            .where(
                GenerationAttempt.task_id == task_id,
                GenerationAttempt.attempt_no == attempt_no,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()
