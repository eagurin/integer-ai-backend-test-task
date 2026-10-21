"""PostgreSQL-backed provider failover and callback contracts."""

import anyio
import pytest
from app.api.schemas.webhooks import ProviderWebhookRequest
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.services.provider_callback_service import AttemptDispatch
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


async def test_first_provider_failure_succeeds_on_second_with_two_attempts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A technical error advances once and completion settles the task."""
    user_id = await funded_user(session_factory)
    client, cleanup, _ = await client_for(session_factory)
    try:
        task_id = await generate(client, user_id)
        assert (
            await callback(client, task_id, 1, "alpha", "technical_error")
        ).status_code == 204
        assert (
            await callback(client, task_id, 2, "beta", "completed")
        ).status_code == 204
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
        assert task is not None and task.status == "succeeded"
        assert task.result_url == "https://provider.example/result.png"
        assert [
            (item.attempt_no, item.status, item.error_type) for item in attempts
        ] == [
            (1, "failed", "technical_error"),
            (2, "succeeded", None),
        ]
        assert all(item.completed_at is not None for item in attempts)
    finally:
        await close_client(client, cleanup)


async def test_moderation_skips_flagged_leg(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Video moderation skips only the alpha catalog leg flagged for it."""
    user_id = await funded_user(session_factory)
    client, cleanup, _ = await client_for(session_factory)
    try:
        task_id = await generate(client, user_id, model="video-long")
        assert (
            await callback(client, task_id, 1, "beta", "moderation")
        ).status_code == 204
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempts = await session.scalar(
                select(func.count())
                .select_from(GenerationAttempt)
                .where(GenerationAttempt.task_id == task_id)
            )
            refund = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.operation_key == f"generation:{task_id}:refund")
            )
        assert task is not None and task.status == "failed"
        assert attempts == 1
        assert refund == 1
    finally:
        await close_client(client, cleanup)


async def test_sync_503_and_timeout_fail_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Synchronous 503 and timeout statuses both advance to beta."""
    provider = SequenceProvider([503, 202, 504, 202])
    client, cleanup, _ = await client_for(session_factory, provider)
    user_ids = [await funded_user(session_factory) for _ in range(2)]
    try:
        task_ids = [await generate(client, user_id) for user_id in user_ids]
        assert [
            (provider_name, generation.attempt_no)
            for provider_name, generation in provider.calls
        ] == [("alpha", 1), ("beta", 2), ("alpha", 1), ("beta", 2)]
        async with session_factory() as session:
            statuses = [
                await session.scalar(
                    select(GenerationTask.status).where(GenerationTask.id == task_id)
                )
                for task_id in task_ids
            ]
        assert statuses == ["processing", "processing"]
    finally:
        await close_client(client, cleanup)


async def test_payload_failure_is_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Payload rejection refunds once and never contacts the next leg."""
    user_id = await funded_user(session_factory)
    provider = SequenceProvider([202])
    client, cleanup, _ = await client_for(session_factory, provider)
    try:
        task_id = await generate(client, user_id)
        assert (
            await callback(client, task_id, 1, "alpha", "payload")
        ).status_code == 204
        assert len(provider.calls) == 1
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            refunds = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.operation_key == f"generation:{task_id}:refund")
            )
        assert task is not None and task.status == "failed"
        assert refunds == 1
    finally:
        await close_client(client, cleanup)


async def test_10_concurrent_final_leg_failures_refund_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ten concurrent current-leg failures serialize to one refund."""
    user_id = await funded_user(session_factory)
    client, cleanup, _ = await client_for(session_factory)
    try:
        task_id = await generate(client, user_id)
        assert (
            await callback(client, task_id, 1, "alpha", "technical_error")
        ).status_code == 204
        ready = anyio.Event()
        arrived = 0
        responses: list[int] = []

        async def post_failure() -> None:
            nonlocal arrived
            arrived += 1
            if arrived == 10:
                ready.set()
            await ready.wait()
            response = await callback(client, task_id, 2, "beta", "technical_error")
            responses.append(response.status_code)

        with anyio.fail_after(10):
            async with anyio.create_task_group() as task_group:
                for _ in range(10):
                    task_group.start_soon(post_failure)
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
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
        assert responses == [204] * 10
        assert task is not None and task.status == "failed"
        assert refunds == 1
        assert balance == 100
    finally:
        await close_client(client, cleanup)


async def test_rollback_before_callback_commit_preserves_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception before commit rolls back task and attempt transition."""
    user_id = await funded_user(session_factory)
    client, cleanup, service = await client_for(session_factory)
    original = service.callbacks.apply
    try:
        task_id = await generate(client, user_id)

        async def fail_after_apply(
            session: AsyncSession,
            provider_name: str,
            event: ProviderWebhookRequest,
        ) -> AttemptDispatch | None:
            await original(session, provider_name, event)
            raise RuntimeError("forced pre-commit failure")

        monkeypatch.setattr(service.callbacks, "apply", fail_after_apply)
        response = await callback(client, task_id, 1, "alpha", "technical_error")
        assert response.status_code == 500
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
        assert task is not None and task.status == "processing"
        assert len(attempts) == 1
        assert attempts[0].status == "processing"
    finally:
        await close_client(client, cleanup)
