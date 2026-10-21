"""HTTP failure mapping for the outbound provider client."""

from uuid import UUID

import httpx
from app.providers import GenerationInput
from app.providers.http_client import ProviderConfiguration, ProviderHttpClient

TASK_ID = UUID("ed89a1e6-4806-4e0d-8a12-7b90b2ee878f")


def provider_client(transport: httpx.AsyncBaseTransport) -> ProviderHttpClient:
    """Create a provider client with explicit test endpoints."""
    return ProviderHttpClient(
        ProviderConfiguration(
            alpha_url="http://alpha.test",
            beta_url="http://beta.test",
            callback_url="http://api.test/webhooks/providers",
            webhook_secret="provider-test-secret",
            request_timeout=1,
        ),
        transport=transport,
    )


def generation_input() -> GenerationInput:
    """Return a stable generation dispatch payload."""
    return GenerationInput(
        task_id=TASK_ID,
        attempt_no=1,
        prompt="Provider timeout test",
        ref_images=(),
    )


async def test_provider_http_503_becomes_retryable_acceptance() -> None:
    """Given a provider 503, When dispatching, Then report technical failure."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, request=request)
    )
    client = provider_client(transport)
    acceptance = await client.submit("alpha", generation_input())
    assert acceptance.status_code == 503
    assert acceptance.external_id is None


async def test_provider_http_timeout_becomes_retryable_acceptance() -> None:
    """Given a provider timeout, When dispatching, Then report technical failure."""

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("provider did not answer", request=request)

    client = provider_client(httpx.MockTransport(timeout))
    acceptance = await client.submit("alpha", generation_input())
    assert acceptance.status_code == 503
    assert acceptance.external_id is None
