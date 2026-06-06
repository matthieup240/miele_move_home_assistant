"""Pure transformation, naming and classification logic for Miele MOVE.

This module deliberately has no Home Assistant dependency so it can be unit
tested in isolation. The sensor/coordinator layers adapt its results to HA.

All field names and enums handled here come from the official Miele MOVE
OpenAPI contract (https://www.miele-move.com/api-docs/json/app):
- DeviceDetails.currentProgram uses keys name / phaseName, and serializes
  remainingTime / elapsedTime as Java Duration objects ({"seconds": ...}),
- ProgramExecution(Details).programStatus is one of
  completed / cancelled / failure / unknown,
- ConsumptionValue.type is energy / water / cold_water / warm_water / ... with
  unit one of kg / l / ml / pcs / wh / unknown.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

# Value used by Miele for unsupported / not-currently-available fields.
MISSING_SENTINEL = -32768

# Physically implausible ceiling (litres) for one program's accumulated water.
# WashingProgramDetails.waterVolume is an "accumulated" counter the appliance
# does not reset at the first program after an overnight idle: it reports a
# stale residual (observed ~2045-2337 L) that then drops back to 0. A real home
# wash cycle stays well under this, so readings above the ceiling are dropped
# (-> unknown) rather than displayed and fed into long-term statistics.
WATER_VOLUME_MAX_LITERS = 150

# --------------------------------------------------------------------------- #
# Durations
# --------------------------------------------------------------------------- #

_ISO_DURATION_PATTERN = re.compile(
    r"^P"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)


def duration_to_seconds(value: Any) -> int | float | None:
    """Return a duration in seconds from any shape the API may use.

    Accepts a plain number (already seconds), an ISO 8601 string (``PT32M18S``)
    or a serialized Java ``Duration`` object (``{"seconds": 1938, ...}``).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        seconds = value.get("seconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            return int(seconds)
        return None
    if not isinstance(value, str):
        return None

    match = _ISO_DURATION_PATTERN.match(value)
    if not match or value == "P":
        return None

    seconds = (
        float(match.group("days") or 0) * 86400
        + float(match.group("hours") or 0) * 3600
        + float(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )
    return int(seconds) if seconds.is_integer() else round(seconds, 3)


def format_duration_minutes(value: Any) -> str | None:
    """Format a duration as minutes, switching to hours past 60 minutes.

    Examples: ``45 min``, ``1 h 30 min``, ``2 h``.
    """
    seconds_value = duration_to_seconds(value)
    if seconds_value is None:
        return None

    minutes = int(round(seconds_value / 60))
    if minutes < 60:
        return f"{minutes} min"

    hours, remaining_minutes = divmod(minutes, 60)
    if remaining_minutes == 0:
        return f"{hours} h"
    return f"{hours} h {remaining_minutes} min"


# --------------------------------------------------------------------------- #
# Status translation (device status enum + programStatus enum)
# --------------------------------------------------------------------------- #

_STATUS_TRANSLATIONS = {
    # Device.status / DeviceDetails.status (UPPER_SNAKE in the contract)
    "off": "Éteint",
    "standby": "Veille",
    "programmed": "Programmé",
    "waiting_to_start": "En attente de démarrage",
    "running": "En cours",
    "paused": "En pause",
    "completed": "Terminé",
    "error": "Erreur",
    "cancelled": "Annulé",
    "canceled": "Annulé",
    "service": "Maintenance",
    "locked": "Verrouillé",
    "not_connected": "Non connecté",
    "busy": "Occupé",
    "removed": "Retiré",
    "unknown": "Inconnu",
    # ProgramExecution.programStatus (lower in the contract)
    "failure": "Échec",
    "failed": "Échec",
    "aborted": "Interrompu",
    "finished": "Terminé",
    # Device.kind enum
    "connected": "Connecté",
    "virtual": "Virtuel",
    # productGroup / program type enum (WM/TD/DW/WD/ST)
    "wm": "Lave-linge",
    "td": "Sèche-linge",
    "dw": "Lave-vaisselle",
    "wd": "Laveur-désinfecteur",
    "st": "Stérilisateur",
    # ProgramExecutionDetails.syncStatus enum
    "pending": "En attente",
    "incomplete": "Incomplet",
    # Synthetic value used when a device left the /devices listing (cycle ended)
    # and we no longer receive its live status.
    "offline": "Hors ligne",
}

# Live-status flat paths whose value is replaced by "offline" when the device
# is retained from a previous tick (no longer listed by the API).
LIVE_STATUS_PATHS = frozenset({"device.status", "details.status"})

# Flat-path prefix for the running-program snapshot (remaining time, phase,
# temperature, ...). These describe a cycle in progress, so they are cleared
# for a retained device whose cycle has ended.
LIVE_PROGRAM_PREFIX = "current_program."


def translate_status(value: Any) -> Any:
    """Translate a Miele status/programStatus enum value to French."""
    if not isinstance(value, str):
        return value
    return _STATUS_TRANSLATIONS.get(value.strip().lower(), value)


# Program-name overrides: Miele returns abbreviated French labels for some
# programs. Keyed by a normalized form (lowercased, trailing period/spaces
# stripped) so capitalization and punctuation variants all match.
_PROGRAM_NAME_TRANSLATIONS = {
    "couette synth": "Couette synthétique",
}


def translate_program_name(value: Any) -> Any:
    """Expand known abbreviated Miele program names; pass others through."""
    if not isinstance(value, str):
        return value
    key = value.strip().rstrip(".").strip().lower()
    return _PROGRAM_NAME_TRANSLATIONS.get(key, value)


# --------------------------------------------------------------------------- #
# Consumption extraction
# --------------------------------------------------------------------------- #


def _to_liters(value: float, unit: str) -> float:
    return round(value / 1000, 3) if unit == "ml" else value


def _to_kwh(value: float, unit: str) -> float:
    return round(value / 1000, 3) if unit == "wh" else value


_CONSUMPTION_TARGETS = {
    "energy": ("energy_consumption", _to_kwh),
    "water": ("water_consumption", _to_liters),
    "cold_water": ("cold_water_consumption", _to_liters),
    "warm_water": ("warm_water_consumption", _to_liters),
    "ve_water": ("ve_water_consumption", _to_liters),
}


def extract_consumption(*sources: Any) -> dict[str, Any]:
    """Extract energy/water consumption from ProgramExecutionDetails payloads.

    Each ConsumptionValue type maps to its own key (no overwrite between
    water / cold_water / warm_water) and units are normalized (wh->kWh, ml->L).
    """
    values: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        raw_values = source.get("consumptionValues")
        if not isinstance(raw_values, list):
            continue
        for item in raw_values:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "").strip().lower()
            target = _CONSUMPTION_TARGETS.get(kind)
            if target is None:
                continue
            amount = item.get("value")
            if amount in (None, ""):
                continue
            unit = str(item.get("unit") or "").strip().lower()
            key, converter = target
            try:
                values[key] = converter(float(amount), unit)
            except (TypeError, ValueError):
                values[key] = amount
    return values


# --------------------------------------------------------------------------- #
# Summaries built from the real nested payloads
# --------------------------------------------------------------------------- #


def build_current_program_summary(
    details: Any, program_running: bool = True
) -> dict[str, Any]:
    """Build a clean current-program summary from DeviceDetails.currentProgram.

    Reduces the Java Duration objects (remainingTime/elapsedTime) to seconds and
    drops their internal noise (nano/zero/negative/units).

    `program_running` guards against a stale snapshot: the API may keep
    currentProgram populated (with a residual remainingTime) after a cycle ends
    until the appliance powers off. When the program is no longer running the
    summary is empty, so "Temps restant"/"Phase" clear instead of freezing.
    """
    if not program_running:
        return {}
    if not isinstance(details, dict):
        return {}
    program = details.get("currentProgram")
    if not isinstance(program, dict):
        return {}

    summary: dict[str, Any] = {
        "program_name": translate_program_name(program.get("name")),
        "phase": program.get("phaseName"),
        "program_id": program.get("id"),
        "started_at": program.get("startedAt"),
        "stopped_at": program.get("stoppedAt"),
        "remaining_time": duration_to_seconds(program.get("remainingTime")),
        "elapsed_time": duration_to_seconds(program.get("elapsedTime")),
    }

    # currentProgram.details is polymorphic (discriminator `type`): a washing
    # machine yields WashingProgramDetails (temperature/spin/load), a dryer
    # DryingProgramDetails, etc. Surface every scalar so nothing is lost.
    program_details = program.get("details")
    if isinstance(program_details, dict):
        summary["type"] = program_details.get("type")
        for key, value in program_details.items():
            if key == "type":
                continue
            if key in ("extras", "options"):
                names = _option_names(value)
                if names:
                    summary["options"] = names
                continue
            if isinstance(value, dict):
                # Some fields (e.g. dryingTime) are Java Duration objects.
                seconds = duration_to_seconds(value)
                if seconds is not None:
                    summary[_camel_to_snake(key)] = seconds
                continue
            if isinstance(value, list):
                continue
            if value in (None, "", MISSING_SENTINEL):
                continue
            summary[_camel_to_snake(key)] = value

    return {key: value for key, value in summary.items() if value not in (None, "")}


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _option_names(raw: Any) -> str | None:
    if not isinstance(raw, list):
        return None
    names: list[str] = []
    for option in raw:
        if isinstance(option, str) and option:
            names.append(option)
        elif isinstance(option, dict):
            # `name` is the readable label (official Extra schema); `type` is the
            # uppercase code, kept as a last resort so the entity is never empty.
            for field in ("name", "value_localized", "localized", "label", "value", "type"):
                value = option.get(field)
                if isinstance(value, str) and value:
                    names.append(value)
                    break
    return ", ".join(names) if names else None


def sort_executions_desc(executions: list[Any]) -> list[Any]:
    """Sort program executions by startedAt descending.

    The Miele MOVE OpenAPI contract does not document the ordering of
    /devices/{fabNr}/executions, so we sort defensively rather than assuming
    index 0 is the most recent. Items with a missing or unparseable startedAt
    are kept at the tail (rather than dropped) so nothing silently disappears.
    """
    if not executions:
        return []

    indexed = list(enumerate(executions))
    indexed.sort(
        key=lambda pair: (
            _parse_datetime(pair[1].get("startedAt") if isinstance(pair[1], dict) else None)
            or datetime.min.replace(tzinfo=timezone.utc),
            -pair[0],
        ),
        reverse=True,
    )
    return [item for _, item in indexed]


# programStatus values that indicate the cycle has been finalized by Miele's
# cloud. Anything outside this set (notably "unknown") means the device-to-cloud
# sync is still in flight after the program just ended.
_FINALIZED_PROGRAM_STATUSES = frozenset({"completed", "cancelled", "canceled", "failure", "failed", "finished", "aborted"})


def is_finalized_program_status(value: Any) -> bool:
    """True if a programStatus value marks the cycle as finalized by the cloud."""
    return isinstance(value, str) and value.strip().lower() in _FINALIZED_PROGRAM_STATUSES


def stale_field_value(path: str, value: Any) -> Any:
    """Adjust a frozen field's value for a retained (stale) device.

    Called only when the device left the listing. Live-only fields are
    misleading once the cycle ended, so:
    - live-status paths report "offline" (-> "Hors ligne");
    - running-program paths clear to None (-> unknown);
    - every other field keeps its last known value.
    """
    if path in LIVE_STATUS_PATHS:
        return "offline"
    if path.startswith(LIVE_PROGRAM_PREFIX):
        return None
    return value


def pick_latest_finalized(
    executions: list[Any], execution_details: list[Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick the (execution, detail) pair for the most recent finalized cycle.

    Miele's API creates a new execution row as soon as a program ends, but
    leaves programStatus = "unknown" until the cloud finalizes the cycle (the
    syncStatus field on ProgramExecutionDetails also moves through
    pending/incomplete during this window). Surfacing that transient "unknown"
    pollutes Home Assistant's history graph for the "État dernier cycle"
    sensor with an "Inconnu" segment between two "Terminé" segments.

    We therefore skip executions whose status is still "unknown" and fall
    back to the previous finalized cycle. If every cycle is unfinalized,
    return the most recent so the sensors are never empty.
    """
    if not executions:
        return {}, {}

    for index, execution in enumerate(executions):
        detail = execution_details[index] if index < len(execution_details) else {}
        status = _program_status(execution, detail)
        if status in _FINALIZED_PROGRAM_STATUSES:
            return (
                execution if isinstance(execution, dict) else {},
                detail if isinstance(detail, dict) else {},
            )

    fallback_execution = executions[0] if isinstance(executions[0], dict) else {}
    fallback_detail = (
        execution_details[0]
        if execution_details and isinstance(execution_details[0], dict)
        else {}
    )
    return fallback_execution, fallback_detail


def _program_status(*payloads: Any) -> str | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        value = payload.get("programStatus")
        if isinstance(value, str) and value:
            return value.strip().lower()
    return None


def build_latest_cycle_summary(
    latest_execution: Any, latest_execution_detail: Any
) -> dict[str, Any]:
    """Build a readable last-cycle summary from ProgramExecution(+Details)."""
    sources = [
        payload
        for payload in (latest_execution_detail, latest_execution)
        if isinstance(payload, dict)
    ]
    if not sources:
        return {}

    summary: dict[str, Any] = {}
    _set_first(summary, "program_name", sources, ("programName",))
    if "program_name" in summary:
        summary["program_name"] = translate_program_name(summary["program_name"])
    _set_first(summary, "final_status", sources, ("programStatus",))
    _set_first(summary, "sync_status", sources, ("syncStatus",))
    _set_first(summary, "started_at", sources, ("startedAt",))
    _set_first(summary, "stopped_at", sources, ("stoppedAt",))

    for source in sources:
        seconds = duration_to_seconds(source.get("duration"))
        if seconds is not None:
            summary["duration"] = seconds
            break

    # Fallback: derive the duration from the start/stop timestamps when the API
    # does not provide a usable `duration` field.
    if "duration" not in summary:
        start = _parse_datetime(summary.get("started_at"))
        stop = _parse_datetime(summary.get("stopped_at"))
        if start and stop and stop > start:
            summary["duration"] = int((stop - start).total_seconds())

    summary.update(extract_consumption(*sources))
    return {key: value for key, value in summary.items() if value not in (None, "")}


def _set_first(
    target: dict[str, Any],
    target_key: str,
    sources: list[dict[str, Any]],
    source_keys: tuple[str, ...],
) -> None:
    for source in sources:
        for source_key in source_keys:
            value = source.get(source_key)
            if value not in (None, ""):
                target[target_key] = value
                return


# --------------------------------------------------------------------------- #
# Naming and path classification
# --------------------------------------------------------------------------- #


def _normalize(value: str) -> str:
    return value.replace("_", "").replace("-", "").lower()


def _normalized_path(path: str) -> str:
    """Lowercase, strip separators, drop list indices, join by dots."""
    parts = [_normalize(part) for part in path.split(".") if not part.isdigit()]
    return ".".join(parts)


# Exact labels keyed by normalized path. Disambiguated by source group so the
# same underlying field never collides between live state and history.
_EXACT_LABELS: dict[str, str] = {
    # Live device fields
    "device.name": "Nom",
    "device.status": "État actuel",
    "device.kind": "Connexion",
    "device.productgroup": "Type d'appareil",
    "device.techtype": "Modèle",
    "device.materialnumber": "Numéro de matériel",
    "device.id": "Identifiant",
    "device.location.name": "Emplacement",
    "device.location.id": "Identifiant emplacement",
    # Current program (live)
    "currentprogram.programname": "Programme en cours",
    "currentprogram.phase": "Phase en cours",
    "currentprogram.programid": "ID du programme en cours",
    "currentprogram.startedat": "Début du programme",
    "currentprogram.stoppedat": "Fin du programme",
    "currentprogram.remainingtime": "Temps restant",
    "currentprogram.elapsedtime": "Temps écoulé",
    "currentprogram.type": "Type de programme",
    # Current program details (polymorphic per device type)
    "currentprogram.temperaturecurrent": "Température actuelle",
    "currentprogram.temperaturetarget": "Température cible",
    "currentprogram.airtemperaturecurrent": "Température d'air actuelle",
    "currentprogram.airtemperaturetarget": "Température d'air cible",
    "currentprogram.chambertemperature": "Température de chambre",
    "currentprogram.theoreticaltemperature": "Température théorique",
    "currentprogram.spinningspeedcurrent": "Essorage actuel",
    "currentprogram.spinningspeedtarget": "Essorage cible",
    "currentprogram.loadweight": "Charge",
    "currentprogram.setweight": "Charge cible",
    "currentprogram.maxweight": "Charge nominale",
    "currentprogram.loadratio": "Taux de charge",
    "currentprogram.watervolume": "Volume d'eau",
    "currentprogram.waterlevel": "Niveau d'eau",
    "currentprogram.waterconsumptiontotal": "Eau consommée (total)",
    "currentprogram.waterconsumptioncurrent": "Eau consommée (en cours)",
    "currentprogram.residualmoisturecurrent": "Humidité résiduelle actuelle",
    "currentprogram.residualmoisturetarget": "Humidité résiduelle cible",
    "currentprogram.saltcontainerratio": "Niveau de sel",
    "currentprogram.rinseaidcontainerratio": "Niveau de liquide de rinçage",
    "currentprogram.options": "Options",
    # Disinfector / sterilizer details (pro equipment)
    "currentprogram.a0": "Valeur A0",
    "currentprogram.conductivity": "Conductivité",
    "currentprogram.cleaningpressure": "Pression de nettoyage",
    "currentprogram.chamberpressure": "Pression de chambre",
    "currentprogram.dryingtime": "Temps de séchage",
    "currentprogram.temperaturebottom": "Température (bas)",
    "currentprogram.temperaturecenter": "Température (centre)",
    "currentprogram.temperaturemain": "Température principale",
    "currentprogram.temperaturetank1": "Température cuve 1",
    "currentprogram.temperaturetank2": "Température cuve 2",
    "currentprogram.temperaturedrying": "Température de séchage",
    "currentprogram.temperaturedryingtarget": "Température de séchage cible",
    "currentprogram.temperaturewater1": "Température eau 1",
    "currentprogram.temperaturewater1target": "Température eau 1 cible",
    "currentprogram.chargeid": "ID de charge",
    "currentprogram.timestamp": "Horodatage",
    "currentprogram.phasename": "Phase",
    # Latest cycle extra
    "latestcycle.syncstatus": "État de synchronisation dernier cycle",
    # Latest cycle (history)
    "latestcycle.programname": "Programme dernier cycle",
    "latestcycle.finalstatus": "État dernier cycle",
    "latestcycle.startedat": "Début dernier cycle",
    "latestcycle.stoppedat": "Fin dernier cycle",
    "latestcycle.duration": "Durée dernier cycle",
    "latestcycle.energyconsumption": "Consommation d'énergie dernier cycle",
    "latestcycle.waterconsumption": "Consommation d'eau dernier cycle",
    "latestcycle.coldwaterconsumption": "Eau froide dernier cycle",
    "latestcycle.warmwaterconsumption": "Eau chaude dernier cycle",
    "latestcycle.vewaterconsumption": "Eau déminéralisée dernier cycle",
    # Details (diagnostic)
    "details.manufacturer": "Fabricant",
    "details.commissionedat": "Date de mise en service",
    "details.status": "État (détails)",
    "details.name": "Nom (détails)",
    "details.techtype": "Modèle (détails)",
    "details.productgroup": "Type d'appareil (détails)",
}

_GROUP_PREFIXES = ("device", "details", "currentprogram", "latestcycle")


def friendly_name(path: str) -> str:
    """Return a French label for a flattened payload path."""
    normalized = _normalized_path(path)
    if normalized in _EXACT_LABELS:
        return _EXACT_LABELS[normalized]

    # Fallback: humanize the trailing segments, dropping the known group prefix.
    raw_parts = [part for part in path.split(".") if not part.isdigit()]
    cleaned = [
        part for part in raw_parts if _normalize(part) not in _GROUP_PREFIXES
    ]
    label = " ".join(_split_words(part) for part in cleaned).strip()
    return label or "Info"


def _split_words(value: str) -> str:
    result = ""
    for index, char in enumerate(value):
        if index > 0 and char.isupper() and value[index - 1].islower():
            result += " "
        result += char.replace("_", " ").replace("-", " ")
    return " ".join(result.split()).title()


# Trailing segment classes
_DATETIME_KEYS = {"startedat", "stoppedat", "commissionedat", "endedat", "endtime", "starttime", "estimatedendtime", "timestamp"}
_DURATION_KEYS = {"remainingtime", "elapsedtime", "duration", "remainingduration", "dryingtime"}
_STATUS_KEYS = {"status", "finalstatus", "kind", "productgroup", "type", "syncstatus"}
_DIAGNOSTIC_KEYS = {
    "id",
    "kind",
    "materialnumber",
    "uuid",
    "serial",
    "programid",
    "type",
    "techtype",
    "productgroup",
}
_ENERGY_KEYS = {"energyconsumption"}
_WATER_KEYS = {"waterconsumption", "coldwaterconsumption", "warmwaterconsumption", "vewaterconsumption"}
# Per-cycle consumption totals: exposed with state class TOTAL so Home Assistant
# renders them as bars (a "metered entity") instead of a flat measurement line.
_CONSUMPTION_TOTAL_KEYS = _ENERGY_KEYS | _WATER_KEYS


def _last_key(path: str) -> str:
    parts = [_normalize(part) for part in path.split(".") if not part.isdigit()]
    return parts[-1] if parts else ""


def value_class_for_path(path: str) -> str | None:
    """Return a value class hint: 'datetime', 'duration' or None.

    Dates use 'datetime' (rendered as an absolute formatted string) rather than
    a HA timestamp device class, which Home Assistant displays relatively
    ("last week"). The user wants the real date and time shown.
    """
    last = _last_key(path)
    if last in _DATETIME_KEYS:
        return "datetime"
    if last in _DURATION_KEYS:
        return "duration"
    return None


def unit_for_path(path: str) -> str | None:
    """Return the native unit of measurement for a path, if any."""
    last = _last_key(path)
    if last in _ENERGY_KEYS:
        return "kWh"
    if last in _WATER_KEYS or last in ("watervolume", "waterconsumptiontotal", "waterconsumptioncurrent"):
        return "L"
    if last == "waterlevel":
        return "mm"
    if "temperature" in last:
        return "°C"
    if "spinningspeed" in last:
        return "tr/min"
    if last.endswith("weight"):
        return "kg"
    # `endswith` (not substring): the ratio fields all end in "ratio"
    # (loadRatio / saltContainerRatio / rinseAidContainerRatio), whereas a
    # substring match would wrongly catch "du-ratio-n" and tag durations "%".
    if last.endswith("ratio") or "moisture" in last:
        return "%"
    return None


def device_class_for_path(path: str) -> str | None:
    """Return a measurement device-class hint: 'temperature', 'weight',
    'humidity' or None."""
    last = _last_key(path)
    if "temperature" in last:
        return "temperature"
    if last.endswith("weight"):
        return "weight"
    if "moisture" in last:
        return "humidity"
    return None


def state_class_for_path(path: str) -> str | None:
    """Return the state class hint: 'total' for per-cycle consumption (bars),
    'measurement' for live numeric sensors (line), else None."""
    last = _last_key(path)
    if last in _CONSUMPTION_TOTAL_KEYS:
        return "total"
    if unit_for_path(path) in ("°C", "tr/min", "kg", "%", "L", "mm"):
        return "measurement"
    return None


# Diagnostic but kept visible (not disabled by default).
_VISIBLE_DIAGNOSTIC_PATHS = {"device.name"}

# Diagnostic AND hidden by default: low-value fields the user does not want
# surfaced on the device page (e.g. the appliance location).
_HIDDEN_DIAGNOSTIC_PATHS = {"device.location.name", "device.location.id"}


def is_diagnostic(path: str) -> bool:
    """Return True for fields that belong to the diagnostic category."""
    normalized = _normalized_path(path)
    if normalized in _VISIBLE_DIAGNOSTIC_PATHS:
        return True
    if normalized in _HIDDEN_DIAGNOSTIC_PATHS:
        return True
    if normalized.startswith("details."):
        return True
    return _last_key(path) in _DIAGNOSTIC_KEYS


def disabled_by_default(path: str) -> bool:
    """Return True for diagnostic fields that should also be hidden by default."""
    return is_diagnostic(path) and _normalized_path(path) not in _VISIBLE_DIAGNOSTIC_PATHS


def native_value_for_path(path: str, value: Any) -> Any:
    """Apply value transformations based on the path classification."""
    value_class = value_class_for_path(path)
    if value_class == "datetime":
        return _format_local_datetime(value)
    if value_class == "duration":
        return format_duration_minutes(value)
    if _last_key(path) in _STATUS_KEYS:
        return translate_status(value)
    if _last_key(path) == "watervolume" and _exceeds_water_volume_ceiling(value):
        return None
    return value


def _exceeds_water_volume_ceiling(value: Any) -> bool:
    """True for a water-volume reading above the physical per-cycle ceiling."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > WATER_VOLUME_MAX_LITERS
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


_FRENCH_MONTHS = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}


def _format_local_datetime(value: Any) -> str | None:
    """Format an ISO datetime as an absolute local French string.

    Example: ``22 mai 2026 à 10:00``. The month name is always French,
    independently of the host locale.
    """
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    local = parsed.astimezone()
    return f"{local.day} {_FRENCH_MONTHS[local.month]} {local.year} à {local:%H:%M}"
