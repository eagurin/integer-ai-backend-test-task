"""Адаптеры внешних провайдеров."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ProviderAcceptance:
    """Provider submission acknowledgement used by the temporary test port."""

    status_code: int
    external_id: str


class TemporaryProviderPort:
    """Local provider-port test double, replaced by configured services in todo 6."""

    async def submit(self, provider: str, task_id: UUID) -> ProviderAcceptance:
        """Mimic an accepted provider submission without making a network call."""
        return ProviderAcceptance(
            status_code=202,
            external_id=f"temporary-{provider}-{task_id}",
        )
