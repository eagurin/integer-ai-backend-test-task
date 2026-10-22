"""Bounded database watchdog for silent provider attempts."""

from datetime import UTC, datetime

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.task_repository import TaskRepository
from app.services.generation_service import DispatchLease, GenerationService


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
        dispatches: list[DispatchLease] = []
        async with self.session_factory() as session:
            async with session.begin():
                due_tasks = await self.tasks.due_for_watchdog(
                    session, now, self.batch_size
                )
                for task in due_tasks:
                    if task.status == "queued":
                        lease = await self.generation_service.claim_queued_attempt(
                            session, task.id
                        )
                    else:
                        dispatch = await self.generation_service.callbacks.timeout_due(
                            session, task.id, now
                        )
                        lease = (
                            await self.generation_service.claim_dispatch(
                                session, dispatch
                            )
                            if dispatch is not None
                            else None
                        )
                    if lease is not None:
                        dispatches.append(lease)

        for lease in dispatches:
            async with self.session_factory() as session:
                await self.generation_service.send_claimed(session, lease)
        return len(due_tasks)

    async def run_forever(self, poll_interval_seconds: float) -> None:
        """Poll once per interval; each database claim remains batch-bounded."""
        while True:
            _ = await self.run_once()
            await anyio.sleep(poll_interval_seconds)
