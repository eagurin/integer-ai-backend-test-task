"""Generation model catalog queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_model import GenerationModel, ProviderLeg


class GenerationCatalogRepository:
    """Reads model prices and compatible provider legs in priority order."""

    async def get_model(
        self, session: AsyncSession, model_key: str
    ) -> GenerationModel | None:
        """Return a catalog model by its public key."""
        result = await session.execute(
            select(GenerationModel).where(GenerationModel.key == model_key)
        )
        return result.scalar_one_or_none()

    async def get_model_by_id(
        self, session: AsyncSession, model_id: UUID
    ) -> GenerationModel | None:
        """Return a catalog model by its primary key."""
        return await session.get(GenerationModel, model_id)

    async def compatible_legs(
        self, session: AsyncSession, model_id: UUID, reference_count: int
    ) -> list[ProviderLeg]:
        """Return legs accepting this reference count in configured order."""
        result = await session.execute(
            select(ProviderLeg)
            .where(
                ProviderLeg.generation_model_id == model_id,
                ProviderLeg.max_refs >= reference_count,
            )
            .order_by(ProviderLeg.priority)
        )
        return list(result.scalars())
