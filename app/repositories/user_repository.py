"""User persistence queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Queries and inserts user accounts in the caller's transaction."""

    async def get(self, session: AsyncSession, user_id: UUID) -> User | None:
        """Return a user by id."""
        return await session.get(User, user_id)

    async def get_for_update(self, session: AsyncSession, user_id: UUID) -> User | None:
        """Return and lock a user row while checking and changing its balance."""
        result = await session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def add(self, session: AsyncSession, user: User) -> User:
        """Add and flush a user without committing the caller's transaction."""
        session.add(user)
        await session.flush()
        return user
