"""Entity classes for the Airzone integration."""

import logging
from typing import Any, Final

from aioairzone.const import (
    API_COOL_SET_POINT,
    API_HEAT_SET_POINT,
    API_MODE,
    API_ON,
    API_SET_POINT,
    API_SPEED,
    API_SYSTEM_ID,
    API_ZONE_ID,
    AZD_AVAILABLE,
    AZD_COOL_TEMP_SET,
    AZD_FIRMWARE,
    AZD_FULL_NAME,
    AZD_HEAT_TEMP_SET,
    AZD_HOT_WATER,
    AZD_ID,
    AZD_MAC,
    AZD_MODE,
    AZD_MODEL,
    AZD_NAME,
    AZD_ON,
    AZD_SPEED,
    AZD_SYSTEM,
    AZD_SYSTEMS,
    AZD_TEMP_SET,
    AZD_THERMOSTAT_FW,
    AZD_THERMOSTAT_MODEL,
    AZD_WEBSERVER,
    AZD_ZONES,
)
from aioairzone.exceptions import AirzoneError

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AirzoneConfigEntry, AirzoneUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Write parameter -> the state key holding the value it would set. Used to
# detect a fan-out write that wouldn't change anything. Only idempotent
# settings belong here; a parameter absent from this map is always written.
#
# API_SLEEP is deliberately absent: it arms a countdown, so re-selecting the
# value already in effect is a request to restart the timer, not a no-op.
API_TO_AZD_STATE: Final[dict[str, str]] = {
    API_COOL_SET_POINT: AZD_COOL_TEMP_SET,
    API_HEAT_SET_POINT: AZD_HEAT_TEMP_SET,
    API_MODE: AZD_MODE,
    API_ON: AZD_ON,
    API_SET_POINT: AZD_TEMP_SET,
    API_SPEED: AZD_SPEED,
}


def zone_needs_write(zone: dict[str, Any], params: dict[str, Any]) -> bool:
    """Return whether a zone actually needs the given parameters written.

    Airzone webservers serialize every HTTP request (aioairzone caps itself at
    one in-flight request), so a fan-out over N zones costs N round-trips in
    sequence. Skipping zones already in the requested state is what keeps a
    system-wide command fast.

    Errs towards writing: an unmapped parameter, or a state key the zone
    doesn't expose, always counts as needing a write. Comparison is exact --
    a redundant write is harmless, a wrongly skipped one is not.

    The known state can lag reality if a zone was changed outside Home
    Assistant (wall thermostat, Airzone app); the window is bounded by the
    refresh interval.
    """
    for key, value in params.items():
        state_key = API_TO_AZD_STATE.get(key)
        if state_key is None or state_key not in zone:
            return True
        if zone[state_key] != value:
            return True
    return False


class AirzoneEntity(CoordinatorEntity[AirzoneUpdateCoordinator]):
    """Define an Airzone entity."""

    _attr_has_entity_name = True

    def get_airzone_value(self, key: str) -> Any:
        """Return Airzone entity value by key."""
        raise NotImplementedError


