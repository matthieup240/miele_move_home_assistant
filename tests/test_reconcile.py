"""Tests for reconcile.py — pure device-persistence logic.

Covers the "retain last known state" behaviour: when a Miele MOVE appliance
leaves the /devices listing at the end of a cycle, it must be retained (stale)
instead of disappearing, until a configurable TTL expires.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import load_module

reconcile = load_module("reconcile")

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


def _entry(device_id: str, **extra) -> dict:
    """Minimal device entry with a couple of business fields."""
    entry = {"id": device_id, "fab_nr": f"FAB-{device_id}", "flat": {"device.status": "running"}}
    entry.update(extra)
    return entry


# --------------------------------------------------------------------------- #
# mark_present
# --------------------------------------------------------------------------- #


def test_mark_present_sets_metadata():
    out = reconcile.mark_present(_entry("A"), NOW)
    assert out["_persist"] == {
        "present": True,
        "last_seen": NOW.isoformat(),
        "stale": False,
    }


def test_mark_present_does_not_mutate_input():
    original = _entry("A")
    reconcile.mark_present(original, NOW)
    assert "_persist" not in original


def test_mark_present_preserves_business_fields():
    out = reconcile.mark_present(_entry("A", flat={"x": 1}), NOW)
    assert out["flat"] == {"x": 1}
    assert out["fab_nr"] == "FAB-A"


# --------------------------------------------------------------------------- #
# reconcile_devices
# --------------------------------------------------------------------------- #


def test_present_device_passes_through_marked_present():
    result = reconcile.reconcile_devices({"A": _entry("A")}, {}, NOW, 3600)
    assert set(result) == {"A"}
    assert result["A"]["_persist"]["present"] is True
    assert result["A"]["_persist"]["stale"] is False
    assert result["A"]["_persist"]["last_seen"] == NOW.isoformat()


def test_present_device_preserves_business_fields():
    result = reconcile.reconcile_devices(
        {"A": _entry("A", flat={"k": "v"})}, {}, NOW, 3600
    )
    assert result["A"]["flat"] == {"k": "v"}


def test_disappeared_device_retained_within_ttl():
    seen_at = NOW - timedelta(seconds=100)
    previous = {"A": reconcile.mark_present(_entry("A"), seen_at)}
    result = reconcile.reconcile_devices({}, previous, NOW, 3600)

    assert set(result) == {"A"}
    persist = result["A"]["_persist"]
    assert persist["present"] is False
    assert persist["stale"] is True
    # last_seen must NOT advance while the device is gone.
    assert persist["last_seen"] == seen_at.isoformat()


def test_retained_device_keeps_business_fields_from_previous():
    seen_at = NOW - timedelta(seconds=100)
    previous = {
        "A": reconcile.mark_present(
            _entry("A", flat={"latestcycle.finalstatus": "finished"}), seen_at
        )
    }
    result = reconcile.reconcile_devices({}, previous, NOW, 3600)
    assert result["A"]["flat"] == {"latestcycle.finalstatus": "finished"}


def test_disappeared_device_purged_past_ttl():
    seen_at = NOW - timedelta(seconds=3601)
    previous = {"A": reconcile.mark_present(_entry("A"), seen_at)}
    result = reconcile.reconcile_devices({}, previous, NOW, 3600)
    assert result == {}


def test_disappeared_device_at_ttl_boundary_retained():
    seen_at = NOW - timedelta(seconds=3600)  # age == ttl
    previous = {"A": reconcile.mark_present(_entry("A"), seen_at)}
    result = reconcile.reconcile_devices({}, previous, NOW, 3600)
    assert set(result) == {"A"}


def test_reappearing_device_refreshes_last_seen_and_data():
    old = NOW - timedelta(seconds=500)
    previous = {"A": reconcile.mark_present(_entry("A", flat={"old": 1}), old)}
    # mark it stale as a real previous tick would have
    previous = reconcile.reconcile_devices({}, previous, NOW - timedelta(seconds=10), 3600)

    fresh = {"A": _entry("A", flat={"new": 2})}
    result = reconcile.reconcile_devices(fresh, previous, NOW, 3600)

    assert result["A"]["_persist"]["present"] is True
    assert result["A"]["_persist"]["stale"] is False
    assert result["A"]["_persist"]["last_seen"] == NOW.isoformat()
    assert result["A"]["flat"] == {"new": 2}


def test_previous_without_persist_is_retained_not_purged():
    # Entry coming from an older version of the integration: no _persist meta.
    previous = {"A": _entry("A")}
    result = reconcile.reconcile_devices({}, previous, NOW, 3600)
    assert set(result) == {"A"}
    assert result["A"]["_persist"]["stale"] is True
    assert result["A"]["_persist"]["last_seen"] == NOW.isoformat()


def test_invalid_last_seen_is_treated_as_just_seen_not_purged():
    # A corrupted/unparseable timestamp must not make the device vanish: even
    # with ttl=0 (which would purge a valid older timestamp), it is retained.
    previous = {
        "A": {
            **_entry("A"),
            "_persist": {"present": False, "last_seen": "not-a-date", "stale": True},
        }
    }
    result = reconcile.reconcile_devices({}, previous, NOW, 0)
    assert set(result) == {"A"}
    assert result["A"]["_persist"]["last_seen"] == NOW.isoformat()


def test_ttl_zero_purges_disappeared_device():
    seen_at = NOW - timedelta(seconds=1)
    previous = {"A": reconcile.mark_present(_entry("A"), seen_at)}
    result = reconcile.reconcile_devices({}, previous, NOW, 0)
    assert result == {}


def test_mixed_present_and_disappeared():
    seen_at = NOW - timedelta(seconds=100)
    previous = {
        "A": reconcile.mark_present(_entry("A"), seen_at),
        "B": reconcile.mark_present(_entry("B"), seen_at),
    }
    result = reconcile.reconcile_devices({"A": _entry("A")}, previous, NOW, 3600)
    assert set(result) == {"A", "B"}
    assert result["A"]["_persist"]["present"] is True
    assert result["B"]["_persist"]["present"] is False


def test_empty_inputs():
    assert reconcile.reconcile_devices({}, {}, NOW, 3600) == {}


# --------------------------------------------------------------------------- #
# disappeared_device_ids
# --------------------------------------------------------------------------- #


def test_disappeared_device_ids():
    previous = {"A": _entry("A"), "B": _entry("B"), "C": _entry("C")}
    gone = reconcile.disappeared_device_ids({"A"}, previous)
    assert sorted(gone) == ["B", "C"]


def test_disappeared_device_ids_none_gone():
    previous = {"A": _entry("A")}
    assert reconcile.disappeared_device_ids({"A"}, previous) == []


# --------------------------------------------------------------------------- #
# should_final_history_refresh
# --------------------------------------------------------------------------- #


def test_final_refresh_allowed_first_attempt():
    assert reconcile.should_final_history_refresh(0, 3, already_finalized=False) is True


def test_final_refresh_stops_when_finalized():
    assert reconcile.should_final_history_refresh(0, 3, already_finalized=True) is False


def test_final_refresh_stops_after_max_attempts():
    assert reconcile.should_final_history_refresh(3, 3, already_finalized=False) is False


def test_final_refresh_allows_retries_regardless_of_active_state():
    # Independent of was_active: still True on 2nd attempt while not finalized.
    assert reconcile.should_final_history_refresh(1, 3, already_finalized=False) is True


# --------------------------------------------------------------------------- #
# is_present
# --------------------------------------------------------------------------- #


def test_is_present_true_for_present_device():
    entry = reconcile.mark_present(_entry("A"), NOW)
    assert reconcile.is_present(entry) is True


def test_is_present_false_for_stale_device():
    seen_at = NOW - timedelta(seconds=100)
    stale = reconcile.reconcile_devices(
        {}, {"A": reconcile.mark_present(_entry("A"), seen_at)}, NOW, 3600
    )["A"]
    assert reconcile.is_present(stale) is False


def test_is_present_false_for_empty_entry():
    assert reconcile.is_present({}) is False
    assert reconcile.is_present(None) is False


def test_is_present_false_without_persist_meta():
    assert reconcile.is_present(_entry("A")) is False
