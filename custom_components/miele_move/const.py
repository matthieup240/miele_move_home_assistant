"""Constants for the Miele MOVE integration."""

from __future__ import annotations

DOMAIN = "miele_move"

CONF_ACCEPT_LANGUAGE = "accept_language"
CONF_BASE_URL = "base_url"
CONF_MAX_EXECUTION_DETAILS = "max_execution_details"
CONF_SCAN_INTERVAL_SECONDS = "scan_interval_seconds"
CONF_FAST_INTERVAL_SECONDS = "fast_interval_seconds"
CONF_SLOW_INTERVAL_SECONDS = "slow_interval_seconds"
CONF_DEVICE_TTL_SECONDS = "device_ttl_seconds"

DEFAULT_ACCEPT_LANGUAGE = "fr-FR"
DEFAULT_BASE_URL = "https://www.miele-move.com"
DEFAULT_MAX_EXECUTION_DETAILS = 5
DEFAULT_SCAN_INTERVAL_SECONDS = 60
DEFAULT_FAST_INTERVAL_SECONDS = 5
DEFAULT_SLOW_INTERVAL_SECONDS = 120
MIN_FAST_INTERVAL_SECONDS = 3
MAX_FAST_INTERVAL_SECONDS = 60
MIN_SLOW_INTERVAL_SECONDS = 30
MAX_SLOW_INTERVAL_SECONDS = 3600

# How long a device that left the /devices listing is kept with its last known
# state before being purged. The Miele MOVE API drops appliances from the list
# once a cycle ends, so we retain them (default 24 h) instead of going
# unavailable, until they reappear at the next cycle.
DEFAULT_DEVICE_TTL_SECONDS = 86400
MIN_DEVICE_TTL_SECONDS = 3600
MAX_DEVICE_TTL_SECONDS = 604800

# How many ticks between forced full history refreshes when nothing changes.
HISTORY_REFRESH_TICKS = 120

# How many times we re-fetch a disappeared device's history while waiting for
# the Miele cloud to finalize the last cycle's status.
FINAL_HISTORY_REFRESH_ATTEMPTS = 3

# Hard ceiling on a full refresh (devices + details + executions per device).
UPDATE_TIMEOUT_SECONDS = 60

# Persistence of the device map so entities survive a Home Assistant restart
# while an appliance is off (and thus absent from /devices).
STORAGE_VERSION = 1
DEVICES_SAVE_DELAY_SECONDS = 30

PLATFORMS = ["binary_sensor", "sensor"]
