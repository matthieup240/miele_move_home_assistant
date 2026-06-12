"""Tests for the pure transformation/naming logic (transform.py).

The expected behaviour is derived from the real Miele MOVE OpenAPI contract
(https://www.miele-move.com/api-docs/json/app), notably:
- DeviceDetails.currentProgram with keys name / phaseName and Java-Duration
  objects for remainingTime / elapsedTime,
- ProgramExecution(Details) with programStatus enum completed/cancelled/failure,
- ConsumptionValue with type/unit enums (energy in wh, water in l|ml).
"""

from __future__ import annotations

import re

from conftest import load_module

transform = load_module("transform")


# --------------------------------------------------------------------------- #
# Durations: Java Duration object, ISO 8601 string, and plain seconds
# --------------------------------------------------------------------------- #


def test_duration_to_seconds_from_java_duration_object():
    java_duration = {"seconds": 1938, "nano": 0, "zero": False, "negative": False}
    assert transform.duration_to_seconds(java_duration) == 1938


def test_duration_to_seconds_from_iso_string():
    assert transform.duration_to_seconds("PT32M18S") == 32 * 60 + 18


def test_duration_to_seconds_from_plain_int():
    assert transform.duration_to_seconds(90) == 90


def test_duration_to_seconds_invalid_returns_none():
    assert transform.duration_to_seconds("not-a-duration") is None
    assert transform.duration_to_seconds(None) is None


# --------------------------------------------------------------------------- #
# current_program summary: keys name/phaseName, Duration objects reduced to s
# --------------------------------------------------------------------------- #


def test_build_current_program_summary_uses_real_keys_and_reduces_durations():
    details = {
        "currentProgram": {
            "id": 123,
            "name": "Cotons",
            "phaseName": "Lavage principal",
            "remainingTime": {"seconds": 1938, "nano": 0, "zero": False, "negative": False},
            "elapsedTime": {"seconds": 1325, "nano": 0},
            "startedAt": "2026-05-22T08:00:00Z",
            "stoppedAt": "2026-05-22T08:32:18Z",
            "details": {"type": "WM"},
        }
    }
    summary = transform.build_current_program_summary(details)

    assert summary["program_name"] == "Cotons"
    assert summary["phase"] == "Lavage principal"
    assert summary["program_id"] == 123
    assert summary["remaining_time"] == 1938
    assert summary["elapsed_time"] == 1325
    assert summary["started_at"] == "2026-05-22T08:00:00Z"
    # No Java-Duration noise (nano/zero/negative/units) leaks into the summary.
    assert "nano" not in str(summary)


def test_build_current_program_summary_empty_when_no_program():
    assert transform.build_current_program_summary({}) == {}
    assert transform.build_current_program_summary({"currentProgram": None}) == {}


def test_build_current_program_summary_extracts_polymorphic_details():
    # currentProgram.details is polymorphic (discriminator type). For a washing
    # machine it carries temperature/spin/load fields that must surface.
    details = {
        "currentProgram": {
            "name": "Coton",
            "details": {
                "type": "WM",
                "temperatureCurrent": 23.3,
                "temperatureTarget": 40,
                "spinningSpeedCurrent": 200,
                "spinningSpeedTarget": 1400,
                "loadWeight": 2.34,
                "setWeight": 3.4,
                "maxWeight": 8.0,
                "waterLevel": -32768,
                "extras": [{"name": "Prélavage"}, {"name": "Anti-froissage"}],
            },
        }
    }
    summary = transform.build_current_program_summary(details)
    assert summary["temperature_current"] == 23.3
    assert summary["temperature_target"] == 40
    assert summary["spinning_speed_current"] == 200
    assert summary["spinning_speed_target"] == 1400
    assert summary["load_weight"] == 2.34
    assert summary["max_weight"] == 8.0
    assert summary["options"] == "Prélavage, Anti-froissage"
    # The -32768 "unsupported" sentinel must be dropped.
    assert "water_level" not in summary


