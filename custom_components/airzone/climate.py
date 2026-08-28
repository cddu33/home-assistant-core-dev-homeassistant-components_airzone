"""Support for the Airzone climate."""

from collections.abc import Callable, Iterable, Mapping
from functools import cache
from types import MappingProxyType
from typing import Any, Final

from aioairzone.common import OperationAction, OperationMode
from aioairzone.const import (
    API_COOL_SET_POINT,
    API_HEAT_SET_POINT,
    API_MODE,
    API_ON,
    API_SET_POINT,
    API_SPEED,
    API_SYSTEM_ID,
    API_ZONE_ID,
    AZD_ACTION,
    AZD_COOL_TEMP_SET,
    AZD_DOUBLE_SET_POINT,
    AZD_HEAT_TEMP_SET,
    AZD_HUMIDITY,
    AZD_ID,
    AZD_MASTER,
    AZD_MODE,
    AZD_MODES,
    AZD_ON,
    AZD_SPEED,
    AZD_SPEEDS,
    AZD_SYSTEM,
    AZD_SYSTEMS,
    AZD_TEMP,
    AZD_TEMP_MAX,
    AZD_TEMP_MIN,
    AZD_TEMP_SET,
    AZD_TEMP_UNIT,
    AZD_ZONES,
)
from aioairzone.exceptions import AirzoneError

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import API_TEMPERATURE_STEP, TEMP_UNIT_LIB_TO_HASS
from .coordinator import AirzoneConfigEntry, AirzoneUpdateCoordinator
from .entity import AirzoneSystemEntity, AirzoneZoneEntity, zone_needs_write

BASE_FAN_SPEEDS: Final[dict[int, str]] = {
    0: FAN_AUTO,
    1: FAN_LOW,
}
FAN_SPEED_MAPS: Final[dict[int, dict[int, str]]] = {
    2: BASE_FAN_SPEEDS
    | {
        2: FAN_HIGH,
    },
    3: BASE_FAN_SPEEDS
    | {
        2: FAN_MEDIUM,
        3: FAN_HIGH,
    },
}


def _build_speed_map(speeds: Iterable[int]) -> dict[int, str]:
    """Build a fan-speed-to-label map for an arbitrary speed range.

    Returns a fresh dict every time so callers never share mutable state
    across zones with different (or unusual) speed ranges.
    """
    speeds = list(speeds)
    max_speed = max(speeds)

    if mapped := FAN_SPEED_MAPS.get(max_speed):
        return dict(mapped)

    speed_map: dict[int, str] = {}
    for speed in speeds:
        if speed == 0:
            speed_map[speed] = FAN_AUTO
        else:
            speed_map[speed] = f"{int(round((speed * 100) / max_speed, 0))}%"

    speed_map[1] = FAN_LOW
    speed_map[int(round((max_speed + 1) / 2, 0))] = FAN_MEDIUM
    speed_map[max_speed] = FAN_HIGH

    return speed_map


@cache
def _speed_reverse_map(speeds: tuple[int, ...]) -> Mapping[str, int]:
    """Return the label-to-speed map for a speed range, memoized.

    The system-wide fan-out translates the requested mode into each zone's own
    speed value, and zones overwhelmingly share the same range; building the
    map once per distinct range keeps that loop off the hot path. Read-only,
    hence the proxy: callers that keep a mutable copy use _build_speed_map.
    """
    return MappingProxyType({v: k for k, v in _build_speed_map(speeds).items()})


