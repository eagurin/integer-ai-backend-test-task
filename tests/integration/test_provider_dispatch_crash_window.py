"""Durability behavior when dispatch is interrupted after task commit."""

import httpx
import pytest
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.providers import (
    GenerationInput,
    ProviderAcceptance,
    ProviderPort,
    TemporaryProviderPort,
)
from app.services.provider_callback_service import AttemptDispatch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.provider_helpers import (
    callback,
    client_for,
    close_client,
    funded_user,
)
from tests.integration.watchdog_helpers import expire_dispatch_lease


class InterruptedProvider:
    """Simulates a process interruption at the provider HTTP boundary."""

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """Fail every attempt without touching its committed database record."""
        raise httpx.ConnectError("simulated dispatch interruption")


async def test_repeated_dispatch_interruption_preserves_committed_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repeated dispatch failures preserve one debit and one recoverable attempt."""
    user_id = await funded_user(session_factory)
    provider: ProviderPort = InterruptedProvider()
    client, cleanup, service = await client_for(session_factory, provider)
    try:
        response = await client.post(
            "/generate",
            json={
                "user_id": str(user_id),
                "model": "image-fast",
                "prompt": "Persisted before interrupted provider call",
                "ref_images": [],
            },
        )
        assert response.status_code == 500

        async with session_factory() as session:
            task = await session.scalar(
                select(GenerationTask).where(GenerationTask.user_id == user_id)
            )
        assert task is not None
        dispatch = AttemptDispatch(
            provider="alpha",
            generation=GenerationInput(
                task_id=task.id,
                attempt_no=1,
                prompt=task.prompt,
                ref_images=tuple(task.ref_images),
            ),
        )
        for _ in range(2):
            await expire_dispatch_lease(session_factory, task.id, 1)
            with pytest.raises(httpx.ConnectError):
                async with session_factory() as session:
                    await service.dispatch(session, dispatch)

        async with session_factory() as session:
            durable_task = await session.get(GenerationTask, task.id)
            durable_task_count = await session.scalar(
                select(func.count())
                .select_from(GenerationTask)
                .where(GenerationTask.user_id == user_id)
            )
            attempts = list(
                (
                    await session.scalars(
                        select(GenerationAttempt).where(
                            GenerationAttempt.task_id == task.id
                        )
                    )
                ).all()
            )
            balance = await session.scalar(
                select(func.sum(TokenLedgerEntry.delta)).where(
                    TokenLedgerEntry.user_id == user_id
                )
            )
        assert durable_task is not None and durable_task.status == "queued"
        assert durable_task_count == 1
        assert len(attempts) == 1
        assert attempts[0].status == "queued"
        assert balance == 98

        service.provider = TemporaryProviderPort()
        await expire_dispatch_lease(session_factory, task.id, 1)
        async with session_factory() as session:
            await service.dispatch(session, dispatch)
        completed = await callback(client, task.id, 1, "alpha", "completed")
        assert completed.status_code == 204
        async with session_factory() as session:
            recovered_task = await session.get(GenerationTask, task.id)
        assert recovered_task is not None and recovered_task.status == "succeeded"
    finally:
        await close_client(client, cleanup)