def test_build_current_program_summary_dryer_fields():
    details = {
        "currentProgram": {
            "details": {
                "type": "TD",
                "airTemperatureTarget": 60,
                "residualMoistureTarget": 5,
                # Official Extra schema: a dryer extra carries type + name.
                "extras": [{"type": "GENTLE", "name": "Délicat"}],
            }
        }
    }
    summary = transform.build_current_program_summary(details)
    assert summary["air_temperature_target"] == 60
    assert summary["residual_moisture_target"] == 5
    # The readable `name` wins over the `type` code.
    assert summary["options"] == "Délicat"


def test_option_names_falls_back_to_type_code():
    # Defensive: if the API omits the (schema-required) localized `name`, the
    # `type` code keeps the "Options" entity populated rather than empty.
    assert transform._option_names([{"type": "ANTI_CREASE"}]) == "ANTI_CREASE"
    # `name` still takes priority when present.
    assert transform._option_names([{"type": "GENTLE", "name": "gentle"}]) == "gentle"


# --------------------------------------------------------------------------- #
# latest_cycle summary: programStatus + consumptionValues
# --------------------------------------------------------------------------- #


def test_build_latest_cycle_summary_maps_execution_fields():
    execution = {
        "executionId": "e1",
        "programName": "Coton 40",
        "programStatus": "completed",
        "startedAt": "2026-05-20T10:00:00Z",
        "stoppedAt": "2026-05-20T11:30:00Z",
        "duration": "PT1H30M",
    }
    detail = {
        "executionId": "e1",
        "consumptionValues": [
            {"type": "energy", "unit": "wh", "value": 850, "source": "device"},
            {"type": "water", "unit": "l", "value": 42, "source": "device"},
            {"type": "cold_water", "unit": "l", "value": 30, "source": "device"},
            {"type": "warm_water", "unit": "ml", "value": 12000, "source": "device"},
        ],
    }
    summary = transform.build_latest_cycle_summary(execution, detail)

    assert summary["program_name"] == "Coton 40"
    assert summary["final_status"] == "completed"
    assert summary["duration"] == 90 * 60
    # energy wh -> kWh
    assert summary["energy_consumption"] == 0.85
    # water l stays l, cold_water l stays l, warm_water ml -> l
    assert summary["water_consumption"] == 42
    assert summary["cold_water_consumption"] == 30
    assert summary["warm_water_consumption"] == 12


def test_build_latest_cycle_summary_expands_program_name_abbreviation():
    # Miele returns the abbreviated "Couette synth." -> expand to the full label.
    for raw in ("Couette synth.", "Couette synth", "couette synth."):
        summary = transform.build_latest_cycle_summary({"programName": raw}, {})
        assert summary["program_name"] == "Couette synthétique"

    # Unknown program names are left untouched.
    summary = transform.build_latest_cycle_summary({"programName": "Coton 40"}, {})
    assert summary["program_name"] == "Coton 40"


def test_build_latest_cycle_summary_duration_fallback_from_start_stop():
    # No usable `duration` field -> compute it from stoppedAt - startedAt.
    execution = {
        "programName": "Couvertures Cheval",
        "programStatus": "completed",
        "startedAt": "2026-05-17T07:28:00Z",
        "stoppedAt": "2026-05-17T08:44:00Z",
    }
    summary = transform.build_latest_cycle_summary(execution, {})
    assert summary["duration"] == 76 * 60  # 1 h 16


def test_build_latest_cycle_summary_duration_prefers_api_field():
    execution = {
        "duration": "PT1H30M",
        "startedAt": "2026-05-17T07:00:00Z",
        "stoppedAt": "2026-05-17T09:00:00Z",  # 2 h, but API duration wins
    }
    summary = transform.build_latest_cycle_summary(execution, {})
    assert summary["duration"] == 90 * 60


def test_build_latest_cycle_summary_distinct_water_types_not_overwritten():
    detail = {
        "consumptionValues": [
            {"type": "cold_water", "unit": "l", "value": 5},
            {"type": "warm_water", "unit": "l", "value": 3},
            {"type": "water", "unit": "l", "value": 8},
        ]
    }
    summary = transform.build_latest_cycle_summary({}, detail)
    assert summary["water_consumption"] == 8
    assert summary["cold_water_consumption"] == 5
    assert summary["warm_water_consumption"] == 3


# --------------------------------------------------------------------------- #
# Status translation: device enum (UPPER) + programStatus enum (lower)
# --------------------------------------------------------------------------- #