HVAC_ACTION_LIB_TO_HASS: Final[dict[OperationAction, HVACAction]] = {
    OperationAction.COOLING: HVACAction.COOLING,
    OperationAction.DRYING: HVACAction.DRYING,
    OperationAction.FAN: HVACAction.FAN,
    OperationAction.HEATING: HVACAction.HEATING,
    OperationAction.IDLE: HVACAction.IDLE,
    OperationAction.OFF: HVACAction.OFF,
}
HVAC_MODE_LIB_TO_HASS: Final[dict[OperationMode, HVACMode]] = {
    OperationMode.STOP: HVACMode.OFF,
    OperationMode.COOLING: HVACMode.COOL,
    OperationMode.HEATING: HVACMode.HEAT,
    OperationMode.FAN: HVACMode.FAN_ONLY,
    OperationMode.DRY: HVACMode.DRY,
    OperationMode.AUX_HEATING: HVACMode.HEAT,
    OperationMode.AUTO: HVACMode.HEAT_COOL,
}
HVAC_MODE_HASS_TO_LIB: Final[dict[HVACMode, OperationMode]] = {
    HVACMode.OFF: OperationMode.STOP,
    HVACMode.COOL: OperationMode.COOLING,
    HVACMode.HEAT: OperationMode.HEATING,
    HVACMode.FAN_ONLY: OperationMode.FAN,
    HVACMode.DRY: OperationMode.DRY,
    HVACMode.HEAT_COOL: OperationMode.AUTO,
}

