"""Coordinator for Miele MOVE data."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import reconcile, transform
from .api import (
    MieleMoveApiClient,
    MieleMoveApiError,
    MieleMoveAuthError,
    MieleMoveRateLimitError,
)
from .const import (
    CONF_ACCEPT_LANGUAGE,
    CONF_BASE_URL,
    CONF_DEVICE_TTL_SECONDS,
    CONF_FAST_INTERVAL_SECONDS,
    CONF_MAX_EXECUTION_DETAILS,
    CONF_SCAN_INTERVAL_SECONDS,
    CONF_SLOW_INTERVAL_SECONDS,
    DEFAULT_ACCEPT_LANGUAGE,
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE_TTL_SECONDS,
    DEFAULT_FAST_INTERVAL_SECONDS,
    DEFAULT_MAX_EXECUTION_DETAILS,
    DEFAULT_SLOW_INTERVAL_SECONDS,
    DEVICES_SAVE_DELAY_SECONDS,
    DOMAIN,
    FINAL_HISTORY_REFRESH_ATTEMPTS,
    HISTORY_REFRESH_TICKS,
    STORAGE_VERSION,
    UPDATE_TIMEOUT_SECONDS,
)
from .fetchers import fetch_device_history, fetch_live_state
from .helpers import (
    flatten_scalars,
    infer_device_name,
    infer_execution_id,
    infer_fab_nr,
    infer_model,
    is_device_active,
    iter_executions,
    merge_refreshed_cycle_flat,
    stable_flat,
)
from .policy import next_update_interval_seconds, should_refresh_history

LOGGER = logging.getLogger(__name__)

# Fields of DeviceDetails that are summarized separately or too noisy to flatten.
_DETAILS_EXCLUDED_FROM_FLAT = ("currentProgram", "serviceIntervals")


class MieleMoveDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and normalize data from Miele MOVE."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.config_entry = config_entry
        data = {**config_entry.data, **config_entry.options}
        self.client = MieleMoveApiClient(
            session=async_get_clientsession(hass),
            api_key=config_entry.data["api_key"],
            base_url=data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            accept_language=data.get(CONF_ACCEPT_LANGUAGE, DEFAULT_ACCEPT_LANGUAGE),
        )
        self.max_execution_details = int(
            data.get(CONF_MAX_EXECUTION_DETAILS, DEFAULT_MAX_EXECUTION_DETAILS)
        )
        self._fast_interval = int(
            data.get(CONF_FAST_INTERVAL_SECONDS, DEFAULT_FAST_INTERVAL_SECONDS)
        )
        # Legacy scan_interval_seconds is migrated to slow_interval_seconds.
        self._slow_interval = int(
            data.get(
                CONF_SLOW_INTERVAL_SECONDS,
                data.get(CONF_SCAN_INTERVAL_SECONDS, DEFAULT_SLOW_INTERVAL_SECONDS),
            )
        )
        self._device_ttl_seconds = int(
            data.get(CONF_DEVICE_TTL_SECONDS, DEFAULT_DEVICE_TTL_SECONDS)
        )
        self._previous_active: dict[str, bool] = {}
        self._ticks_since_history: dict[str, int] = {}
        self._final_refresh_attempts: dict[str, int] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{config_entry.entry_id}_devices"
        )

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._slow_interval),
        )

    async def async_load_persisted(self) -> None:
        """Preload the retained device map so entities exist before the first poll.

        Without this, restarting Home Assistant while an appliance is off (hence
        absent from /devices) leaves its entities orphaned and unavailable. The
        reloaded entry is reconciled on the first refresh (kept stale within the
        TTL, refreshed if the appliance is back).
        """
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("devices"), dict):
            self.data = {"raw_devices": {}, "devices": stored["devices"]}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all useful information exposed by the API."""
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT_SECONDS):
                return await self._fetch_all()
        except MieleMoveAuthError as err:
            raise ConfigEntryAuthFailed from err
        except MieleMoveRateLimitError as err:
            # Back off to at least the slow interval (or the server hint, whichever is longer).
            backoff = max(self._slow_interval, err.retry_after or 0)
            self.update_interval = timedelta(seconds=backoff)
            LOGGER.warning(
                "Miele MOVE API rate-limited; backing off for %s s", backoff
            )
            raise UpdateFailed(str(err)) from err
        except MieleMoveApiError as err:
            raise UpdateFailed(str(err)) from err
        except TimeoutError as err:
            raise UpdateFailed("Miele MOVE API timed out") from err

    async def _fetch_all(self) -> dict[str, Any]:
        now = dt_util.utcnow()
        devices_payload = await self.client.async_get_devices()
        live = await fetch_live_state(devices_payload, self._safe_get_device)

        previous_devices = (
            self.data.get("devices", {}) if isinstance(self.data, dict) else {}
        )
        devices: dict[str, Any] = {}
        any_active = False

        for device_id, parts in live.items():
            device_payload = parts["device"]
            detail_payload = parts["details"]

            merged_for_id = _merge_dicts(device_payload, detail_payload)
            fab_nr = infer_fab_nr(merged_for_id, device_id)

            is_active = is_device_active(detail_payload) or is_device_active(
                device_payload
            )
            was_active = self._previous_active.get(device_id)
            ticks = self._ticks_since_history.get(device_id, 0)
            do_refresh = should_refresh_history(
                was_active, is_active, ticks, HISTORY_REFRESH_TICKS
            )

            if do_refresh:
                executions_payload, execution_details = await fetch_device_history(
                    fab_nr,
                    self.max_execution_details,
                    self._safe_get_executions,
                    self._safe_get_execution_detail,
                )
                self._ticks_since_history[device_id] = 0
            else:
                previous_dev = previous_devices.get(device_id, {})
                executions_payload = previous_dev.get("executions", {})
                execution_details = previous_dev.get("execution_details", [])
                self._ticks_since_history[device_id] = ticks + 1

            self._previous_active[device_id] = is_active
            # The device is live again: reset the disappeared-refresh counter.
            self._final_refresh_attempts.pop(device_id, None)
            any_active = any_active or is_active

            latest_execution, latest_execution_detail = _latest_cycle(
                executions_payload, execution_details
            )

            details_for_flat = {
                key: value
                for key, value in (detail_payload or {}).items()
                if key not in _DETAILS_EXCLUDED_FROM_FLAT
            }
            flat_payload = {
                "device": device_payload,
                "details": details_for_flat,
                "current_program": transform.build_current_program_summary(
                    detail_payload, program_running=is_active
                ),
                "latest_cycle": transform.build_latest_cycle_summary(
                    latest_execution, latest_execution_detail
                ),
            }

            # Keep a stable entity schema: paths seen earlier (e.g. running
            # program fields) persist as None once the cycle ends, so their
            # entities stay alive ("unknown") instead of disappearing.
            flat = stable_flat(
                flatten_scalars(flat_payload),
                previous_devices.get(device_id, {}).get("flat", {}),
            )

            devices[device_id] = {
                "id": device_id,
                "fab_nr": fab_nr,
                "name": infer_device_name(
                    detail_payload, device_payload, fallback=device_id
                ),
                "model": infer_model(detail_payload, device_payload),
                "device": device_payload,
                "details": detail_payload,
                "executions": executions_payload,
                "execution_details": execution_details,
                "flat": flat,
            }

        # A device active last tick can simply drop out of /devices when its
        # cycle ends. Capture the finalized status of that last cycle with one
        # last history fetch (retried a few ticks while the cloud finalizes).
        refreshed_previous = await self._refresh_disappeared(
            set(devices), previous_devices
        )

        # Active state is judged only on devices present this tick: a retained
        # (stale) device must never keep us in fast-poll on a frozen payload.
        self.update_interval = timedelta(
            seconds=next_update_interval_seconds(
                any_active, self._fast_interval, self._slow_interval
            )
        )

        # Retain devices that left the listing (last known state) until the TTL
        # expires, instead of letting their entities go unavailable.
        merged = reconcile.reconcile_devices(
            devices, refreshed_previous, now, self._device_ttl_seconds
        )
        self._prune_internal_state(set(merged))

        present = sum(
            1 for entry in merged.values() if entry.get("_persist", {}).get("present")
        )
        LOGGER.debug(
            "Miele MOVE reconcile: %s present, %s retained, %s known total",
            present,
            len(merged) - present,
            len(merged),
        )

        # Persist (throttled) so entities survive a restart while devices are off.
        self._store.async_delay_save(
            lambda: {"devices": merged}, DEVICES_SAVE_DELAY_SECONDS
        )

        return {"raw_devices": devices_payload, "devices": merged}

    async def _refresh_disappeared(
        self, present_ids: set[str], previous_devices: dict[str, Any]
    ) -> dict[str, Any]:
        """Re-fetch history for devices that just left the /devices listing.

        Uses the stored fab_nr (execution endpoints key on it, not the device
        id) so it works even when /devices/{id} no longer answers. Retried a
        few ticks until the Miele cloud finalizes the cycle that just ended.
        """
        gone = reconcile.disappeared_device_ids(present_ids, previous_devices)
        if not gone:
            return previous_devices

        updated = dict(previous_devices)
        for device_id in gone:
            prev = updated.get(device_id, {})
            fab_nr = prev.get("fab_nr")
            already_finalized = transform.is_finalized_program_status(
                prev.get("flat", {}).get("latest_cycle.final_status")
            )
            attempts = self._final_refresh_attempts.get(device_id, 0)
            if not fab_nr or not reconcile.should_final_history_refresh(
                attempts, FINAL_HISTORY_REFRESH_ATTEMPTS, already_finalized
            ):
                continue

            self._final_refresh_attempts[device_id] = attempts + 1
            executions_payload, execution_details = await fetch_device_history(
                fab_nr,
                self.max_execution_details,
                self._safe_get_executions,
                self._safe_get_execution_detail,
            )
            updated[device_id] = _with_refreshed_cycle(
                prev, executions_payload, execution_details
            )
            LOGGER.debug(
                "Miele MOVE device %s left /devices; final history refresh "
                "attempt %s/%s (fab_nr=%s)",
                device_id,
                attempts + 1,
                FINAL_HISTORY_REFRESH_ATTEMPTS,
                fab_nr,
            )
        return updated

    def _prune_internal_state(self, keep: set[str]) -> None:
        """Drop per-device bookkeeping for devices purged past the TTL."""
        for store in (
            self._previous_active,
            self._ticks_since_history,
            self._final_refresh_attempts,
        ):
            for device_id in [key for key in store if key not in keep]:
                store.pop(device_id, None)

    async def _safe_get_device(self, device_id: str) -> dict[str, Any]:
        try:
            payload = await self.client.async_get_device(device_id)
        except MieleMoveAuthError:
            raise
        except MieleMoveApiError:
            return {}
        return payload if isinstance(payload, dict) else {}

    async def _safe_get_executions(self, fab_nr: str) -> Any:
        try:
            return await self.client.async_get_executions(fab_nr)
        except MieleMoveAuthError:
            raise
        except MieleMoveApiError:
            return {}

    async def _safe_get_execution_detail(
        self, fab_nr: str, execution_id: str
    ) -> Any:
        try:
            return await self.client.async_get_execution_detail(fab_nr, execution_id)
        except MieleMoveAuthError:
            raise
        except MieleMoveApiError:
            return None


