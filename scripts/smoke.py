"""Проверка платёжного и генерационного HTTP-потока локального API.

Запуск: BASE_URL=http://localhost:8000 uv run python scripts/smoke.py
"""

import hashlib
import hmac
import json
import os
from uuid import uuid4

import httpx
from app.api.schemas.balance import BalanceResponse
from app.api.schemas.generation import GenerateResponse, TaskStatusResponse

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "local-compose-webhook-secret")
TIMEOUT = httpx.Timeout(5.0, connect=2.0)


def main() -> None:
    """Выполнить по одному запросу для каждого шага сквозного сценария."""
    user_id = uuid4()
    payment_id = uuid4()
    payment_body = json.dumps(
        {
            "payment_id": str(payment_id),
            "user_id": str(user_id),
            "tokens": 10,
            "status": "succeeded",
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), payment_body, hashlib.sha256
    ).hexdigest()

    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        payment = client.post(
            "/webhooks/payments",
            content=payment_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature,
            },
        )
        if payment.status_code != 204:
            raise RuntimeError(f"Ожидался payment 204, получен {payment.status_code}")
        print(f"payment: HTTP {payment.status_code}")

        balance = client.get(f"/users/{user_id}/balance")
        balance_response = balance.raise_for_status()
        balance_json = BalanceResponse.model_validate_json(balance_response.content)
        if balance_json.balance != 10:
            raise RuntimeError(f"Ожидался баланс 10: {balance_json!r}")
        print(f"balance: HTTP {balance_response.status_code} {balance_json}")

        generation = client.post(
            "/generate",
            json={
                "user_id": str(user_id),
                "model": "image-fast",
                "prompt": "Smoke test landscape",
                "ref_images": [],
            },
        )
        generation_response = generation.raise_for_status()
        if generation_response.status_code != 202:
            raise RuntimeError(
                f"Ожидался generate 202, получен {generation_response.status_code}"
            )
        generation_json = GenerateResponse.model_validate_json(
            generation_response.content
        )
        print(f"generate: HTTP {generation_response.status_code} {generation_json}")

        task = client.get(f"/tasks/{generation_json.task_id}")
        task_response = task.raise_for_status()
        task_json = TaskStatusResponse.model_validate_json(task_response.content)
        print(f"task: HTTP {task_response.status_code} {task_json}")


if __name__ == "__main__":
    main()
