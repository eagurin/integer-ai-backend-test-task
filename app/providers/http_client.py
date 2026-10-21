"""HTTP provider client and callback dispatch."""

import hashlib
import hmac
from typing import Annotated, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.providers import GenerationInput, ProviderAcceptance


class ProviderConfiguration(BaseModel):
    """Validated endpoint settings for one provider client."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    alpha_url: str = Field(min_length=1)
    beta_url: str = Field(min_length=1)
    callback_url: str = Field(min_length=1)
    webhook_secret: str = Field(min_length=1)
    request_timeout: Annotated[float, Field(gt=0)]


class ProviderError(RuntimeError):
    """A provider catalog entry has no configured service."""

    def __init__(self, provider: str) -> None:
        self.provider: str = provider
        super().__init__(f"Unknown provider: {provider}")


class _ProviderTaskResponse(BaseModel):
    """Validated response returned by a fake-provider service."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)

    external_id: str = Field(min_length=1)


class ProviderHttpClient:
    """Dispatches generation requests and signs callback configuration."""

    def __init__(
        self,
        configuration: ProviderConfiguration,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.configuration: ProviderConfiguration = configuration
        self.transport: httpx.AsyncBaseTransport | None = transport

    async def submit(
        self, provider: str, generation: GenerationInput
    ) -> ProviderAcceptance:
        """POST one attempt to the configured provider service."""
        match provider:
            case "alpha":
                base_url = self.configuration.alpha_url
            case "beta":
                base_url = self.configuration.beta_url
            case _:
                raise ProviderError(provider)

        body = {
            "task_id": str(generation.task_id),
            "attempt_no": generation.attempt_no,
            "prompt": generation.prompt,
            "ref_images": list(generation.ref_images),
            "callback_url": self.configuration.callback_url,
            "callback_secret": self.configuration.webhook_secret,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.configuration.request_timeout),
                transport=self.transport,
            ) as client:
                response = await client.post(f"{base_url}/tasks", json=body)
        except httpx.RequestError:
            return ProviderAcceptance(status_code=503, external_id=None)
        if response.status_code != 202:
            return ProviderAcceptance(
                status_code=response.status_code, external_id=None
            )
        try:
            result = _ProviderTaskResponse.model_validate_json(response.content)
        except ValidationError:
            return ProviderAcceptance(status_code=502, external_id=None)
        return ProviderAcceptance(status_code=202, external_id=result.external_id)


def callback_signature(secret: str, raw_body: bytes) -> str:
    """Sign exact callback bytes using the provider webhook contract."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
