"""Configurable alpha/beta fake-provider HTTP application."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, ClassVar, Literal
from uuid import UUID, uuid4

import anyio
import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.api.schemas.generation import ProviderOutcome
from app.providers.http_client import callback_signature


class SyncFailure(StrEnum):
    """Synchronous failure modes for provider task submission."""

    NONE = "none"
    SERVICE_UNAVAILABLE = "503"
    TIMEOUT = "timeout"


class FakeProviderSettings(BaseSettings):
    """Environment configuration for one fake provider process."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", extra="ignore"
    )

    provider_name: Literal["alpha", "beta"] = "alpha"
    failure_type: ProviderOutcome = ProviderOutcome.COMPLETED
    failure_probability: Annotated[float, Field(ge=0, le=1)] = 0
    sync_failure: SyncFailure = SyncFailure.NONE
    sync_timeout_seconds: Annotated[float, Field(gt=0)] = 5
    callback_delay_seconds: Annotated[float, Field(ge=0, le=20)] = 2
    duplicate_callbacks: bool = False
    omit_callback: bool = False
    late_completion_seconds: Annotated[float | None, Field(gt=0)] = None


class FakeTaskRequest(BaseModel):
    """Generation request accepted by the fake provider service."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    task_id: UUID
    attempt_no: Annotated[int, Field(gt=0)] = 1
    prompt: Annotated[str, Field(min_length=1, max_length=10000)]
    ref_images: list[str] = Field(max_length=10)
    callback_url: str = Field(min_length=1)
    callback_secret: str = Field(min_length=1)


class FakeTaskResponse(BaseModel):
    """Accepted fake-provider task response."""

    external_id: str


class _Callback(BaseModel):
    """Provider outcome callback body."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    task_id: UUID
    attempt_no: Annotated[int, Field(gt=0)]
    outcome: ProviderOutcome
    output: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CallbackDelivery:
    """One signed callback scheduled for a provider task."""

    endpoint: str
    secret: str
    payload: _Callback
    delay: float


async def _send_callback(delivery: CallbackDelivery) -> None:
    """Send one signed callback after the configured completion delay."""
    await anyio.sleep(delivery.delay)
    body = delivery.payload.model_dump_json().encode()
    async with httpx.AsyncClient(timeout=httpx.Timeout(5)) as client:
        await client.post(
            delivery.endpoint,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": callback_signature(delivery.secret, body),
            },
        )


async def _complete_task(
    settings: FakeProviderSettings, request: FakeTaskRequest
) -> None:
    """Apply deterministic configured outcome and deliver callbacks."""
    if settings.omit_callback:
        return
    # Probability endpoints make deterministic scenarios available without
    # sleeps or external state in tests.
    outcome = settings.failure_type
    if settings.failure_probability == 0:
        outcome = ProviderOutcome.COMPLETED
    elif settings.failure_probability < 1:
        import random

        if random.random() >= settings.failure_probability:
            outcome = ProviderOutcome.COMPLETED
    delay = settings.late_completion_seconds or settings.callback_delay_seconds
    callback = _Callback(
        task_id=request.task_id,
        attempt_no=request.attempt_no,
        outcome=outcome,
        output="https://provider.example/result.png"
        if outcome == ProviderOutcome.COMPLETED
        else None,
        error=None if outcome == ProviderOutcome.COMPLETED else outcome.value,
    )
    if settings.duplicate_callbacks:
        delivery = CallbackDelivery(
            endpoint=f"{request.callback_url.rstrip('/')}/{settings.provider_name}",
            secret=request.callback_secret,
            payload=callback,
            delay=delay,
        )
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(_send_callback, delivery)
            task_group.start_soon(_send_callback, delivery)
    else:
        await _send_callback(
            CallbackDelivery(
                endpoint=(
                    f"{request.callback_url.rstrip('/')}/{settings.provider_name}"
                ),
                secret=request.callback_secret,
                payload=callback,
                delay=delay,
            )
        )


def create_fake_provider_app(
    settings: FakeProviderSettings | None = None,
) -> FastAPI:
    """Create one alpha or beta provider FastAPI application."""
    config = settings or FakeProviderSettings()
    application = FastAPI(title=f"Fake provider {config.provider_name}")

    @application.post(
        "/tasks",
        response_model=FakeTaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_task(
        payload: FakeTaskRequest, background_tasks: BackgroundTasks
    ) -> FakeTaskResponse:
        """Accept work or expose the configured synchronous failure."""
        match config.sync_failure:
            case SyncFailure.NONE:
                pass
            case SyncFailure.SERVICE_UNAVAILABLE:
                raise HTTPException(status_code=503, detail="Provider unavailable")
            case SyncFailure.TIMEOUT:
                await anyio.sleep(config.sync_timeout_seconds)
                raise HTTPException(status_code=504, detail="Provider timed out")
            case unreachable:
                from typing import assert_never

                assert_never(unreachable)
        background_tasks.add_task(_complete_task, config, payload)
        return FakeTaskResponse(external_id=f"{config.provider_name}-{uuid4()}")

    return application
