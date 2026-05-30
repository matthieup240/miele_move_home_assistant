"""Tests for is_device_active (drives adaptive polling)."""

from __future__ import annotations

from conftest import load_module

helpers = load_module("helpers")


def test_running_is_active():
    assert helpers.is_device_active({"status": "RUNNING"}) is True


def test_paused_is_active():
    assert helpers.is_device_active({"status": "PAUSED"}) is True


def test_starting_is_active():
    assert helpers.is_device_active({"status": "STARTING"}) is True


def test_programmed_is_active():
    assert helpers.is_device_active({"status": "PROGRAMMED"}) is True


def test_waiting_to_start_is_active():
    assert helpers.is_device_active({"status": "WAITING_TO_START"}) is True


def test_busy_is_active():
    assert helpers.is_device_active({"status": "BUSY"}) is True


def test_lowercase_status_is_active():
    assert helpers.is_device_active({"status": "running"}) is True


def test_mixed_case_status_is_active():
    assert helpers.is_device_active({"status": "Running"}) is True


def test_off_is_not_active():
    assert helpers.is_device_active({"status": "OFF"}) is False


def test_standby_is_not_active():
    assert helpers.is_device_active({"status": "STANDBY"}) is False


def test_completed_is_not_active():
    assert helpers.is_device_active({"status": "COMPLETED"}) is False


def test_error_is_not_active():
    assert helpers.is_device_active({"status": "ERROR"}) is False


def test_cancelled_is_not_active():
    assert helpers.is_device_active({"status": "CANCELLED"}) is False


def test_not_connected_is_not_active():
    assert helpers.is_device_active({"status": "NOT_CONNECTED"}) is False


def test_unknown_status_is_not_active():
    assert helpers.is_device_active({"status": "UNKNOWN"}) is False


def test_missing_status_is_not_active():
    assert helpers.is_device_active({"id": "123"}) is False


def test_non_dict_payload_is_not_active():
    assert helpers.is_device_active(None) is False
    assert helpers.is_device_active("RUNNING") is False
    assert helpers.is_device_active(42) is False


def test_non_string_status_is_not_active():
    assert helpers.is_device_active({"status": 1}) is False
    assert helpers.is_device_active({"status": None}) is False


def test_whitespace_padded_status_is_active():
    assert helpers.is_device_active({"status": "  RUNNING  "}) is True
