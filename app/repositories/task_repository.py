"""Generation task persistence queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_task import GenerationTask


class TaskRepository:
    """Queries tasks and counts active work within the caller's transaction."""

    async def get(self, session: AsyncSession, task_id: UUID) -> GenerationTask | None:
        """Return a task by id."""
        return await session.get(GenerationTask, task_id)

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