def test_translate_status_device_enum_uppercase():
    assert transform.translate_status("RUNNING") == "En cours"
    assert transform.translate_status("WAITING_TO_START") == "En attente de démarrage"
    assert transform.translate_status("COMPLETED") == "Terminé"


def test_translate_status_program_status_failure_is_covered():
    assert transform.translate_status("failure") == "Échec"
    assert transform.translate_status("cancelled") == "Annulé"


def test_translate_status_unknown_passthrough():
    assert transform.translate_status("SOME_NEW_STATE") == "SOME_NEW_STATE"


# --------------------------------------------------------------------------- #
# Friendly names: aligned on the real contract, disambiguated by source
# --------------------------------------------------------------------------- #


def test_friendly_name_current_program_real_keys():
    assert transform.friendly_name("current_program.program_name") == "Programme en cours"
    assert transform.friendly_name("current_program.phase") == "Phase en cours"
    assert transform.friendly_name("current_program.remaining_time") == "Temps restant"
    assert transform.friendly_name("current_program.elapsed_time") == "Temps écoulé"


def test_friendly_name_latest_cycle_disambiguated():
    assert "dernier cycle" in transform.friendly_name("latest_cycle.program_name").lower()
    assert "dernier cycle" in transform.friendly_name("latest_cycle.final_status").lower()


def test_friendly_name_program_details_fields():
    assert transform.friendly_name("current_program.temperature_target") == "Température cible"
    assert transform.friendly_name("current_program.temperature_current") == "Température actuelle"
    assert transform.friendly_name("current_program.spinning_speed_target") == "Essorage cible"
    assert transform.friendly_name("current_program.load_weight") == "Charge"


def test_unit_and_class_for_program_details():
    assert transform.unit_for_path("current_program.temperature_target") == "°C"
    assert transform.unit_for_path("current_program.spinning_speed_target") == "tr/min"
    assert transform.unit_for_path("current_program.load_weight") == "kg"
    assert transform.unit_for_path("current_program.residual_moisture_target") == "%"
    # waterLevel is undocumented by Miele; confirmed as millimetres.
    assert transform.unit_for_path("current_program.water_level") == "mm"
    assert transform.state_class_for_path("current_program.water_level") == "measurement"

    assert transform.device_class_for_path("current_program.temperature_target") == "temperature"
    assert transform.device_class_for_path("current_program.load_weight") == "weight"
    assert transform.device_class_for_path("current_program.spinning_speed_target") is None

    assert transform.state_class_for_path("current_program.temperature_current") == "measurement"


def test_friendly_name_device_fields():
    assert transform.friendly_name("device.status") == "État actuel"
    assert transform.friendly_name("device.name") == "Nom"
    assert transform.friendly_name("device.location.name") == "Emplacement"


def test_friendly_name_no_raw_english_fallback_for_known_fields():
    # phaseName must not surface as "Phase Name"
    assert transform.friendly_name("current_program.phase") != "Phase Name"


# --------------------------------------------------------------------------- #
# Path classification: unit, value class, diagnostic
# --------------------------------------------------------------------------- #


def test_unit_for_path():
    assert transform.unit_for_path("latest_cycle.energy_consumption") == "kWh"
    assert transform.unit_for_path("latest_cycle.water_consumption") == "L"
    # Durations are formatted strings ("1 h 30 min"), so they carry no unit.
    assert transform.unit_for_path("current_program.remaining_time") is None


def test_unit_for_path_duration_keys_carry_no_unit():
    # Regression: "duration" contains the substring "ratio", which must not be
    # treated as a percentage ratio. A formatted-string duration with unit "%"
    # and an implicit measurement state class breaks the HA sensor.
    assert transform.unit_for_path("latest_cycle.duration") is None
    assert transform.unit_for_path("current_program.remaining_duration") is None
    assert transform.state_class_for_path("latest_cycle.duration") is None


def test_unit_for_path_real_ratio_keys_are_percentages():
    assert transform.unit_for_path("current_program.load_ratio") == "%"
    assert transform.unit_for_path("current_program.salt_container_ratio") == "%"
    assert transform.unit_for_path("current_program.rinse_aid_container_ratio") == "%"


