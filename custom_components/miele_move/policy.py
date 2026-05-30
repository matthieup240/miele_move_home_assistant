"""Pure decision logic for the adaptive polling coordinator.

Kept separate from coordinator.py so it can be unit-tested without Home
Assistant. No I/O, no state.
"""

from __future__ import annotations


def should_refresh_history(
    was_active: bool | None,
    is_active: bool,
    ticks_since_refresh: int,
    refresh_period_ticks: int,
) -> bool:
    """Decide whether to re-fetch a device's program history this tick.

    - was_active is None: first tick we see this device, refresh.
    - active -> inactive transition: a cycle just finished, refresh.
    - ticks_since_refresh >= refresh_period_ticks: periodic safety net.
    """
    if was_active is None:
        return True
    if was_active and not is_active:
        return True
    return ticks_since_refresh >= refresh_period_ticks


def next_update_interval_seconds(
    any_active: bool,
    fast_seconds: int,
    slow_seconds: int,
) -> int:
    """Fast interval while at least one device is active, slow otherwise."""
    return fast_seconds if any_active else slow_seconds
