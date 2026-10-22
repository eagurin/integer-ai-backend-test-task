"""Generation admission and task-status operations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.generation import (
    GenerateRequest,
    ProviderOutcome,
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
from app.services.task_status_service import TaskStatusService


@dataclass(frozen=True, slots=True)
class DispatchLease:
    """Persisted ownership token for one provider HTTP dispatch."""

    dispatch: AttemptDispatch
    token: UUID


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
        self.status_service: TaskStatusService = TaskStatusService()

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
        """Persist dispatch ownership before sending work outside the transaction."""
        async with session.begin():
            lease = await self.claim_dispatch(session, dispatch)
        if lease is not None:
            await self.send_claimed(session, lease)

    async def claim_dispatch(
        self, session: AsyncSession, dispatch: AttemptDispatch
    ) -> DispatchLease | None:
        """Lock task then attempt and persist one bounded dispatch lease."""
        generation = dispatch.generation
        task = await self.tasks.get_for_update(session, generation.task_id)
        if task is None or task.status not in {"queued", "processing"}:
            return None
        attempt = await self.attempts.get_for_update(
            session, generation.task_id, generation.attempt_no
        )
        if (
            attempt is None
            or task.current_attempt_id != attempt.id
            or attempt.status != "queued"
            or (
                attempt.dispatch_lease_expires_at is not None
                and attempt.dispatch_lease_expires_at > datetime.now(UTC)
            )
        ):
            return None
        return self._lease_attempt(attempt, dispatch)

    async def claim_queued_attempt(
        self, session: AsyncSession, task_id: UUID
    ) -> DispatchLease | None:
        """Claim a queued current attempt discovered by a watchdog tick."""
        task = await self.tasks.get_for_update(session, task_id)
        if task is None or task.status != "queued" or task.current_attempt_id is None:
            return None
        attempt = await self.attempts.get_current_for_update(
            session, task.id, task.current_attempt_id
        )
        if (
            attempt is None
            or attempt.status != "queued"
            or (
                attempt.dispatch_lease_expires_at is not None
                and attempt.dispatch_lease_expires_at > datetime.now(UTC)
            )
        ):
            return None
        leg = await self.catalog.get_leg(session, attempt.provider_leg_id)
        if leg is None:
            return None
        dispatch = AttemptDispatch(
            provider=leg.provider_name,
            generation=GenerationInput(
                task_id=task.id,
                attempt_no=attempt.attempt_no,
                prompt=task.prompt,
                ref_images=tuple(task.ref_images),
            ),
        )
        return self._lease_attempt(attempt, dispatch)

    async def send_claimed(self, session: AsyncSession, lease: DispatchLease) -> None:
        """Send a committed lease and accept a response only from its owner."""
        dispatch = lease.dispatch
        generation = dispatch.generation
        acceptance = await self.provider.submit(dispatch.provider, generation)
        next_dispatch: AttemptDispatch | None = None
        async with session.begin():
            task = await self.tasks.get_for_update(session, generation.task_id)
            if task is None:
                return
            attempt = await self.attempts.get_for_update(
                session, generation.task_id, generation.attempt_no
            )
            if (
                attempt is None
                or task.current_attempt_id != attempt.id
                or attempt.status != "queued"
                or attempt.dispatch_lease_token != lease.token
            ):
                return
            if acceptance.status_code == 202:
                task.status = "processing"
                attempt.status = "processing"
                attempt.external_id = acceptance.external_id
                attempt.deadline_at = datetime.now(UTC) + timedelta(
                    seconds=self.provider_timeout
                )
                attempt.dispatch_lease_token = None
                attempt.dispatch_lease_expires_at = None
            else:
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

    def _lease_attempt(
        self, attempt: GenerationAttempt, dispatch: AttemptDispatch
    ) -> DispatchLease:
        """Assign a bounded owner token before a provider request begins."""
        token = uuid4()
        attempt.dispatch_lease_token = token
        attempt.dispatch_lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=self.provider_timeout
        )
        return DispatchLease(dispatch=dispatch, token=token)

    async def status(self, session: AsyncSession, task_id: UUID) -> TaskStatusResponse:
        """Return stored task state and provider attempt history."""
        return await self.status_service.status(session, task_id)
