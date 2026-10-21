"""Композиционный корень и фабрика FastAPI."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.controllers.generation import router as generation_router
from app.api.controllers.health import router as health_router
from app.api.controllers.payments import router as payments_router
from app.api.controllers.providers import router as providers_router
from app.database import create_engine, create_session_factory
from app.providers.http_client import ProviderConfiguration, ProviderHttpClient
from app.services.generation_service import GenerationService
from app.settings import Settings
from app.workers.watchdog import Watchdog


def create_app(
    settings: Settings | None = None, *, start_watchdog: bool = False
) -> FastAPI:
    """Создаёт приложение и связывает его инфраструктурные зависимости."""
    app_settings = settings or Settings()
    engine: AsyncEngine = create_engine(app_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        application.state.settings = app_settings
        application.state.engine = engine
        session_factory = create_session_factory(engine)
        application.state.session_factory = session_factory
        generation_service = GenerationService(
            ProviderHttpClient(
                ProviderConfiguration(
                    alpha_url=app_settings.provider_alpha_url,
                    beta_url=app_settings.provider_beta_url,
                    callback_url=app_settings.provider_callback_url,
                    webhook_secret=app_settings.webhook_secret.get_secret_value(),
                    request_timeout=app_settings.provider_request_timeout,
                )
            ),
            provider_timeout=app_settings.provider_timeout,
        )
        application.state.generation_service = generation_service
        watchdog = Watchdog(
            session_factory,
            generation_service,
            batch_size=app_settings.watchdog_batch_size,
        )
        application.state.watchdog = watchdog
        if start_watchdog:
            async with anyio.create_task_group() as task_group:
                _ = task_group.start_soon(
                    watchdog.run_forever,
                    app_settings.watchdog_poll_interval_seconds,
                )
                try:
                    yield
                finally:
                    task_group.cancel_scope.cancel()
        else:
            yield
        await engine.dispose()

    application = FastAPI(title="Integer Generator Service", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(generation_router)
    application.include_router(payments_router)
    application.include_router(providers_router)
    return application
