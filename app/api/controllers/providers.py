"""Signed provider callback endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.webhooks import ProviderWebhookRequest
from app.database import get_session
from app.dependencies import get_generation_service
from app.security import verify_webhook_signature
from app.services.generation_service import GenerationService
from app.settings import Settings

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ProviderName = Literal["alpha", "beta"]
GenerationServiceDependency = Annotated[
    GenerationService, Depends(get_generation_service)
]


@router.post("/webhooks/providers/{provider_name}", status_code=204)
async def provider_webhook(
    provider_name: ProviderName,
    request: Request,
    session: SessionDependency,
    service: GenerationServiceDependency,
    signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> Response:
    """Validate raw-body HMAC before atomically applying an outcome."""
    raw_body = await request.body()
    settings: Settings = request.app.state.settings
    if not verify_webhook_signature(
        raw_body, signature, settings.webhook_secret.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        event = ProviderWebhookRequest.model_validate_json(raw_body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error

    async with session.begin():
        dispatch = await service.callbacks.apply(session, provider_name, event)
    if dispatch is not None:
        await service.dispatch(session, dispatch)
    return Response(status_code=204)
