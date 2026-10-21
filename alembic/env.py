"""Async Alembic environment."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from app.models import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Return the configured async database URL."""
    database_url = os.environ.get("DATABASE_URL") or config.get_main_option(
        "sqlalchemy.url"
    )
    if database_url is None:
        raise RuntimeError("sqlalchemy.url must be configured for Alembic")
    return database_url


def run_migrations_offline() -> None:
    """Render migrations without connecting to PostgreSQL."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run synchronous Alembic operations on an async-engine connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and adapt its connection for Alembic."""
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = get_database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run online migrations using asyncpg."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
