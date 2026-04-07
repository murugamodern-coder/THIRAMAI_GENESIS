"""Provider and routing errors (kept small for blast-radius handling)."""


class QueryLengthExceeded(Exception):
    """Raised when the provider rejects input as too long."""


def looks_like_length_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "too long" in msg
        or "query is too long" in msg
        or "max length" in msg
        or "exceeds the maximum" in msg
        or "length exceeded" in msg
        or ("token" in msg and ("limit" in msg or "exceed" in msg))
    )
