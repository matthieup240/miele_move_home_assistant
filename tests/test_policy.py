"""Tests for policy.py — pure decision logic for adaptive polling."""

from __future__ import annotations

from conftest import load_module

policy = load_module("policy")


# --------------------------------------------------------------------------- #
# should_refresh_history
# --------------------------------------------------------------------------- #


def test_first_tick_always_refreshes_history():
    assert policy.should_refresh_history(None, True, 0, 120) is True
    assert policy.should_refresh_history(None, False, 0, 120) is True


def test_active_to_inactive_transition_refreshes_history():
    assert policy.should_refresh_history(True, False, 0, 120) is True


def test_still_active_skips_history():
    assert policy.should_refresh_history(True, True, 0, 120) is False
    assert policy.should_refresh_history(True, True, 50, 120) is False


def test_still_inactive_skips_history_before_period():
    assert policy.should_refresh_history(False, False, 50, 120) is False


def test_inactive_to_active_does_not_refresh_immediately():
    assert policy.should_refresh_history(False, True, 0, 120) is False


def test_periodic_refresh_at_ceiling():
    assert policy.should_refresh_history(True, True, 120, 120) is True
    assert policy.should_refresh_history(False, False, 121, 120) is True


def test_period_zero_means_always_refresh():
    assert policy.should_refresh_history(True, True, 0, 0) is True


# --------------------------------------------------------------------------- #
# next_update_interval_seconds
# --------------------------------------------------------------------------- #


def test_next_interval_fast_when_any_active():
    assert policy.next_update_interval_seconds(True, 5, 120) == 5


def test_next_interval_slow_when_none_active():
    assert policy.next_update_interval_seconds(False, 5, 120) == 120
