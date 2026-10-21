"""Конфигурация сервиса из переменных окружения."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", validate_default=True
    )

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/integer_generator"
    )
    webhook_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="WEBHOOK_SECRET"
    )
    provider_alpha_url: str = "http://127.0.0.1:9101"
    provider_beta_url: str = "http://127.0.0.1:9102"
    provider_callback_url: str = "http://127.0.0.1:8000/webhooks/providers"
    provider_request_timeout: float = Field(default=2.0, gt=0)
    provider_timeout: float = Field(
        default=60.0, gt=0, validation_alias="PROVIDER_TIMEOUT"
    )
    watchdog_poll_interval_seconds: float = Field(
        default=1.0, gt=0, validation_alias="WATCHDOG_POLL_INTERVAL_SECONDS"
    )
    watchdog_batch_size: int = Field(
        default=50, gt=0, validation_alias="WATCHDOG_BATCH_SIZE"
    )

    @field_validator("webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, value: SecretStr) -> SecretStr:
        """Отклоняет пустой секрет, включая строку из пробелов."""
        if not value.get_secret_value().strip():
            raise ValueError("WEBHOOK_SECRET не должен быть пустым")
        return value
