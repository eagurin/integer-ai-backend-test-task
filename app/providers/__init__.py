"""Адаптеры внешних провайдеров."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ProviderAcceptance:
    """Provider submission acknowledgement."""

    status_code: int
    external_id: str | None


@dataclass(frozen=True)
class GenerationInput:
    """Generation data shared by all provider legs."""

    task_id: UUID
    attempt_no: int
    prompt: str
    ref_images: tuple[str, ...]


class ProviderPort(Protocol):
    """Async boundary for dispatching work to a named provider."""

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance: ...


class TemporaryProviderPort:
    """Deterministic provider port used by integration tests."""

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """Mimic acceptance without making a network call."""
        return ProviderAcceptance(
            status_code=202,
            external_id=f"temporary-{provider}-{generation.task_id}",
        )


__all__ = [
    "GenerationInput",
    "ProviderAcceptance",
    "ProviderPort",
    "TemporaryProviderPort",
]
