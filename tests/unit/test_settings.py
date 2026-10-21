"""Проверки обязательной конфигурации."""

import pytest
from app.settings import Settings
from pydantic import ValidationError


def test_rejects_missing_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Настройки без обязательного секрета не создаются."""
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_rejects_invalid_webhook_secret() -> None:
    """Пустой секрет не принимается как допустимая конфигурация."""
    with pytest.raises(ValidationError):
        Settings(webhook_secret="   ", _env_file=None)
