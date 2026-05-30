"""Miele MOVE API exceptions and response classification.

Pure module: no aiohttp/yarl dependency so it can be unit-tested without the
HA runtime.
"""

from __future__ import annotations


class MieleMoveApiError(Exception):
    """Base exception for Miele MOVE API errors."""


class MieleMoveAuthError(MieleMoveApiError):
    """Raised when the API key is rejected (401/403)."""


class MieleMoveRateLimitError(MieleMoveApiError):
    """Raised when the API returns 429 Too Many Requests."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> int | None:
    """Parse a Retry-After header value as a non-negative number of seconds.

    HTTP date format is not supported (Miele responses use seconds in practice).
    """
    if value is None:
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


def classify_response(
    status: int, retry_after_header: str | None
) -> MieleMoveApiError | None:
    """Return the exception to raise for an HTTP status, or None if OK."""
    if 200 <= status < 400:
        return None
    if status in (401, 403):
        return MieleMoveAuthError("Miele MOVE API key was rejected")
    if status == 429:
        return MieleMoveRateLimitError(
            "Miele MOVE API rate limit reached",
            retry_after=parse_retry_after(retry_after_header),
        )
    return MieleMoveApiError(f"Miele MOVE API returned HTTP {status}")
