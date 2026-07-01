"""Fernet encryption wrapper — Memory Agent v1.3 (Spec §2 Encryption).

ENCRYPTION_KEY must be a valid Fernet key (32-byte url-safe base64).
Generate with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Format is validated at import: if ENCRYPTION_KEY is set but malformed, the module
raises and the API refuses to start. If it is absent, validation is deferred —
encrypt/decrypt then raise at call time, and validate_production_secrets() blocks
startup in production. This keeps dev/test (which import the app without the key)
working while still failing fast on a misconfigured key.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

_INVALID_MSG = (
    "ENCRYPTION_KEY is not a valid Fernet key (32-byte url-safe base64). "
    "Generate with: python -c \"from cryptography.fernet import Fernet; "
    "print(Fernet.generate_key().decode())\""
)
_MISSING_MSG = "ENCRYPTION_KEY not set — required to encrypt LLM provider keys"

_RAW_KEY = os.environ.get("ENCRYPTION_KEY", "")
if _RAW_KEY:
    try:
        _FERNET: "Fernet | None" = Fernet(_RAW_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(_INVALID_MSG) from exc
else:
    _FERNET = None


def encryption_key_ok() -> bool:
    """True if a valid Fernet key is loaded. Used by validate_production_secrets()."""
    return _FERNET is not None


def _get_fernet() -> Fernet:
    if _FERNET is None:
        raise RuntimeError(_MISSING_MSG)
    return _FERNET


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str | bytes) -> str:
    if isinstance(token, str):
        token = token.encode()
    return _get_fernet().decrypt(token).decode()
