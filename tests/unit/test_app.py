"""Проверки bootstrap приложения."""

from app.factory import create_app
from app.settings import Settings
from fastapi.testclient import TestClient


def test_app_factory_serves_healthz() -> None:
    """Фабрика запускает приложение с доступной проверкой здоровья."""
    application = create_app(Settings(webhook_secret="test-secret"))

    with TestClient(application) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
