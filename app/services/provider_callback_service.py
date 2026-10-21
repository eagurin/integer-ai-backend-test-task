"""Guarded provider outcome transitions and failover selection."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.generation import ProviderOutcome
from app.api.schemas.webhooks import ProviderWebhookRequest
from app.models.generation_attempt import GenerationAttempt
from app.models.generation_model import ProviderLeg
from app.models.generation_task import GenerationTask
from app.models.token_ledger_entry import TokenLedgerEntry
from app.providers import GenerationInput
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.generation_catalog_repository import (
    GenerationCatalogRepository,
)
from app.repositories.task_repository import TaskRepository
from app.repositories.token_ledger_repository import TokenLedgerRepository


@dataclass(frozen=True, slots=True)
class AttemptDispatch:
    """The committed next attempt to send after releasing database locks."""

    provider: str
    generation: GenerationInput


class ProviderCallbackService:
    """Applies one callback to the current attempt, at most once."""

    def __init__(self, provider_timeout: float = 60.0) -> None:
        self.tasks: TaskRepository = TaskRepository()
        self.attempts: AttemptRepository = AttemptRepository()
        self.catalog: GenerationCatalogRepository = GenerationCatalogRepository()
        self.ledger: TokenLedgerRepository = TokenLedgerRepository()
        self.provider_timeout: float = provider_timeout

    async def apply(
        self,
        session: AsyncSession,
        provider_name: str,
        event: ProviderWebhookRequest,
    ) -> AttemptDispatch | None:
        """Lock task then attempt and apply its callback transition."""
        task = await self.tasks.get_for_update(session, event.task_id)
        if task is None or task.status in {"succeeded", "failed"}:
            return None
        attempt = await self.attempts.get_for_update(
            session, event.task_id, event.attempt_no
        )
        if (
            attempt is None
            or task.current_attempt_id != attempt.id
            or attempt.status in {"succeeded", "failed", "timed_out"}
        ):
            return None
        leg = await self.catalog.get_leg(session, attempt.provider_leg_id)
        if leg is None or leg.provider_name != provider_name:
            return None

        attempt.completed_at = datetime.now(UTC)
        match event.outcome:
            case ProviderOutcome.COMPLETED:
                attempt.error_type = None
                attempt.status = "succeeded"
                task.status = "succeeded"
                task.result_url = event.output
                return None
            case ProviderOutcome.PAYLOAD:
                attempt.error_type = event.outcome.value
                attempt.status = "failed"
                task.status = "failed"
                await self._refund(session, task)
                return None
            case ProviderOutcome.TECHNICAL_ERROR | ProviderOutcome.MODERATION:
                attempt.error_type = event.outcome.value
                attempt.status = "failed"
                return await self._advance(
                    session,
                    task,
                    leg,
                    moderation=event.outcome == ProviderOutcome.MODERATION,
                )
            case unreachable:
                from typing import assert_never

                assert_never(unreachable)

    async def timeout_due(
        self,
        session: AsyncSession,
        task_id: UUID,
        now: datetime,
    ) -> AttemptDispatch | None:
        """Timeout one due current attempt under task-then-attempt locks."""
        task = await self.tasks.get_for_update(session, task_id)
        if task is None or task.status not in {"queued", "processing"}:
            return None
        attempt_id = task.current_attempt_id
        if attempt_id is None:
            return None
        attempt = await self.attempts.get_current_for_update(
            session, task.id, attempt_id
        )
        if (
            attempt is None
            or attempt.status not in {"queued", "processing"}
            or attempt.deadline_at is None
            or attempt.deadline_at > now
        ):
            return None
        leg = await self.catalog.get_leg(session, attempt.provider_leg_id)
        if leg is None:
            return None

        attempt.completed_at = now
        attempt.error_type = "timeout"
        attempt.status = "timed_out"
        return await self._advance(session, task, leg, moderation=False)

    async def _advance(
        self,
        session: AsyncSession,
        task: GenerationTask,
        current_leg: ProviderLeg,
        *,
        moderation: bool,
    ) -> AttemptDispatch | None:
        """Create one ordered next attempt or refund an exhausted task."""
        legs = await self.catalog.compatible_legs(
            session, task.generation_model_id, len(task.ref_images)
        )
        next_leg = next(
            (
                leg
                for leg in legs
                if leg.priority > current_leg.priority
                and not (moderation and leg.skip_on_moderation)
            ),
            None,
        )
        if next_leg is None:
            task.status = "failed"
            await self._refund(session, task)
            return None

        attempts = await self.attempts.for_task(session, task.id)
        attempt_no = len(attempts) + 1
        new_attempt = GenerationAttempt(
            id=uuid4(),
            task_id=task.id,
            provider_leg_id=next_leg.id,
            attempt_no=attempt_no,
            status="queued",
            deadline_at=datetime.now(UTC) + timedelta(seconds=self.provider_timeout),
        )
        await self.attempts.add(session, new_attempt)
        task.current_provider_leg_id = next_leg.id
        task.current_attempt_id = new_attempt.id
        task.status = "queued"
        return AttemptDispatch(
            provider=next_leg.provider_name,
            generation=GenerationInput(
                task_id=task.id,
                attempt_no=attempt_no,
                prompt=task.prompt,
                ref_images=tuple(task.ref_images),
            ),
        )

    async def _refund(self, session: AsyncSession, task: GenerationTask) -> None:
        """Append the generation refund in the terminal transition transaction."""
        model = await self.catalog.get_model_by_id(session, task.generation_model_id)
        if model is not None:
            await self.ledger.append(
                session,
                TokenLedgerEntry(
                    user_id=task.user_id,
                    operation_key=f"generation:{task.id}:refund",
                    delta=model.price_tokens,
                    reason="refund",
                ),
            )
