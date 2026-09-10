"""Payload-free diagnostics plus bounded redaction of accidentally submitted secrets."""

import os
import re

from omniagent.credentials import configured_secret_values

SENSITIVE_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "access_token",
        "system_prompt",
        "reasoning",
        "reasoning_content",
        "chain_of_thought",
    }
)
SECRET_PATTERN = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{16,}|(?:api[_ -]?key|authorization|password|secret)"
    r"\s*[:=]\s*[^\s,;\"'}]{8,})"
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<![\w-])(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
THINK_PATTERN = re.compile(
    r"<(?:think|analysis|reasoning)>[\s\S]*?(?:</(?:think|analysis|reasoning)>|$)", re.IGNORECASE
)


def secret_values() -> tuple[str, ...]:
    return configured_secret_values() + tuple(
        value
        for key, value in os.environ.items()
        if len(value) >= 8
        and not key.endswith("_FILE")
        and (
            key.startswith("OMNIAGENT_")
            or key in {"OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GLM_API_KEY", "ZHIPUAI_API_KEY"}
        )
        and any(part in key for part in ("API_KEY", "SECRET", "PASSWORD", "TOKEN", "HEADERS"))
    )


def contains_secret(text: str) -> bool:
    return bool(SECRET_PATTERN.search(text) or any(value in text for value in secret_values()))


def redact_text(text: str) -> str:
    value = THINK_PATTERN.sub("[REDACTED_REASONING]", text)
    for secret in secret_values():
        value = value.replace(secret, "[REDACTED_SECRET]")
    value = SECRET_PATTERN.sub("[REDACTED_SECRET]", value)
    value = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    return PHONE_PATTERN.sub("[REDACTED_PHONE]", value)


def redact(value: object, *, depth: int = 0) -> object:
    if depth > 16:
        return "[REDACTED_DEPTH]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if str(key).lower() in SENSITIVE_FIELDS
            else redact(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [redact(item, depth=depth + 1) for item in value]
    return value
