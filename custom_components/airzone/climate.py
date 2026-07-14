"""Support for the Airzone MQTT climate."""

from typing import Any, Final
import logging

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
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import API_TEMPERATURE_STEP, TEMP_UNIT_MAP
from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneSystemEntity, AirzoneZoneEntity

_LOGGER = logging.getLogger(__name__)

# --- Constantes des clés JSON MQTT Airzone ---
AZ_TEMP = "zone_work_temp"
AZ_HUMIDITY = "humidity"
AZ_POWER = "power"
AZ_MODE = "mode"
AZ_MODES = "mode_available"
AZ_SETPOINT = "setpoint"
AZ_COOL_SETPOINT = "setpoint_cool"
AZ_HEAT_SETPOINT = "setpoint_heat"
AZ_ACTION = "action"
AZ_SPEED = "speed_conf"
AZ_SPEEDS = "speed_values"
AZ_MASTER = "master"
AZ_TEMP_UNIT = "units"
AZ_DOUBLE_SP = "double_sp"
AZ_MAX_TEMP = "max_temp"
AZ_MIN_TEMP = "min_temp"

# --- Mapping des modes MQTT vers Home Assistant ---
HVAC_MODE_MAP: Final[dict[str, HVACMode]] = {
    "stop": HVACMode.OFF,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "fan": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
    "auto": HVACMode.HEAT_COOL,
}
HVAC_MODE_REVERSE: Final[dict[HVACMode, str]] = {v: k for k, v in HVAC_MODE_MAP.items()}

# --- Mapping des actions (si fournies par MQTT) ---
HVAC_ACTION_MAP: Final[dict[str, HVACAction]] = {
    "cooling": HVACAction.COOLING,
    "heating": HVACAction.HEATING,
    "fan": HVACAction.FAN,
    "drying": HVACAction.DRYING,
    "idle": HVACAction.IDLE,
    "stop": HVACAction.OFF,
}

BASE_FAN_SPEEDS: Final[dict[int, str]] = {
    0: FAN_AUTO,
    1: FAN_LOW,
}