def test_value_class_for_path():
    assert transform.value_class_for_path("current_program.started_at") == "datetime"
    assert transform.value_class_for_path("current_program.remaining_time") == "duration"
    assert transform.value_class_for_path("device.status") is None


def test_is_diagnostic():
    assert transform.is_diagnostic("device.id") is True
    assert transform.is_diagnostic("current_program.program_id") is True
    assert transform.is_diagnostic("details.manufacturer") is True
    assert transform.is_diagnostic("device.status") is False
    assert transform.is_diagnostic("current_program.program_name") is False
    # The device name duplicates the HA device name -> diagnostic.
    assert transform.is_diagnostic("device.name") is True
    # The appliance location is low-value -> diagnostic.
    assert transform.is_diagnostic("device.location.name") is True
    assert transform.is_diagnostic("device.location.id") is True


def test_disabled_by_default():
    # Noisy technical fields are diagnostic AND disabled by default.
    assert transform.disabled_by_default("device.id") is True
    assert transform.disabled_by_default("details.manufacturer") is True
    # "Nom" is diagnostic but stays visible.
    assert transform.disabled_by_default("device.name") is False
    # Regular sensors are never disabled.
    assert transform.disabled_by_default("device.status") is False
    # Model and product group duplicate the HA device metadata -> hidden.
    assert transform.disabled_by_default("device.techType") is True
    assert transform.disabled_by_default("device.productGroup") is True
    # The location entity is hidden by default (diagnostic, not visible).
    assert transform.disabled_by_default("device.location.name") is True


def test_state_class_consumption_is_total_for_bar_chart():
    # Per-cycle consumption renders as bars (HA "metered entity") rather than a
    # flat measurement line: state class TOTAL instead of MEASUREMENT.
    assert transform.state_class_for_path("latest_cycle.water_consumption") == "total"
    assert transform.state_class_for_path("latest_cycle.energy_consumption") == "total"
    assert transform.state_class_for_path("latest_cycle.cold_water_consumption") == "total"
    assert transform.state_class_for_path("latest_cycle.warm_water_consumption") == "total"
    # Live measurements stay as measurement (line chart).
    assert transform.state_class_for_path("current_program.temperature_current") == "measurement"
    assert transform.state_class_for_path("current_program.water_volume") == "measurement"


# --------------------------------------------------------------------------- #
# native_value_for_path: duration -> minutes, timestamp -> aware datetime
# --------------------------------------------------------------------------- #


def test_native_value_duration_under_one_hour_in_minutes():
    # 1938 s ~= 32 min -> shown in minutes
    assert transform.native_value_for_path("current_program.remaining_time", 1938) == "32 min"


def test_native_value_duration_over_one_hour_in_hours():
    # 90 min -> "1 h 30 min", 120 min -> "2 h"
    assert transform.native_value_for_path("latest_cycle.duration", 90 * 60) == "1 h 30 min"
    assert transform.native_value_for_path("latest_cycle.duration", 120 * 60) == "2 h"
    assert transform.native_value_for_path("current_program.elapsed_time", 60 * 60) == "1 h"


def test_format_duration_minutes_boundaries():
    assert transform.format_duration_minutes(0) == "0 min"
    assert transform.format_duration_minutes(59 * 60) == "59 min"
    assert transform.format_duration_minutes(65 * 60) == "1 h 5 min"
    assert transform.format_duration_minutes(None) is None


# --------------------------------------------------------------------------- #
# water_volume: drop the appliance's non-reset accumulator residual
# --------------------------------------------------------------------------- #


def test_native_value_water_volume_keeps_plausible_cycle_values():
    # A real wash cycle accumulates a few tens of litres -> kept as-is.
    assert transform.native_value_for_path("current_program.water_volume", 0.0) == 0.0
    assert transform.native_value_for_path("current_program.water_volume", 45.6) == 45.6
    assert transform.native_value_for_path("current_program.water_volume", 51.8) == 51.8


def test_native_value_water_volume_drops_implausible_residual():
    # At the first program after an overnight idle, the appliance reports a
    # stale, non-reset "accumulated water volume" residual (~2045/2293 L) that
    # is physically impossible for one cycle -> dropped to None (unknown).
    assert transform.native_value_for_path("current_program.water_volume", 2293.7) is None
    assert transform.native_value_for_path("current_program.water_volume", 2045.0) is None


