"""Stateless fetch orchestration over the Miele MOVE client.

Split into two operations so the coordinator can decide each tick whether to
refresh only the live state (cheap, frequent) or also the program history
(more expensive, rare).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .helpers import infer_execution_id, iter_devices, iter_executions


async def fetch_live_state(
    devices_payload: Any,
    get_device: Callable[[str], Awaitable[Any]],
) -> dict[str, dict[str, Any]]:
    """Fetch /devices/{id} for each device in devices_payload."""
    result: dict[str, dict[str, Any]] = {}
    for device_id, device_payload in iter_devices(devices_payload):
        details = await get_device(device_id)
        result[device_id] = {"device": device_payload, "details": details}
    return result


async def fetch_device_history(
    fab_nr: str,
    max_execution_details: int,
    get_executions: Callable[[str], Awaitable[Any]],
    get_execution_detail: Callable[[str, str], Awaitable[Any]],
) -> tuple[Any, list[Any]]:
    """Fetch executions list + up to max_execution_details details."""
    executions_payload = await get_executions(fab_nr)
    executions = list(iter_executions(executions_payload))
    details: list[Any] = []
    for execution in executions[:max_execution_details]:
        exec_id = infer_execution_id(execution)
        if not exec_id:
            continue
        detail = await get_execution_detail(fab_nr, exec_id)
        if detail is not None:
            details.append(detail)
    return executions_payload, details
