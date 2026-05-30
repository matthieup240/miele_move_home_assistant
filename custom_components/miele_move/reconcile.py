"""Pure device-persistence logic for the adaptive polling coordinator.

The Miele MOVE API only lists an appliance in /devices while a cycle is active
(and briefly after). When a program ends the appliance leaves the listing, so
naively rebuilding the device map each tick makes it vanish and its entities go
unavailable. This module keeps the last known state of a disappeared appliance
("stale") until a time-based TTL expires.

Kept separate from coordinator.py (no I/O, no Home Assistant import) so it can
be unit-tested in isolation, like policy.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def mark_present(entry: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Return a copy of a device entry tagged as seen live this tick."""
    tagged = dict(entry)
    tagged["_persist"] = {
        "present": True,
        "last_seen": now.isoformat(),
        "stale": False,
    }
    return tagged


def reconcile_devices(
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    now: datetime,
    ttl_seconds: float,
) -> dict[str, dict[str, Any]]:
    """Merge devices present this tick with recently-seen absent ones.

    - present in `current`: kept as-is, tagged present (last_seen=now).
    - absent from `current` but in `previous`, within TTL: carried over from
      `previous`, tagged stale, last_seen unchanged.
    - absent past TTL: purged (dropped from the result).
    - `previous` entry without `_persist` (upgrade from an older version): kept
      and treated as just seen, so it is never purged on the first tick.
    """
    result: dict[str, dict[str, Any]] = {}

    for device_id, entry in current.items():
        result[device_id] = mark_present(entry, now)

    for device_id, prev_entry in previous.items():
        if device_id in current:
            continue

        persist = prev_entry.get("_persist")
        last_seen_iso = persist.get("last_seen") if isinstance(persist, dict) else None
        last_seen = _parse_iso(last_seen_iso)

        if last_seen is None:
            # No usable timestamp (legacy entry): treat as just seen, keep it.
            last_seen_iso = now.isoformat()
        elif (now - last_seen).total_seconds() > ttl_seconds:
            continue  # TTL expired: purge.

        stale_entry = dict(prev_entry)
        stale_entry["_persist"] = {
            "present": False,
            "last_seen": last_seen_iso,
            "stale": True,
        }
        result[device_id] = stale_entry

    return result


def disappeared_device_ids(
    present_ids: set[str], previous: dict[str, dict[str, Any]]
) -> list[str]:
    """Device ids known last tick but no longer listed by the API."""
    return [device_id for device_id in previous if device_id not in present_ids]


def is_present(entry: Any) -> bool:
    """True if the device is currently listed/reachable (not stale, not purged)."""
    return bool(entry) and bool(entry.get("_persist", {}).get("present"))


def should_final_history_refresh(
    attempts_done: int, max_attempts: int, already_finalized: bool
) -> bool:
    """Whether to (re)fetch a disappeared device's history one more time.

    Intentionally independent of the device's active flag: once an appliance
    leaves the listing we keep retrying until the cloud finalizes the cycle or
    we exhaust `max_attempts`, so the last cycle's final status is captured.
    """
    return attempts_done < max_attempts and not already_finalized


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
