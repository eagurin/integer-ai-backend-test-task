"""PostgreSQL-backed provider dispatch lease and recovery scenarios."""

from typing import final
from uuid import UUID

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
    client_for,
    close_client,
    funded_user,
    generate,
)
from tests.integration.watchdog_helpers import (
    expire_attempt,
    expire_dispatch_lease,
)


@final
class GatedProvider:
    """Hold the first provider POST until the test releases its event gate."""

    def __init__(self) -> None:
        self.entered = anyio.Event()
        self.release = anyio.Event()
        self.calls: list[tuple[str, GenerationInput]] = []

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """Block the first POST and accept any later recovery dispatch."""
        self.calls.append((provider, generation))
        if len(self.calls) == 1:
            self.entered.set()
            await self.release.wait()
        return ProviderAcceptance(
            status_code=202,
            external_id=f"{provider}-{generation.task_id}-{len(self.calls)}",
        )


@final
class GatedInterruptionProvider:
    """Pause a failed dispatch after its database lease is committed."""

    def __init__(self) -> None:
        self.entered = anyio.Event()
        self.release = anyio.Event()

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """Raise the simulated process interruption after the event gate."""
        self.entered.set()
        await self.release.wait()
        raise httpx.ConnectError(
            f"dispatch interrupted for {provider}/{generation.task_id}"
        )


async def test_watchdog_does_not_expire_provider_post_in_flight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A leased POST remains current after its original deadline passes."""
    user_id = await funded_user(session_factory)
    provider = GatedProvider()
    client, cleanup, service = await client_for(session_factory, provider)
    watchdog = Watchdog(session_factory, service)
    responses: list[httpx.Response] = []
    task_id: UUID | None = None

    async def submit() -> None:
        responses.append(
            await client.post(
                "/generate",
                json={
                    "user_id": str(user_id),
                    "model": "image-fast",
                    "prompt": "Hold provider dispatch past its deadline",
                    "ref_images": [],
                },
            )
        )

    try:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as task_group:
                _ = task_group.start_soon(submit)
                await provider.entered.wait()
                async with session_factory() as session:
                    task_id = await session.scalar(
                        select(GenerationTask.id).where(
                            GenerationTask.user_id == user_id
                        )
                    )
                assert task_id is not None
                await expire_attempt(session_factory, task_id, 1)
                assert await watchdog.run_once() == 0
                await expire_dispatch_lease(session_factory, task_id, 1)
                assert await watchdog.run_once() == 1
                provider.release.set()

        assert task_id is not None
        assert len(responses) == 1 and responses[0].status_code == 202
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempts = list(
                (
                    await session.scalars(
                        select(GenerationAttempt).where(
                            GenerationAttempt.task_id == task_id
                        )
                    )
                ).all()
            )
            refunds = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.operation_key == f"generation:{task_id}:refund")
            )
        assert task is not None and task.status == "processing"
        assert len(attempts) == 1 and attempts[0].status == "processing"
        assert refunds == 0
        assert len(provider.calls) == 2
    finally:
        provider.release.set()
        await close_client(client, cleanup)


async def test_watchdog_recovers_committed_undispatched_fallback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A later watchdog tick dispatches a fallback committed before a crash."""
    user_id = await funded_user(session_factory)
    provider = SequenceProvider([202, 202])
    client, cleanup, service = await client_for(session_factory, provider)
    watchdog = Watchdog(session_factory, service)
    try:
        task_id = await generate(client, user_id)
        await expire_attempt(session_factory, task_id, 1)
        interrupted_provider = GatedInterruptionProvider()
        service.provider = interrupted_provider
        interruptions: list[bool] = []

        async def interrupt_dispatch() -> None:
            try:
                _ = await watchdog.run_once()
            except httpx.ConnectError:
                interruptions.append(True)

        with anyio.fail_after(10):
            async with anyio.create_task_group() as task_group:
                _ = task_group.start_soon(interrupt_dispatch)
                await interrupted_provider.entered.wait()
                async with session_factory() as session:
                    fallback_attempt = await session.scalar(
                        select(GenerationAttempt).where(
                            GenerationAttempt.task_id == task_id,
                            GenerationAttempt.attempt_no == 2,
                        )
                    )
                assert fallback_attempt is not None
                assert fallback_attempt.status == "queued"
                assert fallback_attempt.dispatch_lease_token is not None
                interrupted_provider.release.set()
        assert interruptions == [True]
        assert [provider_name for provider_name, _ in provider.calls] == ["alpha"]

        await expire_dispatch_lease(session_factory, task_id, 2)
        service.provider = provider
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
