"""Sensors for Miele MOVE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import transform
from .const import DOMAIN
from .coordinator import MieleMoveDataUpdateCoordinator
from .entity import MieleMoveEntity

# Dates and durations are exposed as readable formatted strings rather than
# typed numeric values: dates ("22 mai 2026 a 10:00") avoid Home Assistant's
# relative rendering ("last week"), and durations switch from minutes to hours
# past 60 min ("1 h 30 min"). Neither carries a device class.
_DEVICE_CLASSES = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "weight": SensorDeviceClass.WEIGHT,
    "humidity": SensorDeviceClass.HUMIDITY,
}
_STATE_CLASSES = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total": SensorStateClass.TOTAL,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Miele MOVE sensors."""
    coordinator: MieleMoveDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    @callback
    def add_new_entities() -> None:
        entities: list[SensorEntity] = []
        devices = coordinator.data.get("devices", {}) if coordinator.data else {}

        for device_id, device_data in devices.items():
            raw_key = (device_id, "__raw__")
            if raw_key not in known:
                known.add(raw_key)
                entities.append(MieleMoveRawSensor(coordinator, entry, device_id))

            for path in sorted(device_data.get("flat", {})):
                key = (device_id, path)
                if key in known:
                    continue
                known.add(key)
                entities.append(
                    MieleMoveScalarSensor(coordinator, entry, device_id, path)
                )

        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class MieleMoveBaseSensor(MieleMoveEntity, SensorEntity):
    """Base class for Miele MOVE sensors."""


class MieleMoveScalarSensor(MieleMoveBaseSensor):
    """One scalar value from a flattened Miele MOVE payload."""

    def __init__(
        self,
        coordinator: MieleMoveDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: str,
        path: str,
    ) -> None:
        """Initialize a scalar sensor."""
        super().__init__(coordinator, entry, device_id)
        self.path = path
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_{path}"
        self._attr_name = transform.friendly_name(path)

        if transform.is_diagnostic(path):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if transform.disabled_by_default(path):
            self._attr_entity_registry_enabled_default = False

        self._attr_native_unit_of_measurement = transform.unit_for_path(path)
        self._attr_device_class = _DEVICE_CLASSES.get(
            transform.device_class_for_path(path)
        )
        self._attr_state_class = _STATE_CLASSES.get(
            transform.state_class_for_path(path)
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        data = self._device_data
        value = data.get("flat", {}).get(self.path)
        if isinstance(value, (dict, list)):
            return None
        if data.get("_persist", {}).get("stale"):
            value = transform.stale_field_value(self.path, value)
        return transform.native_value_for_path(self.path, value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return metadata useful for debugging."""
        return {
            "miele_move_path": self.path,
            "fab_nr": self._device_data.get("fab_nr"),
        }


class MieleMoveRawSensor(MieleMoveBaseSensor):
    """Diagnostic sensor exposing full raw payloads as attributes."""

    def __init__(
        self,
        coordinator: MieleMoveDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the raw sensor."""
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_raw"
        self._attr_name = "Raw data"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | None:
        """Return a compact presence state ("present" / "stale")."""
        data = self._device_data
        if not data:
            return None
        return "stale" if data.get("_persist", {}).get("stale") else "present"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all fetched API payloads."""
        data = self._device_data
        return {
            "fab_nr": data.get("fab_nr"),
            "persist": data.get("_persist"),
            "device": data.get("device"),
            "details": data.get("details"),
            "executions": data.get("executions"),
            "execution_details": data.get("execution_details"),
        }
