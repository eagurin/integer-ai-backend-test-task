"""Public API schema contract tests."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.api.schemas import (
    BalanceResponse,
    GenerateRequest,
    GenerateResponse,
    LedgerEntryResponse,
    PaymentStatus,
    PaymentWebhookRequest,
    ProviderOutcome,
    ProviderWebhookRequest,
    TaskHistoryEntry,
    TaskStatus,
    TaskStatusResponse,
)
from pydantic import HttpUrl, TypeAdapter, ValidationError

USER_ID = UUID("16ab0a64-c5ce-4f91-90b3-b495a3a853f0")
TASK_ID = UUID("0e00d749-8d8b-4fdb-9844-72aeea315b25")


def test_valid_generation_request_and_response() -> None:
    request = GenerateRequest(
        user_id=USER_ID,
        model="image-fast",
        prompt="A geometric landscape",
        ref_images=[
            TypeAdapter(HttpUrl).validate_python("https://example.com/reference.png")
        ],
    )

    assert str(request.ref_images[0]) == "https://example.com/reference.png"
    assert GenerateResponse(task_id=TASK_ID).task_id == TASK_ID


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": USER_ID, "model": "image-fast", "prompt": "   "},
        {
            "user_id": USER_ID,
            "model": "image-fast",
            "prompt": "valid",
            "ref_images": ["not a URL"],
        },
        {
            "user_id": "not-a-uuid",
            "model": "image-fast",
            "prompt": "valid",
        },
    ],
)
def test_rejects_invalid_generation_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(payload)


@pytest.mark.parametrize("status", ["", "created", "SUCCEEDED"])
def test_rejects_missing_or_unknown_payment_status(status: str) -> None:
    with pytest.raises(ValidationError):
        PaymentWebhookRequest.model_validate(
            {
                "payment_id": TASK_ID,
                "user_id": USER_ID,
                "tokens": 5,
                "status": status,
            }
        )


def test_rejects_omitted_payment_status() -> None:
    with pytest.raises(ValidationError):
        PaymentWebhookRequest.model_validate(
            {"payment_id": TASK_ID, "user_id": USER_ID, "tokens": 5}
        )


def test_accepts_payment_states_and_rejects_nonpositive_tokens() -> None:
    for status in (
        PaymentStatus.PENDING,
        PaymentStatus.SUCCEEDED,
        PaymentStatus.FAILED,
    ):
        assert (
            PaymentWebhookRequest(
                payment_id=TASK_ID, user_id=USER_ID, tokens=5, status=status
            ).status
            is status
        )
    with pytest.raises(ValidationError):
        PaymentWebhookRequest(
            payment_id=TASK_ID, user_id=USER_ID, tokens=-1, status=PaymentStatus.PENDING
        )


@pytest.mark.parametrize("outcome", [item.value for item in ProviderOutcome])
def test_accepts_provider_outcomes(outcome: str) -> None:
    event = ProviderWebhookRequest.model_validate(
        {"task_id": TASK_ID, "attempt_no": 1, "outcome": ProviderOutcome(outcome)}
    )
    assert event.outcome.value == outcome


def test_rejects_unknown_provider_outcome_and_invalid_identifier() -> None:
    with pytest.raises(ValidationError):
        ProviderWebhookRequest.model_validate(
            {"task_id": TASK_ID, "attempt_no": 1, "outcome": "unknown"}
        )
    with pytest.raises(ValidationError):
        GenerateResponse.model_validate({"task_id": "not-a-uuid"})


def test_valid_task_status_history_and_balance_shapes() -> None:
    timestamp = datetime.now(UTC)
    history_entry = TaskHistoryEntry(
        provider="alpha",
        outcome=ProviderOutcome.COMPLETED,
        error=None,
        created_at=timestamp,
    )
    status = TaskStatusResponse(
        task_id=TASK_ID,
        status=TaskStatus.SUCCEEDED,
        current_provider="alpha",
        output="result",
        history=[history_entry],
    )
    balance = BalanceResponse(
        user_id=USER_ID,
        balance=3,
        history=[
            LedgerEntryResponse(operation="payment", delta=3, created_at=timestamp)
        ],
    )
    assert status.history == [history_entry]
    assert balance.history[0].delta == 3


@pytest.mark.parametrize("task_status", list(TaskStatus))
def test_accepts_each_task_status(task_status: TaskStatus) -> None:
    assert (
        TaskStatusResponse(
            task_id=TASK_ID,
            status=task_status,
            current_provider=None,
            output=None,
            history=[],
        ).status
        is task_status
    )


def test_rejects_unknown_task_status() -> None:
    with pytest.raises(ValidationError):
        TaskStatusResponse.model_validate(
            {
                "task_id": TASK_ID,
                "status": "waiting",
                "current_provider": None,
                "output": None,
                "history": [],
            }
        )
