"""PostgreSQL assertions for the migrated generation catalog."""

from app.models.generation_model import GenerationModel, ProviderLeg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_catalog_has_exact_seed_models_and_ordered_legs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The live database contains exactly the requested prices and routes."""
    async with session_factory() as session:
        models_result = await session.execute(
            select(GenerationModel).order_by(GenerationModel.key)
        )
        models = list(models_result.scalars())
        assert [(model.key, model.price_tokens) for model in models] == [
            ("image-fast", 2),
            ("video-long", 25),
        ]

        legs_result = await session.execute(
            select(ProviderLeg, GenerationModel.key)
            .join(GenerationModel)
            .order_by(GenerationModel.key, ProviderLeg.priority)
        )
        legs = [
            (
                model_key,
                leg.provider_name,
                leg.priority,
                leg.max_refs,
                leg.skip_on_moderation,
            )
            for leg, model_key in legs_result
        ]

    assert legs == [
        ("image-fast", "alpha", 1, 4, False),
        ("image-fast", "beta", 2, 10, False),
        ("video-long", "beta", 1, 2, False),
        ("video-long", "alpha", 2, 1, True),
    ]
