"""Generation admission and task-status operations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.generation import (
    GenerateRequest,
    ProviderOutcome,
    TaskHistoryEntry,
    TaskStatus,
    TaskStatusResponse,
)
from app.api.schemas.webhooks import ProviderWebhookRequest
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.providers import GenerationInput, ProviderPort, TemporaryProviderPort
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.generation_catalog_repository import (
    GenerationCatalogRepository,
)
from app.repositories.task_repository import TaskRepository
from app.repositories.token_ledger_repository import TokenLedgerRepository
from app.repositories.user_repository import UserRepository
from app.services.provider_callback_service import (
    AttemptDispatch,
    ProviderCallbackService,
)


class GenerationService:
    """Validates and persists generation work before calling the provider port."""

    def __init__(
        self, provider: ProviderPort | None = None, provider_timeout: float = 60.0
    ) -> None:
        self.users = UserRepository()
        self.catalog = GenerationCatalogRepository()
        self.tasks = TaskRepository()
        self.attempts = AttemptRepository()
        self.ledger = TokenLedgerRepository()
        self.provider = provider or TemporaryProviderPort()
        self.callbacks = ProviderCallbackService(provider_timeout)
        self.provider_timeout = provider_timeout

    async def submit(self, session: AsyncSession, request: GenerateRequest) -> UUID:
        """Admit a task and debit in one transaction, then dispatch outside it."""
        async with session.begin():
            model = await self.catalog.get_model(session, request.model)
            if model is None:
                raise HTTPException(
                    status_code=400, detail="No compatible provider leg"
                )
            legs = await self.catalog.compatible_legs(
                session, model.id, len(request.ref_images)
            )
            if not legs:
                raise HTTPException(
                    status_code=400, detail="No compatible provider leg"
                )

            user = await self.users.get_for_update(session, request.user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")

            balance = await self.ledger.balance(session, request.user_id)
            if balance < model.price_tokens:
                raise HTTPException(status_code=402, detail="Insufficient balance")
            if await self.tasks.count_active(session, request.user_id) >= 3:
                raise HTTPException(
                    status_code=429, detail="Maximum active tasks reached"
                )

            task_id = uuid4()
            attempt_id = uuid4()
            first_leg = legs[0]
            task = GenerationTask(
                id=task_id,
                user_id=request.user_id,
                generation_model_id=model.id,
                status="queued",
                current_provider_leg_id=first_leg.id,
                prompt=request.prompt,
                ref_images=[str(image) for image in request.ref_images],
            )
            await self.tasks.add(session, task)
            await self.ledger.append(
                session,
                TokenLedgerEntry(
                    user_id=request.user_id,
                    operation_key=f"generation:{task_id}:debit",
                    delta=-model.price_tokens,
                    reason="generation",
                ),
            )
            await self.attempts.add(
                session,
                GenerationAttempt(
                    id=attempt_id,
                    task_id=task_id,
                    provider_leg_id=first_leg.id,
                    attempt_no=1,
                    status="queued",
                    deadline_at=datetime.now(UTC)
                    + timedelta(seconds=self.provider_timeout),
                ),
            )
            task.current_attempt_id = attempt_id
            await session.flush()

        await self.dispatch(
            session,
            AttemptDispatch(
                provider=first_leg.provider_name,
                generation=GenerationInput(
                    task_id=task_id,
                    attempt_no=1,
                    prompt=request.prompt,
                    ref_images=tuple(str(image) for image in request.ref_images),
                ),
            ),
        )

        return task_id

    async def dispatch(self, session: AsyncSession, dispatch: AttemptDispatch) -> None:
        """Send committed work outside the transaction and record its response."""
        generation = dispatch.generation
        acceptance = await self.provider.submit(dispatch.provider, generation)
        if acceptance.status_code == 202:
            async with session.begin():
                task = await self.tasks.get_for_update(session, generation.task_id)
                attempt = await self.attempts.get_for_update(
                    session, generation.task_id, generation.attempt_no
                )
                if (
                    task is not None
                    and attempt is not None
                    and task.current_attempt_id == attempt.id
                    and task.status not in {"succeeded", "failed"}
                ):
                    task.status = "processing"
                    attempt.status = "processing"
                    attempt.external_id = acceptance.external_id
            return

        async with session.begin():
            next_dispatch = await self.callbacks.apply(
                session,
                dispatch.provider,
                ProviderWebhookRequest(
                    task_id=generation.task_id,
                    attempt_no=generation.attempt_no,
                    outcome=ProviderOutcome.TECHNICAL_ERROR,
                    error=f"sync_{acceptance.status_code}",
                ),
            )
        if next_dispatch is not None:
            await self.dispatch(session, next_dispatch)

    async def status(self, session: AsyncSession, task_id: UUID) -> TaskStatusResponse:
        """Return stored task state and provider attempt history."""
        task = await self.tasks.get(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        current_leg = (
            await self.catalog.get_leg(session, task.current_provider_leg_id)
            if task.current_provider_leg_id is not None
            else None
        )
        attempts = await self.attempts.for_task_with_providers(session, task_id)
        history = [
            TaskHistoryEntry(
                provider=provider_name,
                outcome=self._outcome(attempt),
                error=attempt.error_type,
                created_at=attempt.created_at,
            )
            for attempt, provider_name in attempts
        ]
        return TaskStatusResponse(
            task_id=task.id,
            status=TaskStatus(task.status),
            current_provider=current_leg.provider_name if current_leg else None,
            output=task.result_url,
            history=history,
        )

    @staticmethod
    def _outcome(attempt: GenerationAttempt) -> ProviderOutcome | None:
        if attempt.status == "succeeded":
            return ProviderOutcome.COMPLETED
        if attempt.error_type is not None:
            try:
                return ProviderOutcome(attempt.error_type)
            except ValueError:
                pass
        if attempt.status in {"failed", "timed_out"}:
            return ProviderOutcome.TECHNICAL_ERROR
        return None
