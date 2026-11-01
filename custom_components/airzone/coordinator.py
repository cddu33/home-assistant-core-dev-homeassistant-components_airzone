"""The Airzone integration."""

from asyncio import timeout
from datetime import timedelta
import inspect
import logging
from typing import Any

from aioairzone.const import (
    AZD_FIRMWARE,
    AZD_MASTER,
    AZD_MODEL,
    AZD_SYSTEM,
    AZD_SYSTEMS,
    AZD_WEBSERVER,
    AZD_ZONES,
)
from aioairzone.exceptions import AirzoneError
from aioairzone.localapi import AirzoneLocalApi

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AIOAIRZONE_DEVICE_TIMEOUT_SEC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
)

_LOGGER = logging.getLogger(__name__)

# Recent Home Assistant releases link a device to its parent by device registry
# id (`via_device_id`); the identifier tuple form (`via_device`) is deprecated
# and stops working in 2027.8. Older releases only know `via_device`, so the
# parent link is built in whichever form the running core supports.
VIA_DEVICE_ID_SUPPORTED: bool = (
    "via_device_id"
    in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)

type AirzoneConfigEntry = ConfigEntry[AirzoneUpdateCoordinator]


class AirzoneUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from the Airzone device."""

    config_entry: AirzoneConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AirzoneConfigEntry,
        airzone: AirzoneLocalApi,
    ) -> None:
        """Initialize."""
        self.airzone = airzone

        # Indexes rebuilt once per data change, so system-wide entities don't
        # have to rescan every zone of every system on each attribute read.
        self.system_zones: dict[int, list[dict[str, Any]]] = {}
        self.system_masters: dict[int, dict[str, Any]] = {}

        # Device registry id of the webserver device, set by async_setup_entry
        # once that device is registered, before any entity is created.
        self.webserver_device_id: str | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def _index_zones(self, data: dict[str, Any]) -> None:
        """Index zones by system in a single pass.

        The master zone falls back to the first zone of the system, matching
        what the system-wide entities used to compute on their own.
        """
        system_zones: dict[int, list[dict[str, Any]]] = {}
        system_masters: dict[int, dict[str, Any]] = {}

        for zone in data.get(AZD_ZONES, {}).values():
            system_id = zone.get(AZD_SYSTEM)
            if system_id is None:
                continue
            system_zones.setdefault(system_id, []).append(zone)
            # First master wins; a non-master is only kept as a fallback until
            # a real master shows up.
            current = system_masters.get(system_id)
            if current is None or (
                not current.get(AZD_MASTER) and zone.get(AZD_MASTER)
            ):
                system_masters[system_id] = zone

        self.system_zones = system_zones
        self.system_masters = system_masters

    def _via_device(self, suffix: str, device_id: str | None) -> dict[str, Any]:
        """Return the device info fields linking a device to its parent.

        `suffix` is the parent's identifier suffix (used by cores without
        `via_device_id`), `device_id` its device registry id.
        """
        if not VIA_DEVICE_ID_SUPPORTED:
            return {"via_device": (DOMAIN, f"{self.config_entry.entry_id}_{suffix}")}
        if device_id is None:
            return {}
        return {"via_device_id": device_id}

    def via_webserver_device(self) -> dict[str, Any]:
        """Return the device info fields linking a device to the webserver."""
        if AZD_WEBSERVER not in self.data:
            return {}
        return self._via_device("ws", self.webserver_device_id)

    def system_device_info(self, system_id: int) -> dict[str, Any]:
        """Return the device info of a system, as keyword arguments."""
        system = self.data.get(AZD_SYSTEMS, {}).get(system_id) or {}
        return {
            "identifiers": {(DOMAIN, f"{self.config_entry.entry_id}_{system_id}")},
            "manufacturer": MANUFACTURER,
            "model": system.get(AZD_MODEL),
            "name": f"System {system_id}",
            "sw_version": system.get(AZD_FIRMWARE),
            **self.via_webserver_device(),
        }

    @callback
    def async_via_system_device(self, system_id: int) -> dict[str, Any]:
        """Return the device info fields linking a device to its system.

        The system device is registered here if needed: zone and system
        entities live on different platforms set up concurrently, and new
        systems can show up at runtime, so the parent can't be assumed to
        exist yet when a zone entity is created.
        """
        if not VIA_DEVICE_ID_SUPPORTED:
            return self._via_device(str(system_id), None)
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            **self.system_device_info(system_id),
        )
        return self._via_device(str(system_id), device.id)

    @callback
    def async_push_airzone_data(self) -> None:
        """Push the library's current state to every entity.

        Used after a write: aioairzone updates its local cache as part of a
        successful command, so the new state can be published without waiting
        for the next poll. The indexes are rebuilt before notifying, since
        listeners read them while handling the update.
        """
        data = self.airzone.data()
        self._index_zones(data)
        self.async_set_updated_data(data)

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        async with timeout(AIOAIRZONE_DEVICE_TIMEOUT_SEC):
            try:
                await self.airzone.update()
            except AirzoneError as error:
                raise UpdateFailed(error) from error
            data = self.airzone.data()
            self._index_zones(data)
            return data
