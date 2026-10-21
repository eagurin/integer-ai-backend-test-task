"""PostgreSQL-backed persistence and failover transport input contract."""

from uuid import UUID

from app.models.generation_task import GenerationTask
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.provider_helpers import (
    SequenceProvider,
    client_for,
    close_client,
    funded_user,
)


async def test_failover_reuses_persisted_generation_input(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each ordered leg receives the persisted original prompt and references."""
    user_id = await funded_user(session_factory)
    provider = SequenceProvider([503, 202])
    client, cleanup, _ = await client_for(session_factory, provider)
    prompt = "A mountain valley at dawn"
    ref_images = ["https://example.com/reference.png"]
    try:
        response = await client.post(
            "/generate",
            json={
                "user_id": str(user_id),
                "model": "image-fast",
                "prompt": prompt,
                "ref_images": ref_images,
            },
        )
        assert response.status_code == 202
        task_id = UUID(response.json()["task_id"])
        async with session_factory() as session:
            task = await session.get(GenerationTask, task_id)
        assert task is not None
        assert task.prompt == prompt
        assert task.ref_images == ref_images
        assert [item[1].prompt for item in provider.calls] == [prompt, prompt]
        assert [item[1].ref_images for item in provider.calls] == [
            tuple(ref_images),
            tuple(ref_images),
        ]
        assert [item[1].attempt_no for item in provider.calls] == [1, 2]
    finally:
        await close_client(client, cleanup)
