"""PostgreSQL constraint and immutable-ledger integration checks."""

from uuid import uuid4

import pytest
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_model import GenerationModel, ProviderLeg
from app.models.generation_task import GenerationTask
from app.models.payment_identity import PaymentIdentity
from app.models.token_ledger_entry import TokenLedgerEntry
from app.models.user import User
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def add_user(session: AsyncSession) -> User:
    """Persist an isolated test user in this PostgreSQL session."""
    user = User()
    session.add(user)
    await session.flush()
    return user


async def test_duplicate_payment_id_is_rejected_without_second_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Payment identity uniqueness is enforced by PostgreSQL."""
    payment_id = f"payment-{uuid4()}"
    async with session_factory() as session:
        user = await add_user(session)
        session.add(
            PaymentIdentity(
                payment_id=payment_id,
                user_id=user.id,
                token_count=7,
                status="succeeded",
            )
        )
        await session.commit()
        user_id = user.id

    async with session_factory() as session:
        session.add(
            PaymentIdentity(
                payment_id=payment_id,
                user_id=user_id,
                token_count=7,
                status="succeeded",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(PaymentIdentity)
            .where(PaymentIdentity.payment_id == payment_id)
        )
    assert count == 1


async def test_duplicate_ledger_operation_key_is_rejected_without_second_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The unique operation key prevents duplicate accounting effects."""
    operation_key = f"operation-{uuid4()}"
    async with session_factory() as session:
        user = await add_user(session)
        session.add(
            TokenLedgerEntry(
                user_id=user.id,
                operation_key=operation_key,
                delta=5,
                reason="payment",
            )
        )
        await session.commit()
        user_id = user.id

    async with session_factory() as session:
        session.add(
            TokenLedgerEntry(
                user_id=user_id,
                operation_key=operation_key,
                delta=5,
                reason="payment",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(TokenLedgerEntry)
            .where(TokenLedgerEntry.operation_key == operation_key)
        )
    assert count == 1


async def test_duplicate_attempt_number_is_rejected_without_partial_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A task cannot persist two provider attempts at the same ordinal."""
    async with session_factory() as session:
        user = await add_user(session)
        model = await session.scalar(
            select(GenerationModel).where(GenerationModel.key == "image-fast")
        )
        assert model is not None
        leg = await session.scalar(
            select(ProviderLeg).where(
                ProviderLeg.generation_model_id == model.id,
                ProviderLeg.priority == 1,
            )
        )
        assert leg is not None
        task = GenerationTask(user_id=user.id, generation_model_id=model.id)
        session.add(task)
        await session.flush()
        session.add(
            GenerationAttempt(
                task_id=task.id,
                provider_leg_id=leg.id,
                attempt_no=1,
            )
        )
        await session.commit()
        task_id = task.id
        provider_leg_id = leg.id

    async with session_factory() as session:
        session.add(
            GenerationAttempt(
                task_id=task_id,
                provider_leg_id=provider_leg_id,
                attempt_no=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(GenerationAttempt)
            .where(GenerationAttempt.task_id == task_id)
        )
    assert count == 1


async def test_nonpositive_model_price_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Catalog prices must be positive in the database itself."""
    async with session_factory() as session:
        session.add(GenerationModel(key=f"invalid-{uuid4()}", price_tokens=0))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_duplicate_leg_priority_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One model cannot have ambiguous provider ordering."""
    async with session_factory() as session:
        model = await session.scalar(
            select(GenerationModel).where(GenerationModel.key == "image-fast")
        )
        assert model is not None
        session.add(
            ProviderLeg(
                generation_model_id=model.id,
                provider_name="duplicate-priority",
                priority=1,
                max_refs=3,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_ledger_rows_reject_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Database trigger preserves the append-only accounting history."""
    async with session_factory() as session:
        user = await add_user(session)
        entry = TokenLedgerEntry(
            user_id=user.id,
            operation_key=f"immutable-{uuid4()}",
            delta=3,
            reason="payment",
        )
        session.add(entry)
        await session.commit()
        entry_id = entry.id

    async with session_factory() as session:
        stored_entry = await session.get(TokenLedgerEntry, entry_id)
        assert stored_entry is not None
        stored_entry.delta = 4
        with pytest.raises(DBAPIError, match="token ledger entries are immutable"):
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        stored_entry = await session.get(TokenLedgerEntry, entry_id)
        assert stored_entry is not None
        assert stored_entry.delta == 3