def test_native_value_water_volume_ceiling_boundary():
    ceiling = transform.WATER_VOLUME_MAX_LITERS
    assert transform.native_value_for_path("current_program.water_volume", ceiling) == ceiling
    assert transform.native_value_for_path("current_program.water_volume", ceiling + 0.1) is None


# --------------------------------------------------------------------------- #
# ratio / moisture: Miele reports 0-1 fractions, Home Assistant shows percent
# --------------------------------------------------------------------------- #


def test_native_value_residual_moisture_fraction_to_percent():
    # Miele returns residual moisture as a 0-1 fraction (0.07), but the entity
    # is a humidity sensor in %, so it must read 7 % and not 0.07 %.
    assert transform.native_value_for_path(
        "current_program.residual_moisture_current", 0.07
    ) == 7
    assert transform.native_value_for_path(
        "current_program.residual_moisture_target", 0.05
    ) == 5


def test_native_value_ratio_fraction_to_percent():
    # loadRatio / saltContainerRatio / rinseAidContainerRatio are 0-1 fractions.
    assert transform.native_value_for_path("current_program.load_ratio", 0.65) == 65
    assert transform.native_value_for_path("current_program.salt_container_ratio", 1.0) == 100
    assert transform.native_value_for_path(
        "current_program.rinse_aid_container_ratio", 0.8
    ) == 80


def test_native_value_percent_fraction_zero_and_none():
    assert transform.native_value_for_path("current_program.load_ratio", 0.0) == 0
    assert transform.native_value_for_path("current_program.residual_moisture_current", None) is None


def test_native_value_percent_already_scaled_is_left_untouched():
    # Defensive: a value already expressed as a percent (> 1) must not be scaled
    # by 100 again (no double conversion to 700 %).
    assert transform.native_value_for_path("current_program.residual_moisture_current", 7) == 7


def test_native_value_duration_is_not_scaled_as_percent():
    # Regression: "duration" contains the substring "ratio" but is a formatted
    # string, never a percentage -> must never be multiplied by 100.
    assert transform.native_value_for_path("latest_cycle.duration", 90 * 60) == "1 h 30 min"


def test_native_value_datetime_french_absolute_format():
    # Must be an absolute French string "22 mai 2026 à 10:00", never a relative
    # date, so Home Assistant shows the real date/time instead of "last week".
    value = transform.native_value_for_path(
        "current_program.started_at", "2026-05-22T08:00:00+02:00"
    )
    assert isinstance(value, str)
    assert re.fullmatch(r"\d{1,2} \S+ \d{4} à \d{2}:\d{2}", value)


def test_native_value_datetime_uses_french_month_name():
    # A naive datetime is treated as UTC; the month name is in French regardless
    # of the host locale.
    value = transform.native_value_for_path(
        "latest_cycle.started_at", "2026-05-22T08:00:00+00:00"
    )
    assert "mai 2026 à" in value


def test_native_value_datetime_invalid_returns_none():
    assert transform.native_value_for_path("latest_cycle.started_at", "n/a") is None


def test_native_value_status_translated():
    assert transform.native_value_for_path("device.status", "RUNNING") == "En cours"
    assert transform.native_value_for_path("latest_cycle.final_status", "failure") == "Échec"


def test_native_value_kind_translated():
    assert transform.native_value_for_path("device.kind", "CONNECTED") == "Connecté"
    assert transform.native_value_for_path("device.kind", "VIRTUAL") == "Virtuel"


def test_native_value_product_group_and_program_type_translated():
    assert transform.native_value_for_path("device.productGroup", "wm") == "Lave-linge"
    assert transform.native_value_for_path("current_program.type", "TD") == "Sèche-linge"
    assert transform.native_value_for_path("device.productGroup", "DW") == "Lave-vaisselle"


def test_native_value_sync_status_translated():
    assert transform.native_value_for_path("latest_cycle.sync_status", "pending") == "En attente"
    assert transform.native_value_for_path("latest_cycle.sync_status", "incomplete") == "Incomplet"


