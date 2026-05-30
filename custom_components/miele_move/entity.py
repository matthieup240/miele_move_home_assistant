"""Shared base entity for Miele MOVE platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MieleMoveDataUpdateCoordinator


class MieleMoveEntity(CoordinatorEntity[MieleMoveDataUpdateCoordinator]):
    """Base class shared by every Miele MOVE platform.

    Availability is intentionally left to CoordinatorEntity (i.e.
    last_update_success): a device that left the /devices listing is retained
    with its last known state rather than going unavailable.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MieleMoveDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entry = entry
        self.device_id = device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        data = self._device_data
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self.device_id)},
            "manufacturer": "Miele",
            "name": data.get("name", f"Miele MOVE {self.device_id}"),
        }
        if data.get("model"):
            info["model"] = data["model"]
        return info

    @property
    def _device_data(self) -> dict[str, Any]:
        return self.coordinator.data.get("devices", {}).get(self.device_id, {})
