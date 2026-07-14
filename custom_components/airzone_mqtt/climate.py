"""Support for the Airzone MQTT climate."""

from typing import Any, Final
import logging

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
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
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import API_TEMPERATURE_STEP, TEMP_UNIT_MAP
from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneSystemEntity, AirzoneZoneEntity

_LOGGER = logging.getLogger(__name__)

# --- Clés JSON MQTT Airzone (parameters aplatis par le coordinator) ---
AZ_TEMP = "zone_work_temp"
AZ_HUMIDITY = "humidity"
AZ_POWER = "power"
AZ_MODE = "mode"
AZ_MODES = "mode_available"
AZ_SETPOINT = "setpoint"
AZ_AIR_ACTIVE = "air_active"
AZ_RAD_ACTIVE = "rad_active"
AZ_SPEED = "speed_conf"
AZ_SPEEDS = "speed_values"
AZ_MASTER = "master"  # champ virtuel calculé par le coordinator
AZ_TEMP_UNIT = "units"
AZ_MAX_TEMP = "max_temp"  # dérivé de range_sp.max par le coordinator
AZ_MIN_TEMP = "min_temp"  # dérivé de range_sp.min par le coordinator

# --- Enum AirzoneMode (entiers renvoyés par MQTT) ---
MODE_STOP: Final = 0
MODE_AUTO: Final = 1
MODE_COOLING: Final = 2
MODE_HEATING: Final = 3
MODE_VENTILATION: Final = 4
MODE_DRY: Final = 5

COOL_MODES: Final = {MODE_COOLING, 10, 11, 12}  # cooling + cool air/radiant/combined
HEAT_MODES: Final = {MODE_HEATING, 6, 7, 8, 9}  # heating + emergency + heat variants

# Mapping mode (int) -> HVACMode
HVAC_MODE_MAP: Final[dict[int, HVACMode]] = {
    MODE_STOP: HVACMode.OFF,
    MODE_AUTO: HVACMode.HEAT_COOL,
    MODE_COOLING: HVACMode.COOL,
    MODE_HEATING: HVACMode.HEAT,
    MODE_VENTILATION: HVACMode.FAN_ONLY,
    MODE_DRY: HVACMode.DRY,
    6: HVACMode.HEAT,
    7: HVACMode.HEAT,
    8: HVACMode.HEAT,
    9: HVACMode.HEAT,
    10: HVACMode.COOL,
    11: HVACMode.COOL,
    12: HVACMode.COOL,
}

# Mapping HVACMode -> mode (int) pour l'envoi de commandes
HVAC_MODE_REVERSE: Final[dict[HVACMode, int]] = {
    HVACMode.OFF: MODE_STOP,
    HVACMode.HEAT_COOL: MODE_AUTO,
    HVACMode.COOL: MODE_COOLING,
    HVACMode.HEAT: MODE_HEATING,
    HVACMode.FAN_ONLY: MODE_VENTILATION,
    HVACMode.DRY: MODE_DRY,
}

BASE_FAN_SPEEDS: Final[dict[int, str]] = {0: FAN_AUTO, 1: FAN_LOW}
FAN_SPEED_MAPS: Final[dict[int, dict[int, str]]] = {
    2: BASE_FAN_SPEEDS | {2: FAN_HIGH},
    3: BASE_FAN_SPEEDS | {2: FAN_MEDIUM, 3: FAN_HIGH},
}


def _mode_to_hvac(mode: Any) -> HVACMode | None:
    """Convertit un mode Airzone (int) en HVACMode."""
    if mode is None:
        return None
    try:
        return HVAC_MODE_MAP.get(int(mode))
    except (TypeError, ValueError):
        return None


