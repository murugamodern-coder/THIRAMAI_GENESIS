"""Typed HTTP errors for consistent API responses (Week 1 FIX 3)."""


class ThiramaiAppError(Exception):
    """Base for API errors mapped to JSON responses."""

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class ThiramaiNotFound(ThiramaiAppError):
    code = "NOT_FOUND"
    status_code = 404


class ThiramaiUnauthorized(ThiramaiAppError):
    code = "UNAUTHORIZED"
    status_code = 403


class ThiramaiValidationError(ThiramaiAppError):
    code = "VALIDATION_ERROR"
    status_code = 400


class ThiramaiServiceError(ThiramaiAppError):
    code = "SERVICE_UNAVAILABLE"
    status_code = 503


class ThiramaiRateLimit(ThiramaiAppError):
    code = "RATE_LIMIT"
    status_code = 429
