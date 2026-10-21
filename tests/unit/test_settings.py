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
        Settings()


def test_rejects_invalid_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой секрет не принимается как допустимая конфигурация."""
    monkeypatch.setenv("WEBHOOK_SECRET", "   ")

    with pytest.raises(ValidationError):
        Settings()


def test_watchdog_settings_are_configurable_with_bounded_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchdog uses safe defaults and accepts environment overrides."""
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    for key in (
        "WATCHDOG_POLL_INTERVAL_SECONDS",
        "WATCHDOG_BATCH_SIZE",
        "PROVIDER_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)

    defaults = Settings()
    assert defaults.watchdog_poll_interval_seconds == 1
    assert defaults.watchdog_batch_size == 50
    assert defaults.provider_timeout == 60

    monkeypatch.setenv("WATCHDOG_POLL_INTERVAL_SECONDS", "0.25")
    monkeypatch.setenv("WATCHDOG_BATCH_SIZE", "7")
    monkeypatch.setenv("PROVIDER_TIMEOUT", "17")
    configured = Settings()
    assert configured.watchdog_poll_interval_seconds == 0.25
    assert configured.watchdog_batch_size == 7
    assert configured.provider_timeout == 17
