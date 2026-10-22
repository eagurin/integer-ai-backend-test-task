"""Static Compose dependency and database-isolation contracts."""

from pathlib import Path
from typing import ClassVar, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DATABASE_URL: Final[str] = "postgresql+asyncpg://postgres:postgres@"


class Dependency(BaseModel):
    """One explicit Compose startup dependency."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    condition: Literal[
        "service_started",
        "service_healthy",
        "service_completed_successfully",
    ]


class Healthcheck(BaseModel):
    """A configured healthcheck command."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    test: str | list[str]


class Service(BaseModel):
    """The Compose fields relevant to startup and database isolation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    command: str | list[str] | None = None
    depends_on: dict[str, Dependency] | None = None
    environment: dict[str, str] | None = None
    healthcheck: Healthcheck | None = None
    profiles: list[str] | None = None
    container_name: str | None = None


class ComposeDocument(BaseModel):
    """Parsed Compose service map."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    services: dict[str, Service]


def load_compose() -> ComposeDocument:
    """Parse the repository Compose file into the fields this contract uses."""
    compose_file = ROOT / "compose.yaml"
    return ComposeDocument.model_validate(yaml.safe_load(compose_file.read_text()))


def test_api_requires_healthy_database_and_completed_migration() -> None:
    """API startup waits for a healthy DB and successful Alembic migration."""
    services = load_compose().services

    assert services["api"].depends_on == {
        "db": Dependency(condition="service_healthy"),
        "migrate": Dependency(condition="service_completed_successfully"),
        "alpha": Dependency(condition="service_healthy"),
        "beta": Dependency(condition="service_healthy"),
    }
    assert services["migrate"].depends_on == {
        "db": Dependency(condition="service_healthy")
    }
    command = services["api"].command
    assert isinstance(command, list)
    assert command[command.index("--workers") + 1] == "4"


def test_test_profile_migrates_and_uses_a_separate_database() -> None:
    """Test migrations and fixtures target only their isolated PostgreSQL DB."""
    services = load_compose().services
    app_environment = services["api"].environment
    test_environment = services["tests"].environment
    migration_environment = services["test-migrate"].environment
    assert app_environment is not None
    assert test_environment is not None
    assert migration_environment is not None
    app_database_url = app_environment["DATABASE_URL"]
    test_database_url = test_environment["DATABASE_URL"]

    assert app_database_url.startswith(DATABASE_URL)
    assert test_database_url.startswith(DATABASE_URL)
    assert app_database_url != test_database_url
    assert app_database_url.endswith("/integer_generator")
    assert test_database_url.endswith("/integer_generator_test")
    assert migration_environment["DATABASE_URL"] == test_database_url
    assert services["test-db"].profiles == ["test"]
    assert services["test-migrate"].profiles == ["test"]
    assert services["tests"].profiles == ["test"]
    assert services["test-migrate"].depends_on == {
        "test-db": Dependency(condition="service_healthy")
    }
    assert services["tests"].depends_on == {
        "test-migrate": Dependency(condition="service_completed_successfully")
    }


def test_compose_services_allow_replication() -> None:
    """No service pins a container name and blocks Compose replication."""
    services = load_compose().services
    assert all(service.container_name is None for service in services.values())
    assert services["db"].healthcheck is not None
    assert services["test-db"].healthcheck is not None
    assert services["api"].healthcheck is not None
    assert services["alpha"].healthcheck is not None
    assert services["beta"].healthcheck is not None
