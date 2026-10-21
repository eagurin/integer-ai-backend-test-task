"""Raw-body webhook signature verification tests."""

import hashlib
import hmac

import pytest
from app.security import verify_webhook_signature

SECRET = "test-secret"
RAW_BODY = b'{ "amount": 2 }'


def signature_for(raw_body: bytes) -> str:
    return hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()


def test_accepts_valid_signature_for_raw_body() -> None:
    assert verify_webhook_signature(RAW_BODY, signature_for(RAW_BODY), SECRET)


def test_rejects_modified_raw_body() -> None:
    assert not verify_webhook_signature(
        RAW_BODY + b" ", signature_for(RAW_BODY), SECRET
    )


def test_rejects_missing_signature() -> None:
    assert not verify_webhook_signature(RAW_BODY, None, SECRET)


def test_rejects_uppercase_encoding_of_valid_signature() -> None:
    assert not verify_webhook_signature(
        RAW_BODY, signature_for(RAW_BODY).upper(), SECRET
    )


@pytest.mark.parametrize(
    "signature",
    [
        "not-hex",
        "A" * 64,
        "0" * 63,
        " " + "0" * 64,
    ],
)
def test_rejects_malformed_or_nonlowercase_signature(signature: str) -> None:
    assert not verify_webhook_signature(RAW_BODY, signature, SECRET)


def test_signature_uses_original_bytes_not_reserialized_json() -> None:
    compact_json = b'{"amount":2}'
    spaced_json = b'{ "amount": 2 }'
    assert verify_webhook_signature(spaced_json, signature_for(spaced_json), SECRET)
    assert not verify_webhook_signature(
        compact_json, signature_for(spaced_json), SECRET
    )