def _hvac_action(power: Any, mode: Any, air: Any, rad: Any) -> HVACAction:
    """Déduit l'action HVAC à partir de power + air_active/rad_active + mode."""
    if not power:
        return HVACAction.OFF
    if not (air or rad):
        return HVACAction.IDLE
    try:
        mode_int = int(mode) if mode is not None else None
    except (TypeError, ValueError):
        mode_int = None
    if mode_int in COOL_MODES:
        return HVACAction.COOLING
    if mode_int == MODE_VENTILATION:
        return HVACAction.FAN
    if mode_int == MODE_DRY:
        return HVACAction.DRYING
    return HVACAction.HEATING


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Ajoute les entités Climate Airzone depuis la configuration MQTT."""
    coordinator: AirzoneMqttCoordinator = entry.runtime_data

    added_systems: set[str] = set()
    added_zones: set[str] = set()

    def _async_entity_listener() -> None:
        """Ajout dynamique des systèmes et zones à la réception des données."""
        entities: list[ClimateEntity] = []

        systems_data = coordinator.data.get("systems", {})
        new_systems = set(systems_data) - added_systems
        if new_systems:
            entities.extend(
                AirzoneSystemClimate(coordinator, entry, sys_id, systems_data[sys_id])
                for sys_id in new_systems
            )
            added_systems.update(new_systems)

        zones_data = coordinator.data.get("zones", {})
        new_zones = set(zones_data) - added_zones
        if new_zones:
            entities.extend(
                AirzoneClimate(coordinator, entry, sys_zone_id, zones_data[sys_zone_id])
                for sys_zone_id in new_zones
            )
            added_zones.update(new_zones)

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneClimate(AirzoneZoneEntity, ClimateEntity):
    """Représentation d'une Zone de climatisation Airzone."""

    _attr_name = None
    _speeds: dict[int, str] = {}
    _speeds_reverse: dict[str, int] = {}

    def __init__(
        self,
        coordinator: AirzoneMqttCoordinator,
        entry: ConfigEntry,
        system_zone_id: str,
        zone_data: dict[str, Any],
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator, entry, system_zone_id, zone_data)

        self._attr_unique_id = f"{self._attr_unique_id}_{system_zone_id}"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        self._attr_target_temperature_step = API_TEMPERATURE_STEP

        unit_val = self.get_airzone_value(AZ_TEMP_UNIT)
        self._attr_temperature_unit = TEMP_UNIT_MAP.get(
            unit_val, UnitOfTemperature.CELSIUS
        )

        self._is_master = bool(self.get_airzone_value(AZ_MASTER))
        self._update_hvac_modes()

        # Ventilation (si un jour le protocole l'expose).
        if self.get_airzone_value(AZ_SPEED) is not None and self.get_airzone_value(
            AZ_SPEEDS
        ):
            self._set_fan_speeds()

        self._async_update_attrs()

    def _update_hvac_modes(self) -> None:
        """Modes disponibles à partir de mode_available (liste d'entiers)."""
        modes = {HVACMode.OFF}
        if self._is_master:
            for mode in self.get_airzone_value(AZ_MODES) or []:
                if (hvac := _mode_to_hvac(mode)) is not None:
                    modes.add(hvac)
        else:
            # Zone esclave : ne peut que suivre le mode courant ou s'éteindre.
            current = _mode_to_hvac(self.get_airzone_value(AZ_MODE))
            if current is not None and current != HVACMode.OFF:
                modes.add(current)
        self._attr_hvac_modes = list(modes)

    def _set_fan_speeds(self) -> None:
        """Configure les vitesses de ventilation disponibles."""
        self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        speeds = self.get_airzone_value(AZ_SPEEDS)
        if not speeds:
            return

        max_speed = max(speeds)
        if _speeds := FAN_SPEED_MAPS.get(max_speed):
            self._speeds = _speeds
        else:
            for speed in speeds:
                if speed == 0:
                    self._speeds[speed] = FAN_AUTO
                else:
                    self._speeds[speed] = f"{int(round((speed * 100) / max_speed, 0))}%"
            self._speeds[1] = FAN_LOW
            self._speeds[int(round((max_speed + 1) / 2, 0))] = FAN_MEDIUM
            self._speeds[max_speed] = FAN_HIGH

        self._speeds_reverse = {v: k for k, v in self._speeds.items()}
        self._attr_fan_modes = list(self._speeds_reverse)

    async def async_turn_on(self) -> None:
        """Allume la zone."""
        await self._async_update_hvac_params({AZ_POWER: 1})

    async def async_turn_off(self) -> None:
        """Éteint la zone."""
        await self._async_update_hvac_params({AZ_POWER: 0})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Modifie la vitesse de ventilation."""
        if (speed_conf := self._speeds_reverse.get(fan_mode)) is not None:
            await self._async_update_hvac_params({AZ_SPEED: speed_conf})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change le mode HVAC."""
        slave_raise = False
        params: dict[str, Any] = {}

        if hvac_mode == HVACMode.OFF:
            params[AZ_POWER] = 0
        else:
            mode_int = HVAC_MODE_REVERSE.get(hvac_mode, MODE_STOP)
            if mode_int != self.get_airzone_value(AZ_MODE):
                if self._is_master:
                    params[AZ_MODE] = mode_int
                else:
                    slave_raise = True
            params[AZ_POWER] = 1

        await self._async_update_hvac_params(params)

        if slave_raise:
            raise HomeAssistantError(
                f"Le mode ne peut pas être modifié sur la zone esclave {self.entity_id}"
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Modifie la consigne de température."""
        if ATTR_TEMPERATURE in kwargs:
            await self._async_update_hvac_params(
                {AZ_SETPOINT: kwargs[ATTR_TEMPERATURE]}
            )

        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Met à jour l'interface avec les données MQTT reçues."""
        self._is_master = bool(self.get_airzone_value(AZ_MASTER))
        self._update_hvac_modes()

        self._attr_current_temperature = self.get_airzone_value(AZ_TEMP)
        self._attr_current_humidity = self.get_airzone_value(AZ_HUMIDITY)

        power = self.get_airzone_value(AZ_POWER)
        self._attr_hvac_action = _hvac_action(
            power,
            self.get_airzone_value(AZ_MODE),
            self.get_airzone_value(AZ_AIR_ACTIVE),
            self.get_airzone_value(AZ_RAD_ACTIVE),
        )

        if power:
            self._attr_hvac_mode = (
                _mode_to_hvac(self.get_airzone_value(AZ_MODE)) or HVACMode.OFF
            )
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self._attr_max_temp = self.get_airzone_value(AZ_MAX_TEMP) or 30.0
        self._attr_min_temp = self.get_airzone_value(AZ_MIN_TEMP) or 15.0

        if self.supported_features & ClimateEntityFeature.FAN_MODE:
            self._attr_fan_mode = self._speeds.get(self.get_airzone_value(AZ_SPEED))

        self._attr_target_temperature = self.get_airzone_value(AZ_SETPOINT)


class AirzoneSystemClimate(AirzoneSystemEntity, ClimateEntity):
    """Contrôle global d'un système Airzone (Toutes les zones)."""

    _attr_translation_key = "all_zones"

    def __init__(
        self,
        coordinator: AirzoneMqttCoordinator,
        entry: ConfigEntry,
        system_id: str,
        system_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry, system_data)

        self._attr_unique_id = f"{self._attr_unique_id}_{system_id}_all_zones"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        self._attr_target_temperature_step = API_TEMPERATURE_STEP

        unit_val = self._master_value(AZ_TEMP_UNIT)
        self._attr_temperature_unit = TEMP_UNIT_MAP.get(
            unit_val, UnitOfTemperature.CELSIUS
        )

        modes = {HVACMode.OFF}
        for mode in self._master_value(AZ_MODES) or []:
            if (hvac := _mode_to_hvac(mode)) is not None:
                modes.add(hvac)
        self._attr_hvac_modes = list(modes)

        self._async_update_attrs()

    def _system_zones(self) -> list[dict[str, Any]]:
        """Retourne toutes les zones appartenant à ce système."""
        zones = self.coordinator.data.get("zones", {})
        return [z for z in zones.values() if z.get("system_id") == self.system_id]

    def _master_zone(self) -> dict[str, Any] | None:
        """Trouve la zone maître (virtuelle) du système."""
        zones = self._system_zones()
        for zone in zones:
            if zone.get(AZ_MASTER):
                return zone
        return zones[0] if zones else None

    def _master_value(self, key: str) -> Any:
        """Récupère une valeur depuis la zone maître."""
        zone = self._master_zone()
        return zone.get(key) if zone else None

    def _zones_average(self, key: str) -> float | None:
        """Moyenne d'une valeur (ex : température) sur toutes les zones."""
        values = [z[key] for z in self._system_zones() if z.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    async def _async_set_zones_params(
        self, zones: list[dict[str, Any]], params: dict[str, Any]
    ) -> None:
        """Envoie les mêmes paramètres à toutes les zones (fan-out via RPC MQTT)."""
        try:
            for zone in zones:
                await self.coordinator.async_send_rpc(
                    "AzZoneSetStatus",
                    {
                        "system_id": zone.get("system_id"),
                        "zone_id": zone.get("zone_id"),
                        "device_set_status": params,
                    },
                )
        except Exception as error:
            raise HomeAssistantError(
                f"Échec de mise à jour du système {self.entity_id}: {error}"
            ) from error

    async def async_turn_on(self) -> None:
        await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 1})

    async def async_turn_off(self) -> None:
        await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 0})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 0})
            return

        mode_int = HVAC_MODE_REVERSE.get(hvac_mode, MODE_STOP)
        if mode_int != self._master_value(AZ_MODE):
            if master := self._master_zone():
                await self._async_set_zones_params(
                    [master], {AZ_MODE: mode_int, AZ_POWER: 1}
                )
        await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 1})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs:
            await self._async_set_zones_params(
                self._system_zones(), {AZ_SETPOINT: kwargs[ATTR_TEMPERATURE]}
            )
        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Agrège l'état réel de toutes les zones du système."""
        self._attr_current_temperature = self._zones_average(AZ_TEMP)
        humidity = self._zones_average(AZ_HUMIDITY)
        self._attr_current_humidity = (
            int(round(humidity)) if humidity is not None else None
        )

        zones = self._system_zones()
        is_system_on = any(z.get(AZ_POWER) for z in zones)

        if is_system_on:
            self._attr_hvac_mode = (
                _mode_to_hvac(self._master_value(AZ_MODE)) or HVACMode.OFF
            )
        else:
            self._attr_hvac_mode = HVACMode.OFF

        # Action : active si au moins une zone diffuse (air ou plancher).
        any_air = any(z.get(AZ_AIR_ACTIVE) for z in zones)
        any_rad = any(z.get(AZ_RAD_ACTIVE) for z in zones)
        self._attr_hvac_action = _hvac_action(
            is_system_on, self._master_value(AZ_MODE), any_air, any_rad
        )

        self._attr_max_temp = self._master_value(AZ_MAX_TEMP) or 30.0
        self._attr_min_temp = self._master_value(AZ_MIN_TEMP) or 15.0
        self._attr_target_temperature = self._master_value(AZ_SETPOINT)
