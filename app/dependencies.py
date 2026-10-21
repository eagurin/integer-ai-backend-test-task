"""Typed application dependencies."""

from fastapi import HTTPException, Request, status

from app.services.generation_service import GenerationService


def get_generation_service(request: Request) -> GenerationService:
    """Retrieve the app-scoped service and narrow its dynamic ASGI state."""
    service = request.app.state.generation_service
    if not isinstance(service, GenerationService):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Generation service is unavailable",
        )
    return service
