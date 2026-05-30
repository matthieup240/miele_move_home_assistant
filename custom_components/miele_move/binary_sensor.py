"""Binary sensors for Miele MOVE."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import reconcile
from .const import DOMAIN
from .coordinator import MieleMoveDataUpdateCoordinator
from .entity import MieleMoveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Miele MOVE binary sensors (one connectivity sensor per device)."""
    coordinator: MieleMoveDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def add_new_entities() -> None:
        entities: list[BinarySensorEntity] = []
        devices = coordinator.data.get("devices", {}) if coordinator.data else {}

        for device_id in devices:
            if device_id in known:
                continue
            known.add(device_id)
            entities.append(
                MieleMoveConnectivityBinarySensor(coordinator, entry, device_id)
            )

        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class MieleMoveConnectivityBinarySensor(MieleMoveEntity, BinarySensorEntity):
    """Reports whether the appliance is currently reachable by the API.

    On = connected (listed by /devices), Off = disconnected (retained from a
    previous tick, or purged). It never goes unavailable itself while the
    integration is updating, so it can always report "disconnected".
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connectivity"

    def __init__(
        self,
        coordinator: MieleMoveDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_connectivity"

    @property
    def is_on(self) -> bool:
        """Return True when the appliance is currently reachable."""
        return reconcile.is_present(self._device_data)