# Priority order used to pick a single representative action out of all the
# zones of a system: an active demand always takes priority over idle/off,
# so the global "all zones" entity reflects real activity happening
# anywhere in the system.
ACTION_PRIORITY: Final[list[OperationAction]] = [
    OperationAction.HEATING,
    OperationAction.COOLING,
    OperationAction.DRYING,
    OperationAction.FAN,
    OperationAction.IDLE,
    OperationAction.OFF,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirzoneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add Airzone climate from a config_entry."""
    coordinator = entry.runtime_data

    added_systems: set[str] = set()
    added_zones: set[str] = set()

    def _async_entity_listener() -> None:
        """Handle additions of climate."""

        entities: list[ClimateEntity] = []

        systems_data = coordinator.data.get(AZD_SYSTEMS, {})
        received_systems = set(systems_data)
        new_systems = received_systems - added_systems
        if new_systems:
            entities.extend(
                AirzoneSystemClimate(
                    coordinator,
                    entry,
                    system_id,
                    systems_data.get(system_id),
                )
                for system_id in new_systems
            )
            added_systems.update(new_systems)

        zones_data = coordinator.data.get(AZD_ZONES, {})
        received_zones = set(zones_data)
        new_zones = received_zones - added_zones
        if new_zones:
            entities.extend(
                AirzoneClimate(
                    coordinator,
                    entry,
                    system_zone_id,
                    zones_data.get(system_zone_id),
                )
                for system_zone_id in new_zones
            )
            added_zones.update(new_zones)

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneClimate(AirzoneZoneEntity, ClimateEntity):
    """Define an Airzone sensor."""

    _attr_name = None
    _speeds: dict[int, str]
    _speeds_reverse: dict[str, int]

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        entry: ConfigEntry,
        system_zone_id: str,
        zone_data: dict,
    ) -> None:
        """Initialize Airzone climate entity."""
        super().__init__(coordinator, entry, system_zone_id, zone_data)

        self._attr_unique_id = f"{self._attr_unique_id}_{system_zone_id}"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        self._attr_target_temperature_step = API_TEMPERATURE_STEP
        self._attr_temperature_unit = TEMP_UNIT_LIB_TO_HASS[
            self.get_airzone_value(AZD_TEMP_UNIT)
        ]
        self._is_master = bool(self.get_airzone_value(AZD_MASTER))
        if self._is_master:
            _attr_hvac_modes = [
                HVAC_MODE_LIB_TO_HASS[mode]
                for mode in self.get_airzone_value(AZD_MODES)
            ]
            self._attr_hvac_modes = list(dict.fromkeys(_attr_hvac_modes))
        else:
            self._update_slave_hvac_modes()
        if (
            self.get_airzone_value(AZD_SPEED) is not None
            and self.get_airzone_value(AZD_SPEEDS) is not None
        ):
            self._set_fan_speeds()
        if self.get_airzone_value(AZD_DOUBLE_SET_POINT):
            self._attr_supported_features |= (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            )

        self._async_update_attrs()

    def _update_slave_hvac_modes(self) -> None:
        """Restrict slave-zone modes to OFF and the current system mode.

        Slave zones cannot change the system mode, so only expose OFF plus the
        active mode (so the zone can still be turned on/off).
        """
        modes = [HVACMode.OFF]
        current = HVAC_MODE_LIB_TO_HASS.get(self.get_airzone_value(AZD_MODE))
        if current is not None and current != HVACMode.OFF:
            modes.append(current)
        # hvac_modes is a capability attribute: reassigning an equal list on
        # every refresh makes Home Assistant re-emit the capabilities for
        # nothing. ClimateEntity only annotates _attr_hvac_modes, so the first
        # call (from __init__) has nothing to compare against.
        if modes != getattr(self, "_attr_hvac_modes", None):
            self._attr_hvac_modes = modes

    def _set_fan_speeds(self) -> None:
        self._attr_supported_features |= ClimateEntityFeature.FAN_MODE

        speeds = self.get_airzone_value(AZD_SPEEDS)
        self._speeds = _build_speed_map(speeds)
        self._speeds_reverse = {v: k for k, v in self._speeds.items()}
        self._attr_fan_modes = list(self._speeds_reverse)

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        params = {
            API_ON: 1,
        }
        await self._async_update_hvac_params(params)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        params = {
            API_ON: 0,
        }
        await self._async_update_hvac_params(params)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        params = {
            API_SPEED: self._speeds_reverse.get(fan_mode),
        }
        await self._async_update_hvac_params(params)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        slave_raise = False

        params = {}
        if hvac_mode == HVACMode.OFF:
            params[API_ON] = 0
        else:
            mode = HVAC_MODE_HASS_TO_LIB[hvac_mode]
            if mode != self.get_airzone_value(AZD_MODE):
                if self.get_airzone_value(AZD_MASTER):
                    params[API_MODE] = mode
                else:
                    slave_raise = True
            params[API_ON] = 1
        await self._async_update_hvac_params(params)

        if slave_raise:
            raise HomeAssistantError(
                f"Mode can't be changed on slave zone {self.entity_id}"
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        params = {}
        if ATTR_TEMPERATURE in kwargs:
            params[API_SET_POINT] = kwargs[ATTR_TEMPERATURE]
        if ATTR_TARGET_TEMP_LOW in kwargs and ATTR_TARGET_TEMP_HIGH in kwargs:
            params[API_COOL_SET_POINT] = kwargs[ATTR_TARGET_TEMP_HIGH]
            params[API_HEAT_SET_POINT] = kwargs[ATTR_TARGET_TEMP_LOW]
        if params:
            await self._async_update_hvac_params(params)

        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Update climate attributes."""
        if not self._is_master:
            self._update_slave_hvac_modes()
        self._attr_current_temperature = self.get_airzone_value(AZD_TEMP)
        self._attr_current_humidity = self.get_airzone_value(AZD_HUMIDITY)
        self._attr_hvac_action = HVAC_ACTION_LIB_TO_HASS[
            self.get_airzone_value(AZD_ACTION)
        ]
        if self.get_airzone_value(AZD_ON):
            self._attr_hvac_mode = HVAC_MODE_LIB_TO_HASS[
                self.get_airzone_value(AZD_MODE)
            ]
        else:
            self._attr_hvac_mode = HVACMode.OFF
        self._attr_max_temp = self.get_airzone_value(AZD_TEMP_MAX)
        self._attr_min_temp = self.get_airzone_value(AZD_TEMP_MIN)
        if self.supported_features & ClimateEntityFeature.FAN_MODE:
            self._attr_fan_mode = self._speeds.get(self.get_airzone_value(AZD_SPEED))
        if (
            self.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            and self._attr_hvac_mode == HVACMode.HEAT_COOL
        ):
            self._attr_target_temperature_high = self.get_airzone_value(
                AZD_COOL_TEMP_SET
            )
            self._attr_target_temperature_low = self.get_airzone_value(
                AZD_HEAT_TEMP_SET
            )
            self._attr_target_temperature = None
        else:
            self._attr_target_temperature_high = None
            self._attr_target_temperature_low = None
            self._attr_target_temperature = self.get_airzone_value(AZD_TEMP_SET)


class AirzoneSystemClimate(AirzoneSystemEntity, ClimateEntity):
    """Define a global Airzone climate that controls all zones of a system."""

    _attr_translation_key = "all_zones"
    _speeds: dict[int, str]
    _speeds_reverse: dict[str, int]

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        entry: ConfigEntry,
        system_id: str,
        system_data: dict[str, Any],
    ) -> None:
        """Initialize Airzone global climate entity."""
        super().__init__(coordinator, entry, system_data)

        self._speeds = {}
        self._speeds_reverse = {}

        self._attr_unique_id = f"{self._attr_unique_id}_{system_id}_all_zones"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        self._attr_target_temperature_step = API_TEMPERATURE_STEP
        self._attr_temperature_unit = TEMP_UNIT_LIB_TO_HASS[
            self._master_value(AZD_TEMP_UNIT)
        ]

        modes = self._master_value(AZD_MODES) or []
        hvac_modes = [HVAC_MODE_LIB_TO_HASS[mode] for mode in modes]
        self._attr_hvac_modes = list(dict.fromkeys(hvac_modes)) or [HVACMode.OFF]

        if (
            self._master_value(AZD_SPEED) is not None
            and self._master_value(AZD_SPEEDS) is not None
        ):
            self._set_fan_speeds()
        if self._master_value(AZD_DOUBLE_SET_POINT):
            self._attr_supported_features |= (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            )

        self._async_update_attrs()

    def _master_value(self, key: str) -> Any:
        """Return a value from the master zone."""
        zone = self.master_zone()
        return zone.get(key) if zone else None

    @staticmethod
    def _zones_average(zones: list[dict[str, Any]], key: str) -> float | None:
        """Return the average of a numeric key across the given zones."""
        values = [zone[key] for zone in zones if zone.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    @staticmethod
    def _zones_extreme(
        zones: list[dict[str, Any]], key: str, func: Callable[[list[float]], float]
    ) -> float | None:
        """Return func (min/max) of a numeric key across zones that expose it."""
        values = [zone[key] for zone in zones if zone.get(key) is not None]
        return func(values) if values else None

    @staticmethod
    def _zones_action(zones: list[dict[str, Any]]) -> OperationAction | None:
        """Return the most relevant action across the given zones.

        Any zone actively heating/cooling/drying/running its fan takes
        priority over an idle or off zone, so the global entity reflects
        real system activity instead of only the master zone's own action.
        """
        actions = {
            zone[AZD_ACTION] for zone in zones if zone.get(AZD_ACTION) is not None
        }
        for action in ACTION_PRIORITY:
            if action in actions:
                return action
        return None

    def _set_fan_speeds(self) -> None:
        self._attr_supported_features |= ClimateEntityFeature.FAN_MODE

        speeds = self._master_value(AZD_SPEEDS)
        self._speeds = _build_speed_map(speeds)
        self._speeds_reverse = {v: k for k, v in self._speeds.items()}
        self._attr_fan_modes = list(self._speeds_reverse)

    async def async_turn_on(self) -> None:
        """Turn all zones on."""
        await self._async_fanout_zone_params(self.system_zones(), {API_ON: 1})

    async def async_turn_off(self) -> None:
        """Turn all zones off."""
        await self._async_fanout_zone_params(self.system_zones(), {API_ON: 0})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode on every zone that supports speeds.

        Each zone can expose its own speed range (different model/capability
        than the master zone), so the requested fan mode is translated to
        every zone's own native speed value instead of reusing the master
        zone's raw numeric speed everywhere.
        """
        try:
            for zone in self.system_zones():
                speeds = zone.get(AZD_SPEEDS)
                if speeds is None:
                    continue
                speed = _speed_reverse_map(tuple(speeds)).get(fan_mode)
                if speed is None:
                    # This zone doesn't have a matching speed for the
                    # requested mode (different granularity than the master
                    # zone); leave it at its current speed.
                    continue
                params = {API_SPEED: speed}
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

        self.coordinator.async_push_airzone_data()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode for all zones."""
        zones = self.system_zones()

        if hvac_mode == HVACMode.OFF:
            await self._async_fanout_zone_params(zones, {API_ON: 0})
            return

        mode = HVAC_MODE_HASS_TO_LIB[hvac_mode]
        # The mode is system-wide and can only be set on the master zone, so
        # it goes out first, on its own. The master is then excluded from the
        # turn-on fan-out: it was just written with API_ON, and the zone dicts
        # here are a snapshot that still shows its previous state.
        master = self.master_zone()
        if mode != self._master_value(AZD_MODE) and master is not None:
            await self._async_fanout_zone_params(
                [master], {API_MODE: mode, API_ON: 1}, push=False
            )
            zones = [zone for zone in zones if zone is not master]

        await self._async_fanout_zone_params(zones, {API_ON: 1})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a common target temperature for all zones."""
        params: dict[str, Any] = {}
        if ATTR_TEMPERATURE in kwargs:
            params[API_SET_POINT] = kwargs[ATTR_TEMPERATURE]
        if ATTR_TARGET_TEMP_LOW in kwargs and ATTR_TARGET_TEMP_HIGH in kwargs:
            params[API_COOL_SET_POINT] = kwargs[ATTR_TARGET_TEMP_HIGH]
            params[API_HEAT_SET_POINT] = kwargs[ATTR_TARGET_TEMP_LOW]

        set_mode = ATTR_HVAC_MODE in kwargs
        if params:
            # When a mode change follows, let it publish the state once at the
            # end instead of pushing twice for a single service call.
            await self._async_fanout_zone_params(
                self.system_zones(), params, push=not set_mode
            )

        if set_mode:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Update global climate attributes.

        Current temperature/humidity, action and target temperature(s) are
        combined across every zone of the system (not just mirrored from
        the master zone), so this entity reflects the system as a whole.
        Only the HVAC mode (a genuinely system-wide setting in Airzone,
        shared by all zones) and the fan mode (no meaningful "average"
        across zones with different, possibly incompatible speed ranges —
        see async_set_fan_mode) are still derived from the master zone.
        """
        zones = self.system_zones()
        master = self.master_zone()
        features = self.supported_features

        self._attr_current_temperature = self._zones_average(zones, AZD_TEMP)
        humidity = self._zones_average(zones, AZD_HUMIDITY)
        self._attr_current_humidity = (
            int(round(humidity)) if humidity is not None else None
        )

        action = self._zones_action(zones)
        self._attr_hvac_action = (
            HVAC_ACTION_LIB_TO_HASS.get(action) if action is not None else None
        )

        if any(zone.get(AZD_ON) for zone in zones):
            self._attr_hvac_mode = HVAC_MODE_LIB_TO_HASS.get(
                master.get(AZD_MODE) if master else None
            )
        else:
            self._attr_hvac_mode = HVACMode.OFF

        # Most restrictive range across zones, so a temperature accepted by
        # this entity is always valid for every zone it fans out to.
        self._attr_max_temp = self._zones_extreme(zones, AZD_TEMP_MAX, min)
        self._attr_min_temp = self._zones_extreme(zones, AZD_TEMP_MIN, max)

        if features & ClimateEntityFeature.FAN_MODE:
            self._attr_fan_mode = self._speeds.get(
                master.get(AZD_SPEED) if master else None
            )

        if (
            features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            and self._attr_hvac_mode == HVACMode.HEAT_COOL
        ):
            self._attr_target_temperature_high = self._zones_average(
                zones, AZD_COOL_TEMP_SET
            )
            self._attr_target_temperature_low = self._zones_average(
                zones, AZD_HEAT_TEMP_SET
            )
            self._attr_target_temperature = None
        else:
            self._attr_target_temperature_high = None
            self._attr_target_temperature_low = None
            self._attr_target_temperature = self._zones_average(zones, AZD_TEMP_SET)