def test_current_program_drying_time_is_a_duration_object():
    # dryingTime is serialized as a Java Duration object; it must be converted
    # to seconds (it would otherwise be dropped as a dict) and formatted.
    details = {"currentProgram": {"details": {"type": "WD", "dryingTime": {"seconds": 2070}}}}
    summary = transform.build_current_program_summary(details)
    assert summary["drying_time"] == 2070
    assert transform.native_value_for_path("current_program.drying_time", 2070) == "34 min"


def test_sterilizer_timestamp_is_datetime():
    value = transform.native_value_for_path("current_program.timestamp", "2023-10-10T10:00:00Z")
    assert isinstance(value, str) and " à " in value


def test_latest_cycle_includes_sync_status():
    summary = transform.build_latest_cycle_summary({}, {"syncStatus": "completed"})
    assert summary["sync_status"] == "completed"


def test_pro_fields_have_french_labels():
    assert transform.friendly_name("current_program.conductivity") == "Conductivité"
    assert transform.friendly_name("current_program.cleaning_pressure") == "Pression de nettoyage"
    assert transform.friendly_name("current_program.temperature_tank1") == "Température cuve 1"
    assert transform.friendly_name("current_program.a0") == "Valeur A0"


# --------------------------------------------------------------------------- #
# sort_executions_desc: defensive ordering by startedAt desc
#
# The OpenAPI contract (https://www.miele-move.com/api-docs/json/app) does not
# document any ordering for /devices/{fabNr}/executions, so we sort explicitly
# rather than relying on the API returning index 0 as the most recent.
# --------------------------------------------------------------------------- #


def test_sort_executions_desc_orders_by_started_at():
    executions = [
        {"executionId": "old", "startedAt": "2026-05-01T08:00:00Z"},
        {"executionId": "new", "startedAt": "2026-05-20T08:00:00Z"},
        {"executionId": "mid", "startedAt": "2026-05-10T08:00:00Z"},
    ]
    sorted_list = transform.sort_executions_desc(executions)
    assert [item["executionId"] for item in sorted_list] == ["new", "mid", "old"]


def test_sort_executions_desc_pushes_missing_started_at_to_end():
    executions = [
        {"executionId": "no-date"},
        {"executionId": "new", "startedAt": "2026-05-20T08:00:00Z"},
        {"executionId": "bad-date", "startedAt": "not-a-date"},
    ]
    sorted_list = transform.sort_executions_desc(executions)
    assert sorted_list[0]["executionId"] == "new"
    # Items without a parseable startedAt are kept (at the tail), not dropped.
    tail_ids = {item["executionId"] for item in sorted_list[1:]}
    assert tail_ids == {"no-date", "bad-date"}


def test_sort_executions_desc_returns_empty_for_empty_input():
    assert transform.sort_executions_desc([]) == []


# --------------------------------------------------------------------------- #
# pick_latest_finalized: skip unfinalized "unknown" cycles
#
# When a program just ends, Miele's cloud creates the new execution row but
# leaves programStatus = "unknown" until the device-to-cloud sync finalizes the
# cycle. Surfacing that transient "unknown" pollutes Home Assistant's history
# graph for "État dernier cycle" with an "Inconnu" segment between two
# "Terminé" segments. We skip it and fall back to the most recent finalized
# cycle until the new one finalizes.
# --------------------------------------------------------------------------- #


def test_pick_latest_finalized_skips_unknown_cycles():
    executions = [
        {"executionId": "fresh", "programStatus": "unknown"},
        {"executionId": "previous", "programStatus": "completed"},
    ]
    details = [
        {"executionId": "fresh", "programStatus": "unknown"},
        {"executionId": "previous", "programStatus": "completed"},
    ]
    execution, detail = transform.pick_latest_finalized(executions, details)
    assert execution["executionId"] == "previous"
    assert detail["executionId"] == "previous"


def test_pick_latest_finalized_status_from_detail_takes_precedence():
    # If the list item lacks programStatus but the detail has one, use the
    # detail's status to decide finalization.
    executions = [{"executionId": "fresh"}, {"executionId": "previous"}]
    details = [
        {"executionId": "fresh", "programStatus": "unknown"},
        {"executionId": "previous", "programStatus": "completed"},
    ]
    execution, _ = transform.pick_latest_finalized(executions, details)
    assert execution["executionId"] == "previous"


