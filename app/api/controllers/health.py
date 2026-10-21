"""Проверка готовности сервиса."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def health_check() -> dict[str, str]:
    """Возвращает состояние работающего приложения."""
    return {"status": "ok"}
