"""Payment webhook and user balance endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.balance import BalanceResponse, LedgerEntryResponse
from app.api.schemas.webhooks import PaymentWebhookRequest
from app.database import get_session
from app.security import verify_webhook_signature
from app.services.payment_service import PaymentService
from app.settings import Settings

router = APIRouter()
service = PaymentService()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.post("/webhooks/payments", status_code=204)
async def payment_webhook(
    request: Request,
    session: SessionDependency,
    signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> Response:
    """Verify the original bytes before parsing and applying a payment event."""
    raw_body = await request.body()
    settings: Settings = request.app.state.settings
    if not verify_webhook_signature(
        raw_body, signature, settings.webhook_secret.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        event = PaymentWebhookRequest.model_validate_json(raw_body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    async with session.begin():
        await service.apply(session, event)
    return Response(status_code=204)


@router.get("/users/{user_id}/balance", response_model=BalanceResponse)
async def get_balance(user_id: UUID, session: SessionDependency) -> BalanceResponse:
    """Return the ledger-derived balance and at most twenty newest movements."""
    balance, entries = await service.balance(session, user_id)
    return BalanceResponse(
        user_id=user_id,
        balance=balance,
        history=[
            LedgerEntryResponse(
                operation=entry.reason,
                delta=entry.delta,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
    )
