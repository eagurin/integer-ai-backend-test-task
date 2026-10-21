"""Payment webhook processing and ledger-derived balances."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.webhooks import PaymentWebhookRequest
from app.models.payment_identity import PaymentIdentity
from app.models.token_ledger_entry import TokenLedgerEntry
from app.models.user import User
from app.repositories.token_ledger_repository import TokenLedgerRepository
from app.repositories.user_repository import UserRepository


class PaymentService:
    """Apply signed payment events in the request's database transaction."""

    def __init__(self) -> None:
        self.users = UserRepository()
        self.ledger = TokenLedgerRepository()

    async def apply(self, session: AsyncSession, event: PaymentWebhookRequest) -> None:
        """Persist payment state and its credit atomically and idempotently."""
        if event.status.value == "succeeded":
            await session.execute(
                insert(User)
                .values(id=event.user_id)
                .on_conflict_do_nothing(index_elements=[User.id])
            )

        user = await session.scalar(
            select(User).where(User.id == event.user_id).with_for_update()
        )
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        inserted = await session.scalar(
            insert(PaymentIdentity)
            .values(
                payment_id=str(event.payment_id),
                user_id=event.user_id,
                token_count=event.tokens,
                status=event.status.value,
            )
            .on_conflict_do_nothing(index_elements=[PaymentIdentity.payment_id])
            .returning(PaymentIdentity.id)
        )
        if inserted is None:
            payment = await session.scalar(
                select(PaymentIdentity)
                .where(PaymentIdentity.payment_id == str(event.payment_id))
                .with_for_update()
            )
            assert payment is not None
            if payment.user_id != event.user_id or payment.token_count != event.tokens:
                raise HTTPException(status_code=409, detail="Payment identity conflict")
            if payment.status == event.status.value:
                return
            if payment.status != "pending" or event.status.value == "pending":
                raise HTTPException(status_code=409, detail="Payment status conflict")
            payment.status = event.status.value
            await session.flush()

        if event.status.value == "succeeded":
            await self.ledger.append(
                session,
                TokenLedgerEntry(
                    user_id=event.user_id,
                    operation_key=f"payment:{event.payment_id}",
                    delta=event.tokens,
                    reason="payment",
                ),
            )

    async def balance(
        self, session: AsyncSession, user_id: UUID
    ) -> tuple[int, list[TokenLedgerEntry]]:
        """Return total and newest twenty entries for an existing account."""
        if await self.users.get(session, user_id) is None:
            raise HTTPException(status_code=404, detail="User not found")
        return (
            await self.ledger.balance(session, user_id),
            await self.ledger.recent(session, user_id, limit=20),
        )