FAN_SPEED_MAPS: Final[dict[int, dict[int, str]]] = {
    2: BASE_FAN_SPEEDS | {2: FAN_HIGH},
    3: BASE_FAN_SPEEDS | {2: FAN_MEDIUM, 3: FAN_HIGH},
}


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
        """Gère l'ajout dynamique des systèmes et des zones à la réception des données."""
        entities: list[ClimateEntity] = []

        # --- Découverte des Systèmes globaux ---
        systems_data = coordinator.data.get("systems", {})
        received_systems = set(systems_data)
        new_systems = received_systems - added_systems
        if new_systems:
            entities.extend(
                AirzoneSystemClimate(coordinator, entry, sys_id, systems_data[sys_id])
                for sys_id in new_systems
            )
            added_systems.update(new_systems)

        # --- Découverte des Zones individuelles ---
        zones_data = coordinator.data.get("zones", {})
        received_zones = set(zones_data)
        new_zones = received_zones - added_zones
        if new_zones:
            entities.extend(
                AirzoneClimate(coordinator, entry, sys_zone_id, zones_data[sys_zone_id])
                for sys_zone_id in new_zones
            )
            added_zones.update(new_zones)

        if entities:
            async_add_entities(entities)

    # On attache le listener pour créer les entités dès que le MQTT reçoit la première trame
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

        # Définition de l'unité de température
        unit_val = self.get_airzone_value(AZ_TEMP_UNIT)
        self._attr_temperature_unit = TEMP_UNIT_MAP.get(unit_val, UnitOfTemperature.CELSIUS)

        self._is_master = bool(self.get_airzone_value(AZ_MASTER))
        
        # Mapping des modes
        if self._is_master:
            modes = self.get_airzone_value(AZ_MODES) or ["stop"]
            self._attr_hvac_modes = list({HVAC_MODE_MAP.get(m, HVACMode.OFF) for m in modes})
        else:
            self._update_slave_hvac_modes()

        # Mapping des vitesses de ventilation
        if self.get_airzone_value(AZ_SPEED) is not None and self.get_airzone_value(AZ_SPEEDS):
            self._set_fan_speeds()

        if self.get_airzone_value(AZ_DOUBLE_SP):
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

        self._async_update_attrs()

    def _update_slave_hvac_modes(self) -> None:
        """Restreint les modes pour une zone esclave (ne peut que s'éteindre ou suivre le maître)."""
        modes = [HVACMode.OFF]
        current_mode = self.get_airzone_value(AZ_MODE)
        mapped_mode = HVAC_MODE_MAP.get(current_mode)
        if mapped_mode and mapped_mode != HVACMode.OFF:
            modes.append(mapped_mode)
        self._attr_hvac_modes = list(set(modes))

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
        if speed_conf := self._speeds_reverse.get(fan_mode):
            await self._async_update_hvac_params({AZ_SPEED: speed_conf})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change le mode HVAC."""
        slave_raise = False
        params = {}
        
        if hvac_mode == HVACMode.OFF:
            params[AZ_POWER] = 0
        else:
            mode_str = HVAC_MODE_REVERSE.get(hvac_mode, "stop")
            if mode_str != self.get_airzone_value(AZ_MODE):
                if self._is_master:
                    params[AZ_MODE] = mode_str
                else:
                    slave_raise = True
            params[AZ_POWER] = 1

        await self._async_update_hvac_params(params)

        if slave_raise:
            raise HomeAssistantError(f"Le mode ne peut pas être modifié sur la zone esclave {self.entity_id}")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Modifie la consigne de température."""
        params = {}
        if ATTR_TEMPERATURE in kwargs:
            params[AZ_SETPOINT] = kwargs[ATTR_TEMPERATURE]
        if ATTR_TARGET_TEMP_LOW in kwargs and ATTR_TARGET_TEMP_HIGH in kwargs:
            params[AZ_COOL_SETPOINT] = kwargs[ATTR_TARGET_TEMP_HIGH]
            params[AZ_HEAT_SETPOINT] = kwargs[ATTR_TARGET_TEMP_LOW]
        
        if params:
            await self._async_update_hvac_params(params)

        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Met à jour l'interface avec les données MQTT reçues."""
        if not self._is_master:
            self._update_slave_hvac_modes()
            
        self._attr_current_temperature = self.get_airzone_value(AZ_TEMP)
        self._attr_current_humidity = self.get_airzone_value(AZ_HUMIDITY)
        
        action_val = self.get_airzone_value(AZ_ACTION)
        self._attr_hvac_action = HVAC_ACTION_MAP.get(action_val) if action_val else None

        if self.get_airzone_value(AZ_POWER):
            self._attr_hvac_mode = HVAC_MODE_MAP.get(self.get_airzone_value(AZ_MODE), HVACMode.OFF)
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self._attr_max_temp = self.get_airzone_value(AZ_MAX_TEMP) or 30.0
        self._attr_min_temp = self.get_airzone_value(AZ_MIN_TEMP) or 15.0

        if self.supported_features & ClimateEntityFeature.FAN_MODE:
            current_speed = self.get_airzone_value(AZ_SPEED)
            self._attr_fan_mode = self._speeds.get(current_speed)

        if (
            self.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            and self._attr_hvac_mode == HVACMode.HEAT_COOL
        ):
            self._attr_target_temperature_high = self.get_airzone_value(AZ_COOL_SETPOINT)
            self._attr_target_temperature_low = self.get_airzone_value(AZ_HEAT_SETPOINT)
            self._attr_target_temperature = None
        else:
            self._attr_target_temperature_high = None
            self._attr_target_temperature_low = None
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
        self._attr_temperature_unit = TEMP_UNIT_MAP.get(unit_val, UnitOfTemperature.CELSIUS)

        modes = self._master_value(AZ_MODES) or []
        self._attr_hvac_modes = list({HVAC_MODE_MAP.get(m, HVACMode.OFF) for m in modes}) or [HVACMode.OFF]

        self._async_update_attrs()

    def _system_zones(self) -> list[dict[str, Any]]:
        """Retourne toutes les zones appartenant à ce système."""
        zones = self.coordinator.data.get("zones", {})
        return [z for z in zones.values() if z.get("system_id") == self.system_id]

    def _master_zone(self) -> dict[str, Any] | None:
        """Trouve la zone principale (maître) du système."""
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
        """Fait la moyenne d'une valeur (ex: température) sur toutes les zones."""
        values = [zone[key] for zone in self._system_zones() if zone.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    async def _async_set_zones_params(self, zones: list[dict[str, Any]], params: dict[str, Any]) -> None:
        """Envoie les mêmes paramètres à toutes les zones (Fan-out via RPC MQTT)."""
        try:
            for zone in zones:
                rpc_params = {
                    "system_id": zone.get("system_id"),
                    "zone_id": zone.get("zone_id"),
                    "device_set_status": params
                }
                await self.coordinator.async_send_rpc("AzZoneSetStatus", rpc_params)
        except Exception as error:
            raise HomeAssistantError(f"Échec de mise à jour du système {self.entity_id}: {error}") from error

    async def async_turn_on(self) -> None:
        await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 1})

    async def async_turn_off(self) -> None:
        await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 0})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 0})
            return

        mode_str = HVAC_MODE_REVERSE.get(hvac_mode, "stop")
        if mode_str != self._master_value(AZ_MODE):
            if master := self._master_zone():
                await self._async_set_zones_params([master], {AZ_MODE: mode_str, AZ_POWER: 1})
        await self._async_set_zones_params(self._system_zones(), {AZ_POWER: 1})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        params = {}
        if ATTR_TEMPERATURE in kwargs:
            params[AZ_SETPOINT] = kwargs[ATTR_TEMPERATURE]
        if ATTR_TARGET_TEMP_LOW in kwargs and ATTR_TARGET_TEMP_HIGH in kwargs:
            params[AZ_COOL_SETPOINT] = kwargs[ATTR_TARGET_TEMP_HIGH]
            params[AZ_HEAT_SETPOINT] = kwargs[ATTR_TARGET_TEMP_LOW]
            
        if params:
            await self._async_set_zones_params(self._system_zones(), params)
        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Met à jour l'interface en concaténant l'état réel de toutes les zones."""
        self._attr_current_temperature = self._zones_average(AZ_TEMP)
        humidity = self._zones_average(AZ_HUMIDITY)
        self._attr_current_humidity = int(round(humidity)) if humidity is not None else None

        # --- 1. Concaténation de l'état ON/OFF ---
        # Le système est ON si au moins UNE zone est active (on sécurise le format de la valeur)
        is_system_on = any(
            zone.get(AZ_POWER) in [1, True, "1"] 
            for zone in self._system_zones()
        )

        if is_system_on:
            # Si allumé, le mode global (Heat/Cool) est dicté par la machine (zone maître)
            self._attr_hvac_mode = HVAC_MODE_MAP.get(self._master_value(AZ_MODE), HVACMode.OFF)
        else:
            self._attr_hvac_mode = HVACMode.OFF

        # --- 2. Concaténation de l'action en cours ---
        # S'il y a au moins une zone qui chauffe ou refroidit, le système entier travaille
        actions = [zone.get(AZ_ACTION) for zone in self._system_zones() if zone.get(AZ_ACTION)]
        
        # On isole les actions actives en excluant les états de repos
        active_actions = [a for a in actions if a not in ("idle", "stop")]
        
        if active_actions:
            action_val = active_actions[0] # On prend la première action active (ex: "cooling")
        elif actions:
            action_val = actions[0] # S'il n'y a que du repos, on prend "idle"
        else:
            action_val = None
            
        self._attr_hvac_action = HVAC_ACTION_MAP.get(action_val) if action_val else None

        # --- 3. Températures ---
        self._attr_max_temp = self._master_value(AZ_MAX_TEMP) or 30.0
        self._attr_min_temp = self._master_value(AZ_MIN_TEMP) or 15.0
        self._attr_target_temperature = self._master_value(AZ_SETPOINT)