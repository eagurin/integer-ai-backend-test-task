"""Shared integration-test fixtures backed by the Compose PostgreSQL service."""

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest_asyncio.fixture
async def database_engine() -> AsyncIterator[AsyncEngine]:
    """Connect to PostgreSQL; schema lifecycle belongs to Alembic, not tests."""
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/integer_generator",
    )
    engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=20)
    try:
        async with engine.connect():
            pass
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return a factory so each concurrent operation gets its own session."""
    return async_sessionmaker(database_engine, expire_on_commit=False)
