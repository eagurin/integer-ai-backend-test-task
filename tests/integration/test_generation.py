"""PostgreSQL-backed generation admission and task-history behavior."""

import json
from contextlib import AsyncExitStack
from uuid import UUID, uuid4

import anyio
import httpx
import pytest
from app.api.controllers.generation import service
from app.factory import create_app
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_model import GenerationModel
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.models.user import User
from app.settings import Settings
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def client_for(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[httpx.AsyncClient, AsyncExitStack]:
    """Create an ASGI client using the migrated PostgreSQL database."""
    application = create_app(Settings(webhook_secret=SecretStr("generation-secret")))
    cleanup = AsyncExitStack()
    await cleanup.enter_async_context(application.router.lifespan_context(application))
    application.state.session_factory = session_factory
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    )
    return client, cleanup


async def close_client(client: httpx.AsyncClient, cleanup: AsyncExitStack) -> None:
    """Close the HTTP client and application lifespan."""
    await client.aclose()
    await cleanup.aclose()


async def add_funded_user(
    session_factory: async_sessionmaker[AsyncSession], balance: int = 100
) -> UUID:
    """Create one user with a ledger-derived initial balance."""
    user_id = uuid4()
    async with session_factory() as session:
        session.add(User(id=user_id))
        await session.flush()
        session.add(
            TokenLedgerEntry(
                user_id=user_id,
                operation_key=f"test-funding:{user_id}",
                delta=balance,
                reason="payment",
            )
        )
        await session.commit()
    return user_id


async def user_counts(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> tuple[int, int, int, int]:
    """Return ledger, task, and attempt row counts plus the derived balance."""
    async with session_factory() as session:
        ledger_count = await session.scalar(
            select(func.count())
            .select_from(TokenLedgerEntry)
            .where(TokenLedgerEntry.user_id == user_id)
        )
        task_count = await session.scalar(
            select(func.count())
            .select_from(GenerationTask)
            .where(GenerationTask.user_id == user_id)
        )
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(GenerationAttempt)
            .join(GenerationTask, GenerationTask.id == GenerationAttempt.task_id)
            .where(GenerationTask.user_id == user_id)
        )
        balance = await session.scalar(
            select(func.coalesce(func.sum(TokenLedgerEntry.delta), 0)).where(
                TokenLedgerEntry.user_id == user_id
            )
        )
    return (
        int(ledger_count or 0),
        int(task_count or 0),
        int(attempt_count or 0),
        int(balance or 0),
    )


async def post_image_generation(
    client: httpx.AsyncClient, user_id: UUID
) -> httpx.Response:
    """Submit one compatible image generation request."""
    return await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model": "image-fast",
            "prompt": "A geometric landscape",
            "ref_images": [],
        },
    )


async def test_valid_request_debits_once_and_returns_task_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A valid request commits one debit, task, and accepted first attempt."""
    user_id = await add_funded_user(session_factory)
    client, cleanup = await client_for(session_factory)
    try:
        response = await post_image_generation(client, user_id)
        assert response.status_code == 202
        task_id = UUID(response.json()["task_id"])

        ledger_count, task_count, attempt_count, balance = await user_counts(
            session_factory, user_id
        )
        assert (ledger_count, task_count, attempt_count, balance) == (2, 1, 1, 98)

        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
            attempt = await session.scalar(
                select(GenerationAttempt).where(
                    GenerationAttempt.task_id == task_id,
                    GenerationAttempt.attempt_no == 1,
                )
            )
            debit = await session.scalar(
                select(TokenLedgerEntry).where(
                    TokenLedgerEntry.operation_key == f"generation:{task_id}:debit"
                )
            )

        assert task is not None
        assert task.status == "processing"
        assert task.current_provider_leg_id is not None
        assert attempt is not None
        assert task.current_attempt_id == attempt.id
        assert attempt.status == "processing"
        assert attempt.external_id == f"temporary-alpha-{task_id}"
        assert debit is not None
        assert debit.delta == -2
        assert response.json() == {"task_id": str(task_id)}
    finally:
        await close_client(client, cleanup)


async def test_task_status_includes_attempt_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Task status includes its active provider and timestamped attempt."""
    user_id = await add_funded_user(session_factory)
    client, cleanup = await client_for(session_factory)
    try:
        accepted = await post_image_generation(client, user_id)
        task_id = accepted.json()["task_id"]

        response = await client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == task_id
        assert body["status"] == "processing"
        assert body["current_provider"] == "alpha"
        assert body["output"] is None
        assert len(body["history"]) == 1
        history = body["history"][0]
        assert history["provider"] == "alpha"
        assert history["outcome"] is None
        assert history["error"] is None
        assert history["created_at"]
    finally:
        await close_client(client, cleanup)


