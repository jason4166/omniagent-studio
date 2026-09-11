"""Resolve operator-owned credential references without serializing credential values."""

import os
from pathlib import Path

from omniagent.errors import ErrorCode, PlatformError

_loaded_secrets: set[str] = set()


def configured_secret_values() -> tuple[str, ...]:
    return tuple(_loaded_secrets)


def secret_configured(prefix: str) -> bool:
    return bool(os.environ.get(prefix + "_API_KEY") or os.environ.get(prefix + "_API_KEY_FILE"))


def resolve_secret(prefix: str) -> str:
    return resolve_credential(prefix + "_API_KEY")


def resolve_credential(name: str) -> str:
    value = os.environ.get(name)
    location = os.environ.get(name + "_FILE")
    if value and location:
        raise PlatformError(ErrorCode.VALIDATION, "Choose one credential reference")
    if location:
        try:
            with Path(location).open("rb") as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                raise ValueError("Oversized credential")
            value = raw.decode("utf-8").strip()
        except (OSError, UnicodeError, ValueError) as exc:
            raise PlatformError(ErrorCode.UNAVAILABLE, "Credential reference unavailable") from exc
    if not value or len(value) < 8 or len(value) > 8192:
        raise PlatformError(ErrorCode.UNAVAILABLE, "Credential reference unavailable")
    if len(_loaded_secrets) >= 16 and value not in _loaded_secrets:
        raise PlatformError(ErrorCode.UNAVAILABLE, "Restart after credential rotation")
    _loaded_secrets.add(value)
    return value
