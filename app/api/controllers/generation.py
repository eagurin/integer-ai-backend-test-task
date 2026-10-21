"""Generation admission and task-status endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.generation import (
    GenerateRequest,
    GenerateResponse,
    TaskStatusResponse,
)
from app.database import get_session
from app.dependencies import get_generation_service
from app.services.generation_service import GenerationService

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
GenerationServiceDependency = Annotated[
    GenerationService, Depends(get_generation_service)
]


@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": GenerateRequest.model_json_schema(),
                }
            },
            "required": True,
        }
    },
)
async def generate(
    request: Request,
    session: SessionDependency,
    service: GenerationServiceDependency,
) -> GenerateResponse:
    """Create one new generation order and return its task identifier."""
    try:
        generation_request = GenerateRequest.model_validate_json(await request.body())
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    return GenerateResponse(task_id=await service.submit(session, generation_request))


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: UUID, session: SessionDependency, service: GenerationServiceDependency
) -> TaskStatusResponse:
    """Return current task state and timestamped provider attempts."""
    return await service.status(session, task_id)
