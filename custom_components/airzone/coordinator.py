"""The Airzone integration."""

from asyncio import timeout
from datetime import timedelta
import logging
from typing import Any

from aioairzone.const import AZD_MASTER, AZD_SYSTEM, AZD_ZONES
from aioairzone.exceptions import AirzoneError
from aioairzone.localapi import AirzoneLocalApi

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import AIOAIRZONE_DEVICE_TIMEOUT_SEC, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

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
