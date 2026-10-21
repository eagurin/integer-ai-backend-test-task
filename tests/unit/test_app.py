"""Проверки bootstrap приложения."""

from app.factory import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from pydantic import SecretStr


def test_app_factory_serves_healthz() -> None:
    """Фабрика запускает приложение с доступной проверкой здоровья."""
    application = create_app(Settings(webhook_secret=SecretStr("test-secret")))

    with TestClient(application) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_exposes_generation_request_fields() -> None:
    """The published operation schema matches the generation request contract."""
    application = create_app(Settings(webhook_secret=SecretStr("test-secret")))

    with TestClient(application) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    operation = document["paths"]["/generate"]["post"]
    request_body = operation["requestBody"]
    schema = request_body["content"]["application/json"]["schema"]

    assert request_body["required"] is True
    assert set(schema["properties"]) == {
        "user_id",
        "model",
        "prompt",
        "ref_images",
    }
    assert set(schema["required"]) == {"user_id", "model", "prompt"}
