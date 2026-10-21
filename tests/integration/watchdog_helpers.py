"""Database setup helpers shared by watchdog integration scenarios."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.models.generation_attempt import GenerationAttempt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def expire_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: UUID,
    attempt_no: int,
) -> None:
    """Isolate one due task and persist its deadline without waiting."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        _ = await session.execute(
            update(GenerationAttempt)
            .where(
                GenerationAttempt.task_id != task_id,
                GenerationAttempt.status.in_(("queued", "processing")),
            )
            .values(deadline_at=now + timedelta(days=1))
        )
        attempt = await session.scalar(
            select(GenerationAttempt).where(
                GenerationAttempt.task_id == task_id,
                GenerationAttempt.attempt_no == attempt_no,
            )
        )
        assert attempt is not None
        _ = await session.execute(
            update(GenerationAttempt)
            .where(GenerationAttempt.id == attempt.id)
            .values(deadline_at=now - timedelta(minutes=1))
        )
        await session.commit()
