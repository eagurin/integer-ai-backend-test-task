"""Shared fixtures for provider callback integration scenarios."""

import hashlib
import hmac
import json
from contextlib import AsyncExitStack
from uuid import UUID, uuid4

import httpx
from app.factory import create_app
from app.models.token_ledger_entry import TokenLedgerEntry
from app.models.user import User
from app.providers import (
    GenerationInput,
    ProviderAcceptance,
    ProviderPort,
    TemporaryProviderPort,
)
from app.services.generation_service import GenerationService
from app.settings import Settings
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SECRET = "provider-integration-secret"


def sign(body: bytes) -> str:
    """Create a valid lowercase raw-body callback signature."""
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


async def client_for(
    session_factory: async_sessionmaker[AsyncSession],
    provider: ProviderPort | None = None,
) -> tuple[httpx.AsyncClient, AsyncExitStack, GenerationService]:
    """Create an API client wired to the migrated PostgreSQL database."""
    application = create_app(Settings(webhook_secret=SecretStr(SECRET)))
    cleanup = AsyncExitStack()
    await cleanup.enter_async_context(application.router.lifespan_context(application))
    application.state.session_factory = session_factory
    service = GenerationService(provider or TemporaryProviderPort())
    application.state.generation_service = service
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    )
    return client, cleanup, service


async def close_client(client: httpx.AsyncClient, cleanup: AsyncExitStack) -> None:
    """Release client and application resources."""
    await client.aclose()
    await cleanup.aclose()


async def funded_user(
    session_factory: async_sessionmaker[AsyncSession], balance: int = 100
) -> UUID:
    """Create a user with a single immutable funding ledger row."""
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


async def generate(
    client: httpx.AsyncClient, user_id: UUID, model: str = "image-fast"
) -> UUID:
    """Submit a generation and return its accepted task identifier."""
    response = await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model": model,
            "prompt": "A test landscape",
            "ref_images": [],
        },
    )
    assert response.status_code == 202
    return UUID(response.json()["task_id"])


async def callback(
    client: httpx.AsyncClient,
    task_id: UUID,
    attempt_no: int,
    provider: str,
    outcome: str,
) -> httpx.Response:
    """Post one signed provider result to the real API route."""
    event = {
        "task_id": str(task_id),
        "attempt_no": attempt_no,
        "outcome": outcome,
        "output": "https://provider.example/result.png"
        if outcome == "completed"
        else None,
        "error": None if outcome == "completed" else outcome,
    }
    body = json.dumps(event, separators=(",", ":")).encode()
    return await client.post(
        f"/webhooks/providers/{provider}",
        content=body,
        headers={"X-Signature": sign(body)},
    )


class SequenceProvider:
    """Deterministic provider port for synchronous failure tests."""

    def __init__(self, results: list[int]) -> None:
        self.results = results
        self.calls: list[tuple[str, GenerationInput]] = []

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """Return the next configured HTTP status in dispatch order."""
        self.calls.append((provider, generation))
        status_code = self.results.pop(0)
        return ProviderAcceptance(
            status_code=status_code,
            external_id=f"{provider}-{generation.task_id}"
            if status_code == 202
            else None,
        )
