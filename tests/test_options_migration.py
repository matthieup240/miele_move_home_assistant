"""Tests for options migration and interval validation."""

from __future__ import annotations

from conftest import load_module

options = load_module("options")


# --------------------------------------------------------------------------- #
# migrate_options
# --------------------------------------------------------------------------- #


def test_migrate_legacy_scan_interval_to_slow():
    migrated = options.migrate_options(
        {"scan_interval_seconds": 60, "max_execution_details": 5}
    )
    assert migrated["slow_interval_seconds"] == 60
    assert migrated["max_execution_details"] == 5
    assert "scan_interval_seconds" not in migrated


def test_migrate_without_legacy_keeps_existing():
    current = {
        "slow_interval_seconds": 100,
        "fast_interval_seconds": 4,
        "max_execution_details": 3,
    }
    assert options.migrate_options(current) == current


def test_migrate_does_not_overwrite_explicit_slow_interval():
    migrated = options.migrate_options(
        {"scan_interval_seconds": 60, "slow_interval_seconds": 200}
    )
    assert migrated["slow_interval_seconds"] == 200
    assert "scan_interval_seconds" not in migrated


def test_migrate_returns_new_dict_does_not_mutate_input():
    original = {"scan_interval_seconds": 60}
    snapshot = dict(original)
    options.migrate_options(original)
    assert original == snapshot


def test_migrate_empty_options():
    assert options.migrate_options({}) == {}


def test_migrate_preserves_device_ttl_when_present():
    migrated = options.migrate_options(
        {"device_ttl_seconds": 3600, "scan_interval_seconds": 60}
    )
    assert migrated["device_ttl_seconds"] == 3600


def test_migrate_does_not_invent_device_ttl_when_absent():
    migrated = options.migrate_options({"slow_interval_seconds": 120})
    assert "device_ttl_seconds" not in migrated


# --------------------------------------------------------------------------- #
# validate_intervals
# --------------------------------------------------------------------------- #


def test_validate_intervals_normal_case():
    assert options.validate_intervals(5, 120) is None


def test_validate_intervals_equal_is_ok():
    assert options.validate_intervals(60, 60) is None


def test_validate_intervals_fast_greater_than_slow_returns_error_key():
    assert options.validate_intervals(200, 60) == "fast_greater_than_slow"


def test_validate_intervals_minimum_boundary():
    assert options.validate_intervals(3, 30) is None


def test_validate_intervals_maximum_boundary():
    assert options.validate_intervals(60, 3600) is None
