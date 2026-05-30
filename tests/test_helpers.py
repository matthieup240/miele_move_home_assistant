"""Tests for the structural helpers (helpers.py) against the real API shapes."""

from __future__ import annotations

from conftest import load_module

helpers = load_module("helpers")


# DeviceList is {"total": int, "items": [Device]} in the real contract.
def test_iter_devices_from_devicelist_items():
    payload = {"total": 1, "items": [{"id": "000123456789", "name": "Lave-linge"}]}
    devices = list(helpers.iter_devices(payload))
    assert devices == [("000123456789", {"id": "000123456789", "name": "Lave-linge"})]


def test_infer_device_id_uses_id():
    assert helpers.infer_device_id({"id": "000123456789"}) == "000123456789"


def test_infer_fab_nr_falls_back_to_device_id():
    # Device has no fabNr/serialNumber in the contract; the id is used as {fabNr}.
    assert helpers.infer_fab_nr({"id": "000123456789"}, "000123456789") == "000123456789"


def test_iter_executions_from_executionlist_items():
    payload = {"total": 1, "items": [{"executionId": "e1", "programName": "Coton"}]}
    executions = list(helpers.iter_executions(payload))
    assert executions == [{"executionId": "e1", "programName": "Coton"}]


def test_infer_execution_id_uses_execution_id():
    assert helpers.infer_execution_id({"executionId": "e1"}) == "e1"


def test_flatten_scalars_drops_missing_sentinel():
    flat = helpers.flatten_scalars({"a": 1, "b": -32768, "c": {"d": "x"}})
    assert flat == {"a": 1, "c.d": "x"}


def test_flatten_scalars_handles_nested_lists():
    flat = helpers.flatten_scalars({"items": [{"v": 1}, {"v": 2}]})
    assert flat == {"items.0.v": 1, "items.1.v": 2}


# --------------------------------------------------------------------------- #
# stable_flat — keep a monotonic entity schema across the cycle boundary
# --------------------------------------------------------------------------- #


def test_stable_flat_passes_through_new_keys():
    assert helpers.stable_flat({"a": 1}, {}) == {"a": 1}


def test_stable_flat_keeps_disappeared_keys_as_none():
    # A path seen during a cycle (remaining_time) must survive once the cycle
    # ends, as None, so its entity is never orphaned/unavailable.
    result = helpers.stable_flat({"device.status": "off"}, {"current_program.remaining_time": 60})
    assert result == {"device.status": "off", "current_program.remaining_time": None}


def test_stable_flat_new_value_wins_over_previous():
    assert helpers.stable_flat({"a": 2}, {"a": 1, "b": 9}) == {"a": 2, "b": None}


def test_stable_flat_empty_inputs():
    assert helpers.stable_flat({}, {}) == {}


def test_stable_flat_empty_new_keeps_all_previous_as_none():
    assert helpers.stable_flat({}, {"a": 1, "b": 2}) == {"a": None, "b": None}