class AirzoneSystemEntity(AirzoneEntity):
    """Define an Airzone System entity."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        entry: AirzoneConfigEntry,
        system_data: dict[str, Any],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        self.system_id = system_data[AZD_ID]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{self.system_id}")},
            manufacturer=MANUFACTURER,
            model=self.get_airzone_value(AZD_MODEL),
            name=f"System {self.system_id}",
            sw_version=self.get_airzone_value(AZD_FIRMWARE),
        )
        if AZD_WEBSERVER in self.coordinator.data:
            self._attr_device_info["via_device"] = (DOMAIN, f"{entry.entry_id}_ws")
        self._attr_unique_id = entry.unique_id or entry.entry_id

    @property
    def available(self) -> bool:
        """Return system availability."""
        return super().available and self.get_airzone_value(AZD_AVAILABLE)

    def get_airzone_value(self, key: str) -> Any:
        """Return system value by key."""
        value = None
        if system := self.coordinator.data[AZD_SYSTEMS].get(self.system_id):
            if key in system:
                value = system[key]
        return value

    def system_zones(self) -> list[dict[str, Any]]:
        """Return the data of every zone belonging to this system."""
        return self.coordinator.system_zones.get(self.system_id, [])

    def master_zone(self) -> dict[str, Any] | None:
        """Return the master zone of the system (fallback: first zone)."""
        return self.coordinator.system_masters.get(self.system_id)

    async def _async_update_sys_params(self, params: dict[str, Any]) -> None:
        """Send system parameters to API."""
        _params = {
            API_SYSTEM_ID: self.system_id,
            **params,
        }
        _LOGGER.debug("update_sys_params=%s", _params)
        try:
            await self.coordinator.airzone.set_sys_parameters(_params)
        except AirzoneError as error:
            raise HomeAssistantError(
                f"Failed to set system {self.entity_id}: {error}"
            ) from error

        self.coordinator.async_push_airzone_data()

    async def _async_fanout_zone_params(
        self,
        zones: list[dict[str, Any]],
        params: dict[str, Any],
        *,
        push: bool = True,
    ) -> None:
        """Send the same HVAC parameters to each given zone (fan-out).

        Zones already in the requested state are skipped, see
        `zone_needs_write`. Set `push=False` when the caller chains several
        fan-outs for one service call, so the state is published once at the
        end instead of after each batch.
        """
        try:
            for zone in zones:
                if not zone_needs_write(zone, params):
                    continue
                await self.coordinator.airzone.set_hvac_parameters(
                    {
                        API_SYSTEM_ID: zone[AZD_SYSTEM],
                        API_ZONE_ID: zone[AZD_ID],
                        **params,
                    }
                )
        except AirzoneError as error:
            raise HomeAssistantError(
                f"Failed to set system {self.entity_id}: {error}"
            ) from error

        if push:
            self.coordinator.async_push_airzone_data()


class AirzoneHotWaterEntity(AirzoneEntity):
    """Define an Airzone Hot Water entity."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_dhw")},
            manufacturer=MANUFACTURER,
            model="DHW",
            name=self.get_airzone_value(AZD_NAME),
        )
        if AZD_WEBSERVER in self.coordinator.data:
            self._attr_device_info["via_device"] = (DOMAIN, f"{entry.entry_id}_ws")
        self._attr_unique_id = entry.unique_id or entry.entry_id

    def get_airzone_value(self, key: str) -> Any:
        """Return DHW value by key."""
        return self.coordinator.data[AZD_HOT_WATER].get(key)

    async def _async_update_dhw_params(self, params: dict[str, Any]) -> None:
        """Send DHW parameters to API."""
        _params = {
            API_SYSTEM_ID: 0,
            **params,
        }
        _LOGGER.debug("update_dhw_params=%s", _params)
        try:
            await self.coordinator.airzone.set_dhw_parameters(_params)
        except AirzoneError as error:
            raise HomeAssistantError(f"Failed to set DHW: {error}") from error

        self.coordinator.async_push_airzone_data()


class AirzoneWebServerEntity(AirzoneEntity):
    """Define an Airzone WebServer entity."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        mac = self.get_airzone_value(AZD_MAC)

        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_NETWORK_MAC, mac)},
            identifiers={(DOMAIN, f"{entry.entry_id}_ws")},
            manufacturer=MANUFACTURER,
            model=self.get_airzone_value(AZD_MODEL),
            name=self.get_airzone_value(AZD_FULL_NAME),
            sw_version=self.get_airzone_value(AZD_FIRMWARE),
        )
        self._attr_unique_id = entry.unique_id or entry.entry_id

    def get_airzone_value(self, key: str) -> Any:
        """Return system value by key."""
        return self.coordinator.data[AZD_WEBSERVER].get(key)


class AirzoneZoneEntity(AirzoneEntity):
    """Define an Airzone Zone entity."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        entry: ConfigEntry,
        system_zone_id: str,
        zone_data: dict[str, Any],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        self.system_id = zone_data[AZD_SYSTEM]
        self.system_zone_id = system_zone_id
        self.zone_id = zone_data[AZD_ID]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{system_zone_id}")},
            manufacturer=MANUFACTURER,
            model=self.get_airzone_value(AZD_THERMOSTAT_MODEL),
            name=zone_data[AZD_NAME],
            sw_version=self.get_airzone_value(AZD_THERMOSTAT_FW),
            via_device=(DOMAIN, f"{entry.entry_id}_{self.system_id}"),
        )
        self._attr_unique_id = entry.unique_id or entry.entry_id

    @property
    def available(self) -> bool:
        """Return zone availability."""
        return super().available and self.get_airzone_value(AZD_AVAILABLE)

    def get_airzone_value(self, key: str) -> Any:
        """Return zone value by key."""
        value = None
        if zone := self.coordinator.data[AZD_ZONES].get(self.system_zone_id):
            if key in zone:
                value = zone[key]
        return value

    async def _async_update_hvac_params(self, params: dict[str, Any]) -> None:
        """Send HVAC parameters to API."""
        _params = {
            API_SYSTEM_ID: self.system_id,
            API_ZONE_ID: self.zone_id,
            **params,
        }
        _LOGGER.debug("update_hvac_params=%s", _params)
        try:
            await self.coordinator.airzone.set_hvac_parameters(_params)
        except AirzoneError as error:
            raise HomeAssistantError(
                f"Failed to set zone {self.entity_id}: {error}"
            ) from error

        self.coordinator.async_push_airzone_data()
