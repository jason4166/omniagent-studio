"""Public, stable errors; dependency details never cross the API boundary."""

from enum import StrEnum


class ErrorCode(StrEnum):
    AUTH = "authentication_required"
    PERMISSION = "permission_denied"
    NOT_FOUND = "not_found"
    VALIDATION = "validation_error"
    CONFLICT = "version_conflict"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    BUDGET = "budget_exhausted"
    SCHEMA = "unsupported_schema"
    TIMEOUT = "dependency_timeout"
    RATE_LIMIT = "rate_limited"
    UNAVAILABLE = "dependency_unavailable"
    BAD_RESPONSE = "invalid_dependency_response"
    CIRCUIT_OPEN = "circuit_open"


class PlatformError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        self.code = code
        self.message = message or code.value.replace("_", " ")
        super().__init__(self.message)

    @property
    def status_code(self) -> int:
        return {
            ErrorCode.AUTH: 401,
            ErrorCode.PERMISSION: 403,
            ErrorCode.NOT_FOUND: 404,
            ErrorCode.CONFLICT: 409,
            ErrorCode.EXPIRED: 410,
            ErrorCode.CANCELLED: 409,
            ErrorCode.BUDGET: 422,
            ErrorCode.SCHEMA: 409,
            ErrorCode.VALIDATION: 422,
            ErrorCode.TIMEOUT: 504,
            ErrorCode.RATE_LIMIT: 429,
        }.get(self.code, 503)
