"""Generation task persistence queries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask


class TaskRepository:
    """Queries tasks and counts active work within the caller's transaction."""

    async def get(self, session: AsyncSession, task_id: UUID) -> GenerationTask | None:
        """Return a task by id."""
        return await session.get(GenerationTask, task_id)

    async def get_for_update(
        self, session: AsyncSession, task_id: UUID
    ) -> GenerationTask | None:
        """Return and lock a task row before updating its accepted state."""
        result = await session.execute(
            select(GenerationTask).where(GenerationTask.id == task_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def add(self, session: AsyncSession, task: GenerationTask) -> GenerationTask:
        """Add and flush a task without committing the caller's transaction."""
        session.add(task)
        await session.flush()
        return task

    async def count_active(self, session: AsyncSession, user_id: UUID) -> int:
        """Count queued and processing tasks for one user."""
        result = await session.execute(
            select(func.count())
            .select_from(GenerationTask)
            .where(
                GenerationTask.user_id == user_id,
                GenerationTask.status.in_(("queued", "processing")),
            )
        )
        return int(result.scalar_one())

    async def due_for_watchdog(
        self,
        session: AsyncSession,
        now: datetime,
        batch_size: int,
    ) -> list[GenerationTask]:
        """Claim due tasks while skipping tasks locked by other workers."""
        result = await session.scalars(
            select(GenerationTask)
            .join(
                GenerationAttempt,
                and_(
                    GenerationAttempt.id == GenerationTask.current_attempt_id,
                    GenerationAttempt.task_id == GenerationTask.id,
                ),
            )
            .where(
                GenerationTask.status.in_(("queued", "processing")),
                GenerationAttempt.status.in_(("queued", "processing")),
                GenerationAttempt.deadline_at <= now,
            )
            .order_by(
                GenerationAttempt.deadline_at,
                GenerationTask.created_at,
                GenerationTask.id,
            )
            .limit(batch_size)
            .with_for_update(of=GenerationTask, skip_locked=True)
        )
        return list(result.all())
