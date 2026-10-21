"""Bounded database watchdog for silent provider attempts."""

from datetime import UTC, datetime

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.task_repository import TaskRepository
from app.services.generation_service import GenerationService
from app.services.provider_callback_service import AttemptDispatch


class Watchdog:
    """Claims expired current attempts and routes their timeout outcomes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        generation_service: GenerationService,
        batch_size: int = 50,
    ) -> None:
        self.session_factory: async_sessionmaker[AsyncSession] = session_factory
        self.generation_service: GenerationService = generation_service
        self.tasks: TaskRepository = TaskRepository()
        self.batch_size: int = batch_size

    async def run_once(self) -> int:
        """Commit one bounded batch of timeout/failover/refund transitions."""
        now = datetime.now(UTC)
        dispatches: list[AttemptDispatch] = []
        async with self.session_factory() as session:
            async with session.begin():
                due_tasks = await self.tasks.due_for_watchdog(
                    session, now, self.batch_size
                )
                for task in due_tasks:
                    dispatch = await self.generation_service.callbacks.timeout_due(
                        session, task.id, now
                    )
                    if dispatch is not None:
                        dispatches.append(dispatch)

        for dispatch in dispatches:
            async with self.session_factory() as session:
                await self.generation_service.dispatch(session, dispatch)
        return len(due_tasks)

    async def run_forever(self, poll_interval_seconds: float) -> None:
        """Poll once per interval; each database claim remains batch-bounded."""
        while True:
            _ = await self.run_once()
            await anyio.sleep(poll_interval_seconds)
