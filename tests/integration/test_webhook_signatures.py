"""Database no-mutation guarantees for rejected payment signatures."""

import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from app.factory import create_app
from app.models.payment_identity import PaymentIdentity
from app.models.token_ledger_entry import TokenLedgerEntry
from app.settings import Settings
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