def test_pick_latest_finalized_treats_failure_and_cancelled_as_finalized():
    # `failure` and `cancelled` are legitimate terminal statuses, not transients.
    executions = [
        {"executionId": "failed-cycle", "programStatus": "failure"},
        {"executionId": "old", "programStatus": "completed"},
    ]
    execution, _ = transform.pick_latest_finalized(executions, [])
    assert execution["executionId"] == "failed-cycle"


def test_pick_latest_finalized_falls_back_when_all_unknown():
    # If every cycle is still "unknown", surface the most recent one rather
    # than hiding the latest-cycle sensors entirely.
    executions = [
        {"executionId": "a", "programStatus": "unknown"},
        {"executionId": "b", "programStatus": "unknown"},
    ]
    execution, _ = transform.pick_latest_finalized(executions, [])
    assert execution["executionId"] == "a"


def test_pick_latest_finalized_empty_inputs():
    assert transform.pick_latest_finalized([], []) == ({}, {})


def test_pick_latest_finalized_handles_details_shorter_than_executions():
    # Coordinator only fetches details for the top N executions (default 5).
    # Picking the 6th finalized execution must still work (with empty detail).
    executions = [
        {"executionId": "0", "programStatus": "unknown"},
        {"executionId": "1", "programStatus": "completed"},
    ]
    details = [{"executionId": "0", "programStatus": "unknown"}]
    execution, detail = transform.pick_latest_finalized(executions, details)
    assert execution["executionId"] == "1"
    assert detail == {}


# --------------------------------------------------------------------------- #
# is_finalized_program_status
# --------------------------------------------------------------------------- #


def test_is_finalized_program_status_true_for_finished():
    assert transform.is_finalized_program_status("finished") is True
    assert transform.is_finalized_program_status("COMPLETED") is True
    assert transform.is_finalized_program_status(" aborted ") is True


def test_is_finalized_program_status_false_for_unknown_or_non_string():
    assert transform.is_finalized_program_status("unknown") is False
    assert transform.is_finalized_program_status(None) is False
    assert transform.is_finalized_program_status(123) is False


# --------------------------------------------------------------------------- #
# stale_field_value (live fields no longer meaningful once a device is retained)
# --------------------------------------------------------------------------- #


def test_stale_field_value_marks_live_status_offline():
    assert transform.stale_field_value("device.status", "running") == "offline"
    assert transform.stale_field_value("details.status", "running") == "offline"


def test_stale_field_value_blanks_current_program_fields():
    # The running-program snapshot (remaining time, phase, ...) is frozen and
    # misleading once the cycle is over: it must clear to unknown.
    assert transform.stale_field_value("current_program.remaining_time", 60) is None
    assert transform.stale_field_value("current_program.phase", "Rinçage") is None
    assert transform.stale_field_value("current_program.elapsed_time", 1800) is None


def test_stale_field_value_keeps_other_fields():
    assert transform.stale_field_value("latest_cycle.final_status", "finished") == "finished"
    assert transform.stale_field_value("details.model", "WCI870") == "WCI870"


def test_offline_translates_to_french():
    assert transform.translate_status("offline") == "Hors ligne"


# --------------------------------------------------------------------------- #
# build_current_program_summary gating (program not running -> no live summary)
# --------------------------------------------------------------------------- #


def test_current_program_summary_empty_when_not_running():
    details = {
        "currentProgram": {
            "name": "Coton",
            "phaseName": "Rinçage",
            "remainingTime": {"seconds": 60},
        }
    }
    assert transform.build_current_program_summary(details, program_running=False) == {}


def test_current_program_summary_present_when_running():
    details = {
        "currentProgram": {
            "name": "Coton",
            "remainingTime": {"seconds": 1800},
        }
    }
    summary = transform.build_current_program_summary(details, program_running=True)
    assert summary["program_name"] == "Coton"
    assert summary["remaining_time"] == 1800


def test_current_program_summary_defaults_to_running():
    # Backwards-compatible default: omitting the flag keeps the legacy behaviour.
    details = {"currentProgram": {"name": "Coton"}}
    assert transform.build_current_program_summary(details)["program_name"] == "Coton"
