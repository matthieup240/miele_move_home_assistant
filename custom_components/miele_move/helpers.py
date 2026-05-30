"""Data helpers for Miele MOVE payloads."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MISSING_SENTINEL = -32768

ACTIVE_STATUSES = frozenset(
    {
        "running",
        "starting",
        "programmed",
        "waiting_to_start",
        "paused",
        "busy",
    }
)


def is_device_active(payload: Any) -> bool:
    """True if the device status implies fast state transitions can happen."""
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    if not isinstance(status, str):
        return False
    return status.strip().lower() in ACTIVE_STATUSES


def iter_devices(payload: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield device id and device payload from common list/dict shapes."""
    for key, item in _iter_items(payload, ("devices", "items", "content", "data")):
        if isinstance(item, dict):
            device_id = infer_device_id(item, key)
            if device_id:
                yield device_id, item


def iter_executions(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield execution payloads from common list/dict shapes."""
    for _, item in _iter_items(payload, ("executions", "items", "content", "data")):
        if isinstance(item, dict):
            yield item


def infer_device_id(payload: dict[str, Any], fallback: str | None = None) -> str | None:
    """Infer the id accepted by /devices/{id}."""
    for path in (
        ("id",),
        ("deviceId",),
        ("fabNr",),
        ("fabNumber",),
        ("serialNumber",),
        ("ident", "fabNumber"),
        ("ident", "fabNr"),
    ):
        value = nested_get(payload, path)
        if value not in (None, ""):
            return str(value)
    return fallback


def infer_fab_nr(payload: dict[str, Any], fallback: str) -> str:
    """Infer the fab number accepted by execution endpoints."""
    for path in (
        ("fabNr",),
        ("fabNumber",),
        ("serialNumber",),
        ("ident", "fabNumber"),
        ("ident", "fabNr"),
        ("device", "fabNr"),
        ("device", "fabNumber"),
    ):
        value = nested_get(payload, path)
        if value not in (None, ""):
            return str(value)
    return fallback


def infer_execution_id(payload: dict[str, Any]) -> str | None:
    """Infer execution id from an execution list item."""
    for key in ("id", "executionId", "programExecutionId", "uuid"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def infer_device_name(*payloads: Any, fallback: str) -> str:
    """Infer a readable device name."""
    paths = (
        ("name",),
        ("displayName",),
        ("designation",),
        ("ident", "deviceName"),
        ("ident", "type", "value_localized"),
        ("type", "value_localized"),
        ("type", "localized"),
        ("model",),
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for path in paths:
            value = nested_get(payload, path)
            if isinstance(value, str) and value:
                return value
    return f"Miele MOVE {fallback}"


def infer_model(*payloads: Any) -> str | None:
    """Infer a model string."""
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for path in (
            ("model",),
            ("type", "value_raw"),
            ("ident", "type", "value_raw"),
            ("techType",),
            ("ident", "techType"),
        ):
            value = nested_get(payload, path)
            if value not in (None, ""):
                return str(value)
    return None


def flatten_scalars(payload: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten scalar values into dot-separated paths."""
    result: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_prefix = _join(prefix, str(key))
            result.update(flatten_scalars(value, child_prefix))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            child_prefix = _join(prefix, str(index))
            result.update(flatten_scalars(value, child_prefix))
    elif payload is not None and payload != MISSING_SENTINEL:
        result[prefix] = payload
    return result


def stable_flat(new_flat: dict[str, Any], previous_flat: dict[str, Any]) -> dict[str, Any]:
    """Keep a monotonic entity schema for one device.

    Paths seen on a previous tick are preserved (as None when absent now) so an
    entity created during a cycle is never dropped once the cycle ends. This
    keeps the entity alive (value "unknown") instead of letting it disappear and
    become unavailable after a restart.
    """
    return {**{key: None for key in previous_flat}, **new_flat}


def nested_get(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Return a nested value from a dict."""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _iter_items(payload: Any, container_keys: tuple[str, ...]) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            yield str(index), item
        return

    if not isinstance(payload, dict):
        return

    for key in container_keys:
        value = payload.get(key)
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield str(index), item
            return
        if isinstance(value, dict):
            for item_key, item in value.items():
                yield str(item_key), item
            return

    for key, value in payload.items():
        if isinstance(value, dict):
            yield str(key), value


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key
