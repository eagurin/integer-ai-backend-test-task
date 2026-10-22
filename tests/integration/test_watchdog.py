"""PostgreSQL-backed watchdog timeout and callback arbitration scenarios."""

import anyio
import httpx
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.providers import GenerationInput, ProviderAcceptance
from app.workers.watchdog import Watchdog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.provider_helpers import (
    SequenceProvider,
    callback,
    client_for,
    close_client,
    funded_user,
    generate,
)
from tests.integration.watchdog_helpers import (
    expire_attempt,
    expire_dispatch_lease,
)


async def test_late_completed_after_watchdog_commit_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A completion after terminal timeout cannot restore output or debit."""
    user_id = await funded_user(session_factory)
    provider = SequenceProvider([202, 202])
    client, cleanup, service = await client_for(session_factory, provider)
    watchdog = Watchdog(session_factory, service)
    try:
        task_id = await generate(client, user_id)
        await expire_attempt(session_factory, task_id, 1)
        assert await watchdog.run_once() == 1
        await expire_attempt(session_factory, task_id, 2)
        assert await watchdog.run_once() == 1

        late = await callback(client, task_id, 2, "beta", "completed")
        assert late.status_code == 204
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempts = list(
                (
                    await session.scalars(
                        select(GenerationAttempt)
                        .where(GenerationAttempt.task_id == task_id)
                        .order_by(GenerationAttempt.attempt_no)
                    )
                ).all()
            )
            refunds = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.operation_key == f"generation:{task_id}:refund")
            )
            balance = await session.scalar(
                select(func.sum(TokenLedgerEntry.delta)).where(
                    TokenLedgerEntry.user_id == user_id
                )
            )
        assert task is not None and task.status == "failed"
        assert task.result_url is None
        assert [(attempt.status, attempt.error_type) for attempt in attempts] == [
            ("timed_out", "timeout"),
            ("timed_out", "timeout"),
        ]
        assert refunds == 1
        assert balance == 100
    finally:
        await close_client(client, cleanup)


async def test_concurrent_watchdogs_claim_task_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Four independent watchdog sessions claim one due task once."""
    user_id = await funded_user(session_factory)
    provider = SequenceProvider([202, 202])
    client, cleanup, service = await client_for(session_factory, provider)
    watchdogs = [Watchdog(session_factory, service, batch_size=1) for _ in range(4)]
    ready = anyio.Event()
    arrived = 0
    claims: list[int] = []
    try:
        task_id = await generate(client, user_id)
        await expire_attempt(session_factory, task_id, 1)

        async def tick(watchdog: Watchdog) -> None:
            nonlocal arrived
            arrived += 1
            if arrived == len(watchdogs):
                ready.set()
            await ready.wait()
            claims.append(await watchdog.run_once())

        with anyio.fail_after(10):
            async with anyio.create_task_group() as task_group:
                for watchdog in watchdogs:
                    _ = task_group.start_soon(tick, watchdog)

        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempts = list(
                (
                    await session.scalars(
                        select(GenerationAttempt)
                        .where(GenerationAttempt.task_id == task_id)
                        .order_by(GenerationAttempt.attempt_no)
                    )
                ).all()
            )
            refunds = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.operation_key == f"generation:{task_id}:refund")
            )
        assert sum(claims) == 1
        assert task is not None and task.status == "processing"
        assert task.current_attempt_id == attempts[1].id
        assert [(attempt.status, attempt.error_type) for attempt in attempts] == [
            ("timed_out", "timeout"),
            ("processing", None),
        ]
        assert [provider_name for provider_name, _ in provider.calls] == [
            "alpha",
            "beta",
        ]
        assert refunds == 0
    finally:
        await close_client(client, cleanup)


async def test_provider_silence_times_out_and_fails_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An accepted request without a callback advances to the next provider."""
    user_id = await funded_user(session_factory)
    provider = SequenceProvider([202, 202])
    client, cleanup, service = await client_for(session_factory, provider)
    watchdog = Watchdog(session_factory, service)
    try:
        task_id = await generate(client, user_id)
        await expire_attempt(session_factory, task_id, 1)
        assert await watchdog.run_once() == 1
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempts = list(
                (
                    await session.scalars(
                        select(GenerationAttempt)
                        .where(GenerationAttempt.task_id == task_id)
                        .order_by(GenerationAttempt.attempt_no)
                    )
                ).all()
            )
        assert task is not None and task.status == "processing"
        assert task.current_attempt_id == attempts[1].id
        assert [(attempt.status, attempt.error_type) for attempt in attempts] == [
            ("timed_out", "timeout"),
            ("processing", None),
        ]
        assert [provider_name for provider_name, _ in provider.calls] == [
            "alpha",
            "beta",
        ]
    finally:
        await close_client(client, cleanup)


class InterruptedProvider:
    """Provider port that fails before the first HTTP dispatch is accepted."""

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """Raise a transport error at the attempt-commit/POST crash boundary."""
        raise httpx.ConnectError(
            f"dispatch interrupted for {provider}/{generation.task_id}"
        )


async def test_crash_before_provider_post_times_out_and_fails_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A committed attempt is redispatched after its lease expires."""
    user_id = await funded_user(session_factory)
    client, cleanup, service = await client_for(session_factory, InterruptedProvider())
    watchdog = Watchdog(session_factory, service)
    try:
        response = await client.post(
            "/generate",
            json={
                "user_id": str(user_id),
                "model": "image-fast",
                "prompt": "Persisted before interrupted dispatch",
                "ref_images": [],
            },
        )
        assert response.status_code == 500
        async with session_factory() as session:
            task = await session.scalar(
                select(GenerationTask).where(GenerationTask.user_id == user_id)
            )
            assert task is not None
            attempt = await session.scalar(
                select(GenerationAttempt).where(
                    GenerationAttempt.task_id == task.id,
                    GenerationAttempt.attempt_no == 1,
                )
            )
            assert attempt is not None and attempt.deadline_at is None
            assert attempt.dispatch_lease_token is not None
            task_id = task.id

        await expire_attempt(session_factory, task_id, 1)
        service.provider = SequenceProvider([202])
        await expire_dispatch_lease(session_factory, task_id, 1)
        assert await watchdog.run_once() == 1
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempts = list(
                (
                    await session.scalars(
                        select(GenerationAttempt)
                        .where(GenerationAttempt.task_id == task_id)
                        .order_by(GenerationAttempt.attempt_no)
                    )
                ).all()
            )
            balance = await session.scalar(
                select(func.sum(TokenLedgerEntry.delta)).where(
                    TokenLedgerEntry.user_id == user_id
                )
            )
        assert task is not None and task.status == "processing"
        assert task.current_attempt_id == attempts[0].id
        assert [(attempt.status, attempt.error_type) for attempt in attempts] == [
            ("processing", None),
        ]
        assert balance == 98
    finally:
        await close_client(client, cleanup)
