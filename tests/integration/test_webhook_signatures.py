"""Database no-mutation guarantees for rejected payment signatures."""

import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from app.factory import create_app
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask
from app.models.payment_identity import PaymentIdentity
from app.models.token_ledger_entry import TokenLedgerEntry
from app.settings import Settings
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.provider_helpers import (
    client_for,
    close_client,
    funded_user,
    generate,
    sign,
)


@pytest.mark.asyncio
async def test_invalid_payment_signature_changes_no_ledger(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = create_app(Settings(webhook_secret=SecretStr("integration-secret")))
    async with app.router.lifespan_context(app):
        app.state.session_factory = session_factory
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            payload = {
                "payment_id": str(uuid4()),
                "user_id": str(uuid4()),
                "tokens": 9,
                "status": "succeeded",
            }
            body = json.dumps(payload, separators=(",", ":")).encode()
            invalid = hmac.new(b"wrong-secret", body, hashlib.sha256).hexdigest()
            response = await client.post(
                "/webhooks/payments",
                content=body,
                headers={"X-Signature": invalid},
            )
            assert response.status_code == 401
            missing = await client.post("/webhooks/payments", content=body)
            assert missing.status_code == 401

    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PaymentIdentity)
                .where(PaymentIdentity.payment_id == payload["payment_id"])
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(
                    TokenLedgerEntry.operation_key == f"payment:{payload['payment_id']}"
                )
            )
            == 0
        )


async def test_invalid_provider_signature_changes_no_task_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An invalid provider HMAC leaves task, attempt, and ledger untouched."""
    user_id = await funded_user(session_factory)
    client, cleanup, _ = await client_for(session_factory)
    try:
        task_id = await generate(client, user_id)
        body = json.dumps(
            {
                "task_id": str(task_id),
                "attempt_no": 1,
                "outcome": "technical_error",
            },
            separators=(",", ":"),
        ).encode()
        response = await client.post(
            "/webhooks/providers/alpha",
            content=body,
            headers={"X-Signature": "0" * 64},
        )
        assert response.status_code == 401
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempt_count = await session.scalar(
                select(func.count())
                .select_from(GenerationAttempt)
                .where(GenerationAttempt.task_id == task_id)
            )
            ledger_count = await session.scalar(
                select(func.count())
                .select_from(TokenLedgerEntry)
                .where(TokenLedgerEntry.user_id == user_id)
            )
        assert task is not None and task.status == "processing"
        assert attempt_count == 1
        assert ledger_count == 2
    finally:
        await close_client(client, cleanup)


async def test_malformed_signed_provider_callback_changes_no_task_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A signed but invalid callback is rejected before database mutation."""
    user_id = await funded_user(session_factory)
    client, cleanup, _ = await client_for(session_factory)
    try:
        task_id = await generate(client, user_id)
        body = json.dumps(
            {
                "task_id": str(task_id),
                "attempt_no": 0,
                "outcome": "unknown",
            },
            separators=(",", ":"),
        ).encode()
        response = await client.post(
            "/webhooks/providers/alpha",
            content=body,
            headers={"X-Signature": sign(body)},
        )
        assert response.status_code == 422
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempt_count = await session.scalar(
                select(func.count())
                .select_from(GenerationAttempt)
                .where(GenerationAttempt.task_id == task_id)
            )
        assert task is not None and task.status == "processing"
        assert attempt_count == 1
    finally:
        await close_client(client, cleanup)
