"""Deterministic failure and callback configuration for fake providers."""

import anyio
import httpx
import pytest
from app.api.schemas.generation import ProviderOutcome
from app.providers import fake_app
from app.providers.fake_app import (
    CallbackDelivery,
    FakeProviderSettings,
    SyncFailure,
    create_fake_provider_app,
)

TASK_ID = "ed89a1e6-4806-4e0d-8a12-7b90b2ee878f"
REQUEST_BODY = {
    "task_id": TASK_ID,
    "attempt_no": 1,
    "prompt": "fake-provider config",
    "ref_images": [],
    "callback_url": "http://api.test/webhooks/providers",
    "callback_secret": "fake-provider-secret",
}


async def post_task(settings: FakeProviderSettings) -> httpx.Response:
    """Drive the fake provider's public task endpoint."""
    application = create_fake_provider_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://provider.test",
    ) as client:
        return await client.post("/tasks", json=REQUEST_BODY)


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (0.0, ProviderOutcome.COMPLETED),
        (1.0, ProviderOutcome.TECHNICAL_ERROR),
    ],
)
async def test_failure_probability_selects_configured_outcome(
    probability: float,
    expected: ProviderOutcome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Endpoint probabilities deterministically select success or failure."""
    captured: list[CallbackDelivery] = []

    async def capture(delivery: CallbackDelivery) -> None:
        captured.append(delivery)

    monkeypatch.setattr(fake_app, "_send_callback", capture)
    response = await post_task(
        FakeProviderSettings(
            provider_name="alpha",
            failure_type=ProviderOutcome.TECHNICAL_ERROR,
            failure_probability=probability,
            callback_delay_seconds=0,
            late_completion_seconds=12,
        )
    )
    assert response.status_code == 202
    assert len(captured) == 1
    assert captured[0].payload.outcome == expected
    assert captured[0].delay == 12


async def test_omitted_callback_configuration_sends_no_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The omitted-callback mode accepts work without scheduling a callback."""
    captured: list[CallbackDelivery] = []

    async def capture(delivery: CallbackDelivery) -> None:
        captured.append(delivery)

    monkeypatch.setattr(fake_app, "_send_callback", capture)
    response = await post_task(
        FakeProviderSettings(provider_name="beta", omit_callback=True)
    )
    assert response.status_code == 202
    assert captured == []


async def test_duplicate_callbacks_run_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate mode overlaps both callback deliveries before completion."""
    both_started = anyio.Event()
    active = 0
    max_active = 0

    async def capture(delivery: CallbackDelivery) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if active == 2:
            both_started.set()
        await both_started.wait()
        active -= 1

    monkeypatch.setattr(fake_app, "_send_callback", capture)
    with anyio.fail_after(5):
        response = await post_task(
            FakeProviderSettings(
                provider_name="alpha",
                duplicate_callbacks=True,
                callback_delay_seconds=0,
            )
        )
    assert response.status_code == 202
    assert max_active == 2


@pytest.mark.parametrize(
    ("sync_failure", "expected_status"),
    [
        (SyncFailure.SERVICE_UNAVAILABLE, 503),
        (SyncFailure.TIMEOUT, 504),
    ],
)
async def test_sync_failure_modes_return_configured_status(
    sync_failure: SyncFailure,
    expected_status: int,
) -> None:
    """Synchronous unavailable and timeout modes are externally distinguishable."""
    response = await post_task(
        FakeProviderSettings(
            provider_name="alpha",
            sync_failure=sync_failure,
            sync_timeout_seconds=0.001,
        )
    )
    assert response.status_code == expected_status
