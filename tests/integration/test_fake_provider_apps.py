"""HTTP contract tests for provider applications and stale callbacks."""

from typing import Literal
from uuid import UUID

import httpx
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.providers.fake_app import FakeProviderSettings, create_fake_provider_app
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.provider_helpers import (
    callback,
    client_for,
    close_client,
    funded_user,
    generate,
)


async def test_stale_and_duplicate_callbacks_leave_settled_state_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Old-leg and duplicate outcomes return 204 without rewriting results."""
    user_id = await funded_user(session_factory)
    client, cleanup, _ = await client_for(session_factory)
    try:
        task_id = await generate(client, user_id)
        out_of_order = await callback(client, task_id, 2, "beta", "completed")
        await callback(client, task_id, 1, "alpha", "technical_error")
        await callback(client, task_id, 2, "beta", "completed")
        stale = await callback(client, task_id, 1, "alpha", "payload")
        duplicate = await callback(client, task_id, 2, "beta", "technical_error")
        assert (
            out_of_order.status_code
            == stale.status_code
            == duplicate.status_code
            == 204
        )
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            count = await session.scalar(
                select(func.count())
                .select_from(GenerationAttempt)
                .where(GenerationAttempt.task_id == task_id)
            )
            refunds = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.operation_key == f"generation:{task_id}:refund")
            )
        assert task is not None and task.status == "succeeded"
        assert task.result_url == "https://provider.example/result.png"
        assert count == 2
        assert refunds == 0
    finally:
        await close_client(client, cleanup)


async def test_fake_alpha_and_beta_accept_tasks_with_external_ids() -> None:
    """Both provider applications expose the same 202 acceptance contract."""
    names: tuple[Literal["alpha", "beta"], ...] = ("alpha", "beta")
    for name in names:
        application = create_fake_provider_app(
            FakeProviderSettings(provider_name=name, omit_callback=True)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/tasks",
                json={
                    "task_id": str(UUID("ed89a1e6-4806-4e0d-8a12-7b90b2ee878f")),
                    "attempt_no": 1,
                    "prompt": "test prompt",
                    "ref_images": [],
                    "callback_url": "http://127.0.0.1:8000/webhooks/providers",
                    "callback_secret": "test-secret",
                },
            )
        assert response.status_code == 202
        assert response.json()["external_id"].startswith(f"{name}-")


async def test_fake_provider_rejects_malformed_task_data() -> None:
    """Invalid provider task identity and attempt number return 422."""
    application = create_fake_provider_app(
        FakeProviderSettings(provider_name="alpha", omit_callback=True)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/tasks",
            json={
                "task_id": "not-a-uuid",
                "attempt_no": 0,
                "prompt": "malformed",
                "ref_images": [],
                "callback_url": "http://localhost/callback",
                "callback_secret": "secret",
            },
        )
    assert response.status_code == 422
