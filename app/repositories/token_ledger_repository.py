"""Append-only token ledger persistence queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token_ledger_entry import TokenLedgerEntry


class TokenLedgerRepository:
    """Appends ledger entries and derives account balances from their deltas."""

    async def append(
        self, session: AsyncSession, entry: TokenLedgerEntry
    ) -> TokenLedgerEntry:
        """Append one immutable entry without committing the caller's transaction."""
        session.add(entry)
        await session.flush()
        return entry

    async def balance(self, session: AsyncSession, user_id: UUID) -> int:
        """Return the sum of all token deltas for a user."""
        result = await session.execute(
            select(func.coalesce(func.sum(TokenLedgerEntry.delta), 0)).where(
                TokenLedgerEntry.user_id == user_id
            )
        )
        return int(result.scalar_one())

    async def recent(
        self, session: AsyncSession, user_id: UUID, limit: int = 20
    ) -> list[TokenLedgerEntry]:
        """Return newest ledger entries first."""
        result = await session.execute(
            select(TokenLedgerEntry)
            .where(TokenLedgerEntry.user_id == user_id)
            .order_by(TokenLedgerEntry.created_at.desc(), TokenLedgerEntry.id.desc())
            .limit(limit)
        )
        return list(result.scalars())
