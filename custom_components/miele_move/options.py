"""Pure helpers for the config flow: option migration and interval validation."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_DEVICE_TTL_SECONDS,
    CONF_FAST_INTERVAL_SECONDS,
    CONF_SCAN_INTERVAL_SECONDS,
    CONF_SLOW_INTERVAL_SECONDS,
)


def migrate_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return options migrated to the fast/slow interval shape.

    - Legacy scan_interval_seconds is moved to slow_interval_seconds unless slow
      is already set (the explicit value wins).
    - The legacy key is removed from the result.
    """
    migrated = dict(options)
    legacy = migrated.pop(CONF_SCAN_INTERVAL_SECONDS, None)
    if legacy is not None and CONF_SLOW_INTERVAL_SECONDS not in migrated:
        migrated[CONF_SLOW_INTERVAL_SECONDS] = legacy
    return migrated


def validate_intervals(fast: int, slow: int) -> str | None:
    """Cross-field check: fast must not exceed slow.

    Returns an error key compatible with the config flow strings, or None.
    """
    if fast > slow:
        return "fast_greater_than_slow"
    return None


__all__ = [
    "CONF_DEVICE_TTL_SECONDS",
    "CONF_FAST_INTERVAL_SECONDS",
    "CONF_SLOW_INTERVAL_SECONDS",
    "migrate_options",
    "validate_intervals",
]