async def test_unknown_user_returns_404_without_debit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unknown users create neither a debit nor task/attempt rows."""
    user_id = uuid4()
    before = await user_counts(session_factory, user_id)
    client, cleanup = await client_for(session_factory)
    try:
        response = await post_image_generation(client, user_id)
        assert response.status_code == 404
        assert await user_counts(session_factory, user_id) == before
    finally:
        await close_client(client, cleanup)


async def test_no_compatible_leg_returns_400_without_debit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reference counts incompatible with every leg are rejected before writes."""
    user_id = await add_funded_user(session_factory)
    before = await user_counts(session_factory, user_id)
    client, cleanup = await client_for(session_factory)
    try:
        response = await client.post(
            "/generate",
            json={
                "user_id": str(user_id),
                "model": "video-long",
                "prompt": "A long cinematic scene",
                "ref_images": [
                    "https://example.com/one.png",
                    "https://example.com/two.png",
                    "https://example.com/three.png",
                ],
            },
        )
        assert response.status_code == 400
        assert await user_counts(session_factory, user_id) == before
    finally:
        await close_client(client, cleanup)


async def test_malformed_reference_returns_422_without_writes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Invalid reference URLs retain the raw-body validation response."""
    user_id = await add_funded_user(session_factory)
    before = await user_counts(session_factory, user_id)
    client, cleanup = await client_for(session_factory)
    try:
        body = json.dumps(
            {
                "user_id": str(user_id),
                "model": "image-fast",
                "prompt": "A geometric landscape",
                "ref_images": ["not-a-url"],
            }
        ).encode()
        response = await client.post(
            "/generate",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert await user_counts(session_factory, user_id) == before
    finally:
        await close_client(client, cleanup)


async def test_fourth_active_task_returns_429_without_debit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Three existing queued tasks prevent a fourth task and any ledger write."""
    user_id = await add_funded_user(session_factory)
    async with session_factory() as session:
        model = await session.scalar(
            select(GenerationModel).where(GenerationModel.key == "image-fast")
        )
        assert model is not None
        session.add_all(
            GenerationTask(
                user_id=user_id,
                generation_model_id=model.id,
                status="queued",
            )
            for _ in range(3)
        )
        await session.commit()
    before = await user_counts(session_factory, user_id)

    client, cleanup = await client_for(session_factory)
    try:
        response = await post_image_generation(client, user_id)
        assert response.status_code == 429
        assert await user_counts(session_factory, user_id) == before
    finally:
        await close_client(client, cleanup)


async def test_concurrent_requests_serialize_balance_checks(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate request sessions cannot spend the same final balance twice."""
    user_id = await add_funded_user(session_factory, balance=2)
    client, cleanup = await client_for(session_factory)
    barrier = anyio.Event()
    arrivals = 0
    get_for_update = service.users.get_for_update

    async def synchronize_before_lock(
        session: AsyncSession, requested_user_id: UUID
    ) -> User | None:
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            barrier.set()
        await barrier.wait()
        return await get_for_update(session, requested_user_id)

    monkeypatch.setattr(service.users, "get_for_update", synchronize_before_lock)
    try:
        responses: list[httpx.Response] = []

        async def post_generation() -> None:
            responses.append(await post_image_generation(client, user_id))

        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(post_generation)
                task_group.start_soon(post_generation)
        assert sorted(response.status_code for response in responses) == [202, 402]
        assert await user_counts(session_factory, user_id) == (2, 1, 1, 0)
    finally:
        await close_client(client, cleanup)
