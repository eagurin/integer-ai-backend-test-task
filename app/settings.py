"""Конфигурация сервиса из переменных окружения."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/integer_generator"
    )
    webhook_secret: SecretStr = Field(validation_alias="WEBHOOK_SECRET")
    provider_alpha_url: str = "http://127.0.0.1:9101"
    provider_beta_url: str = "http://127.0.0.1:9102"
    provider_callback_url: str = "http://127.0.0.1:8000/webhooks/providers"
    provider_request_timeout: float = Field(default=2.0, gt=0)

    @field_validator("webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, value: SecretStr) -> SecretStr:
        """Отклоняет пустой секрет, включая строку из пробелов."""
        if not value.get_secret_value().strip():
            raise ValueError("WEBHOOK_SECRET не должен быть пустым")
        return value
