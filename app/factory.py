"""Композиционный корень и фабрика FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.controllers.health import router as health_router
from app.database import create_engine, create_session_factory
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение и связывает его инфраструктурные зависимости."""
    app_settings = settings or Settings()
    engine: AsyncEngine = create_engine(app_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = app_settings
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        yield
        await engine.dispose()

    application = FastAPI(title="Integer Generator Service", lifespan=lifespan)
    application.include_router(health_router)
    return application
