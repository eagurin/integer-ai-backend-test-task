"""Shared webhook signature verification."""

import hashlib
import hmac
import re

_LOWERCASE_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def verify_webhook_signature(
    raw_body: bytes, signature: str | None, secret: str
) -> bool:
    """Verify lowercase hexadecimal HMAC-SHA256 over the exact request bytes."""
    if signature is None or _LOWERCASE_SHA256_HEX.fullmatch(signature) is None:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
