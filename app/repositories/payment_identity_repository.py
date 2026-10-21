"""Payment identity persistence queries."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_identity import PaymentIdentity


class PaymentIdentityRepository:
    """Looks up and inserts externally identified payment attempts."""

    async def get_by_payment_id(
        self, session: AsyncSession, payment_id: str
    ) -> PaymentIdentity | None:
        """Return the identity for a provider payment id."""
        result = await session.execute(
            select(PaymentIdentity).where(PaymentIdentity.payment_id == payment_id)
        )
        return result.scalar_one_or_none()

    async def add(
        self, session: AsyncSession, payment: PaymentIdentity
    ) -> PaymentIdentity:
        """Add and flush a payment identity in the caller's transaction."""
        session.add(payment)
        await session.flush()
        return payment
