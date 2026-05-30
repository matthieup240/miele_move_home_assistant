"""Tests for fetchers.py — pure orchestration over the API client."""

from __future__ import annotations

import asyncio
from typing import Any

from conftest import load_module

fetchers = load_module("fetchers")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
# fetch_live_state
# --------------------------------------------------------------------------- #


def test_fetch_live_state_calls_get_device_once_per_device():
    devices_payload = {"items": [{"id": "A"}, {"id": "B"}]}
    calls: list[str] = []

    async def get_device(device_id: str) -> dict[str, Any]:
        calls.append(device_id)
        return {"id": device_id, "status": "RUNNING"}

    _run(fetchers.fetch_live_state(devices_payload, get_device))
    assert calls == ["A", "B"]


def test_fetch_live_state_returns_device_and_details_per_id():
    devices_payload = {"items": [{"id": "A", "status": "RUNNING"}]}

    async def get_device(device_id: str) -> dict[str, Any]:
        return {"id": device_id, "model": "WM-X"}

    result = _run(fetchers.fetch_live_state(devices_payload, get_device))
    assert result == {
        "A": {
            "device": {"id": "A", "status": "RUNNING"},
            "details": {"id": "A", "model": "WM-X"},
        }
    }


def test_fetch_live_state_does_not_call_anything_for_empty_devices():
    calls: list[str] = []

    async def get_device(device_id: str) -> dict[str, Any]:
        calls.append(device_id)
        return {}

    result = _run(fetchers.fetch_live_state({"items": []}, get_device))
    assert result == {}
    assert calls == []


# --------------------------------------------------------------------------- #
# fetch_device_history
# --------------------------------------------------------------------------- #


def test_fetch_device_history_calls_executions_once():
    exec_calls: list[str] = []

    async def get_executions(fab_nr: str) -> Any:
        exec_calls.append(fab_nr)
        return {"items": []}

    async def get_execution_detail(fab_nr: str, exec_id: str) -> Any:
        return {}

    _run(
        fetchers.fetch_device_history(
            "FAB1", 5, get_executions, get_execution_detail
        )
    )
    assert exec_calls == ["FAB1"]


def test_fetch_device_history_calls_detail_up_to_max():
    executions = [{"executionId": f"e{i}"} for i in range(10)]
    detail_calls: list[tuple[str, str]] = []

    async def get_executions(fab_nr: str) -> Any:
        return {"items": executions}

    async def get_execution_detail(fab_nr: str, exec_id: str) -> Any:
        detail_calls.append((fab_nr, exec_id))
        return {"id": exec_id}

    _, details = _run(
        fetchers.fetch_device_history(
            "FAB1", 3, get_executions, get_execution_detail
        )
    )
    assert detail_calls == [("FAB1", "e0"), ("FAB1", "e1"), ("FAB1", "e2")]
    assert len(details) == 3


def test_fetch_device_history_with_max_zero_skips_detail_calls():
    executions = [{"executionId": "e1"}]
    detail_calls: list[Any] = []

    async def get_executions(fab_nr: str) -> Any:
        return {"items": executions}

    async def get_execution_detail(fab_nr: str, exec_id: str) -> Any:
        detail_calls.append(exec_id)
        return {}

    executions_payload, details = _run(
        fetchers.fetch_device_history(
            "FAB1", 0, get_executions, get_execution_detail
        )
    )
    assert executions_payload == {"items": executions}
    assert detail_calls == []
    assert details == []


def test_fetch_device_history_skips_executions_without_id():
    executions = [{"executionId": "e1"}, {"noId": True}, {"executionId": "e2"}]
    detail_calls: list[str] = []

    async def get_executions(fab_nr: str) -> Any:
        return {"items": executions}

    async def get_execution_detail(fab_nr: str, exec_id: str) -> Any:
        detail_calls.append(exec_id)
        return {"id": exec_id}

    _, details = _run(
        fetchers.fetch_device_history(
            "FAB1", 5, get_executions, get_execution_detail
        )
    )
    assert detail_calls == ["e1", "e2"]
    assert len(details) == 2


def test_fetch_device_history_skips_none_details():
    executions = [{"executionId": "e1"}, {"executionId": "e2"}]

    async def get_executions(fab_nr: str) -> Any:
        return {"items": executions}

    async def get_execution_detail(fab_nr: str, exec_id: str) -> Any:
        return None if exec_id == "e1" else {"id": exec_id}

    _, details = _run(
        fetchers.fetch_device_history(
            "FAB1", 5, get_executions, get_execution_detail
        )
    )
    assert details == [{"id": "e2"}]


def test_fetch_device_history_returns_raw_executions_payload():
    raw = {"total": 1, "items": [{"executionId": "e1"}]}

    async def get_executions(fab_nr: str) -> Any:
        return raw

    async def get_execution_detail(fab_nr: str, exec_id: str) -> Any:
        return {"id": exec_id}

    executions_payload, _ = _run(
        fetchers.fetch_device_history(
            "FAB1", 5, get_executions, get_execution_detail
        )
    )
    assert executions_payload == raw
