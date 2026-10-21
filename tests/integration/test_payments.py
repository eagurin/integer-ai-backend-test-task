"""PostgreSQL-backed payment webhook and balance behavior."""

import asyncio
import hashlib
import hmac
import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.api.controllers.payments import payment_webhook
from app.api.schemas.webhooks import PaymentWebhookRequest
from app.factory import create_app
from app.models.payment_identity import PaymentIdentity
from app.models.token_ledger_entry import TokenLedgerEntry
from app.models.user import User
from app.settings import Settings
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SECRET = "integration-secret"


def signed(payload: bytes) -> str:
    return hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


async def client_for(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[httpx.AsyncClient, AbstractAsyncContextManager[Any]]:
    application = create_app(Settings(webhook_secret=SecretStr(SECRET)))
    context = application.router.lifespan_context(application)
    await context.__aenter__()
    application.state.session_factory = session_factory
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    )
    return client, context


async def close_client(
    client: httpx.AsyncClient, context: AbstractAsyncContextManager[None]
) -> None:
    await client.aclose()
    await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_20_concurrent_duplicate_success_webhooks_credit_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment_id, user_id = uuid4(), uuid4()
    body = json.dumps(
        {
            "payment_id": str(payment_id),
            "user_id": str(user_id),
            "tokens": 7,
            "status": "succeeded",
        },
        separators=(",", ":"),
    ).encode()
    client, cleanup = await client_for(session_factory)
    try:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/webhooks/payments",
                    content=body,
                    headers={"X-Signature": signed(body)},
                )
                for _ in range(20)
            )
        )
        assert [response.status_code for response in responses] == [204] * 20
        balance = await client.get(f"/users/{user_id}/balance")
        assert balance.status_code == 200
        assert balance.json()["balance"] == 7
        body_json: dict[str, object] = balance.json()
        history = body_json["history"]
        assert isinstance(history, list)
        assert len(history) == 1
        async with session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PaymentIdentity)
                    .where(PaymentIdentity.payment_id == str(payment_id))
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TokenLedgerEntry)
                    .where(TokenLedgerEntry.operation_key == f"payment:{payment_id}")
                )
                == 1
            )
    finally:
        await close_client(client, cleanup)


@pytest.mark.asyncio
async def test_payment_transitions_duplicates_and_conflicts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = uuid4()
    async with session_factory() as session:
        session.add(User(id=user_id))
        await session.commit()
    client, cleanup = await client_for(session_factory)
    payment_id = uuid4()

    async def post(
        status: str,
        *,
        pid: UUID = payment_id,
        tokens: int = 5,
        uid: UUID = user_id,
    ) -> httpx.Response:
        body = json.dumps(
            {
                "payment_id": str(pid),
                "user_id": str(uid),
                "tokens": tokens,
                "status": status,
            },
            separators=(",", ":"),
        ).encode()
        return await client.post(
            "/webhooks/payments", content=body, headers={"X-Signature": signed(body)}
        )

    try:
        assert (await post("pending")).status_code == 204
        assert (await post("pending")).status_code == 204
        assert (await post("succeeded")).status_code == 204
        assert (await post("succeeded")).status_code == 204
        assert (await post("failed")).status_code == 409
        assert (await post("succeeded", tokens=8)).status_code == 409
        balance = await client.get(f"/users/{user_id}/balance")
        assert balance.json()["balance"] == 5

        failed_id = uuid4()
        assert (await post("failed", pid=failed_id)).status_code == 204
        assert (await post("succeeded", pid=failed_id)).status_code == 409
        balance = await client.get(f"/users/{user_id}/balance")
        assert balance.json()["balance"] == 5

        assert (await client.get(f"/users/{uuid4()}/balance")).status_code == 404
        assert (await post("pending", uid=uuid4())).status_code == 404
    finally:
        await close_client(client, cleanup)


@pytest.mark.asyncio
async def test_balance_returns_twenty_newest_entries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add(User(id=user_id))
        await session.flush()
        session.add_all(
            TokenLedgerEntry(
                user_id=user_id,
                operation_key=f"history:{uuid4()}",
                delta=1,
                reason=f"entry-{index}",
                created_at=now + timedelta(minutes=index),
            )
            for index in range(25)
        )
        await session.commit()
    client, cleanup = await client_for(session_factory)
    try:
        response = await client.get(f"/users/{user_id}/balance")
        assert response.status_code == 200
        assert response.json()["balance"] == 25
        assert len(response.json()["history"]) == 20
        rows: list[dict[str, str]] = response.json()["history"]
        assert [row["operation"] for row in rows] == [
            f"entry-{index}" for index in reversed(range(5, 25))
        ]
        timestamps = [row["created_at"] for row in rows]
        assert timestamps == sorted(timestamps, reverse=True)
    finally:
        await close_client(client, cleanup)


@pytest.mark.asyncio
async def test_rollback_before_commit_leaves_no_payment_or_credit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment_id, user_id = uuid4(), uuid4()
    body = json.dumps(
        {
            "payment_id": str(payment_id),
            "user_id": str(user_id),
            "tokens": 7,
            "status": "succeeded",
        },
        separators=(",", ":"),
    ).encode()
    client, cleanup = await client_for(session_factory)
    original = payment_webhook.__globals__["service"].apply
    try:

        async def fail_after_apply(
            session: AsyncSession, event: PaymentWebhookRequest
        ) -> None:
            await original(session, event)
            raise RuntimeError("forced pre-commit failure")

        payment_webhook.__globals__["service"].apply = fail_after_apply
        failed = await client.post(
            "/webhooks/payments", content=body, headers={"X-Signature": signed(body)}
        )
        assert failed.status_code == 500
        payment_webhook.__globals__["service"].apply = original
        retry = await client.post(
            "/webhooks/payments", content=body, headers={"X-Signature": signed(body)}
        )
        assert retry.status_code == 204
        async with session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PaymentIdentity)
                    .where(PaymentIdentity.payment_id == str(payment_id))
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TokenLedgerEntry)
                    .where(TokenLedgerEntry.operation_key == f"payment:{payment_id}")
                )
                == 1
            )
    finally:
        payment_webhook.__globals__["service"].apply = original
        await close_client(client, cleanup)