def _latest_cycle(
    executions_payload: Any, execution_details: list[Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick the most recent finalized (execution, detail) from raw payloads."""
    executions = transform.sort_executions_desc(
        list(iter_executions(executions_payload))
    )
    # execution_details is a compact list (None values are skipped at fetch
    # time), so re-align with executions by executionId rather than relying on
    # positional pairing.
    details_by_id = {
        infer_execution_id(detail): detail
        for detail in execution_details
        if isinstance(detail, dict) and infer_execution_id(detail)
    }
    aligned_details = [
        details_by_id.get(infer_execution_id(execution), {})
        for execution in executions
    ]
    return transform.pick_latest_finalized(executions, aligned_details)


def _with_refreshed_cycle(
    previous_entry: dict[str, Any],
    executions_payload: Any,
    execution_details: list[Any],
) -> dict[str, Any]:
    """Copy a retained device entry with only its last-cycle subtree refreshed.

    Live fields (device status, current program) stay frozen at their last
    known values, since a disappeared device no longer answers /devices/{id}.
    """
    latest_execution, latest_execution_detail = _latest_cycle(
        executions_payload, execution_details
    )
    summary = transform.build_latest_cycle_summary(
        latest_execution, latest_execution_detail
    )
    if not summary:
        # Transient empty history (API hiccup): keep the last known cycle rather
        # than wiping a valid finalized status to unknown.
        return previous_entry

    refreshed = dict(previous_entry)
    refreshed["executions"] = executions_payload
    refreshed["execution_details"] = execution_details
    # Preserve the entity schema across the refresh: latest_cycle.* paths the
    # new summary no longer carries (e.g. a not-yet-finalized duration) stay as
    # None instead of being dropped, so their entities are never orphaned.
    refreshed["flat"] = merge_refreshed_cycle_flat(
        previous_entry.get("flat", {}), summary
    )
    return refreshed


def _merge_dicts(*payloads: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        if isinstance(payload, dict):
            merged.update(payload)
    return merged
