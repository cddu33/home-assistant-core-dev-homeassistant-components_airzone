"""Support for the Airzone MQTT water heater."""

import logging
from typing import Any, Final

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneHotWaterEntity

_LOGGER = logging.getLogger(__name__)

# --- Constantes locales (Clés MQTT natives Airzone pour l'ECS) ---
AZ_ACS_TEMP = "work_temp"
AZ_ACS_SETPOINT = "setpoint"
AZ_ACS_POWER = "power"
AZ_ACS_MAX_TEMP = "max_temp"
AZ_ACS_MIN_TEMP = "min_temp"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Ajoute le chauffe-eau Airzone depuis le coordinateur MQTT."""
    coordinator: AirzoneMqttCoordinator = entry.runtime_data
    added_dhw = False

    def _async_entity_listener() -> None:
        """Détecte si un module ECS (dhw) est poussé par le JSON MQTT."""
        nonlocal added_dhw
        dhw_data = coordinator.data.get("dhw", {})
        
        # Si on reçoit des données dhw et qu'il n'est pas encore ajouté
        if dhw_data and not added_dhw:
            async_add_entities([AirzoneWaterHeater(coordinator, entry)])
            added_dhw = True

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneWaterHeater(AirzoneHotWaterEntity, WaterHeaterEntity):
    """Représentation du module ECS (Chauffe-eau) Airzone."""

    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: AirzoneMqttCoordinator, entry: ConfigEntry) -> None:
        """Initialisation."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._attr_unique_id}_dhw"
        self._async_update_attrs()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allume l'ECS."""
        await self._async_update_dhw_params({"power": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Éteint l'ECS."""
        await self._async_update_dhw_params({"power": 0})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Modifie la température cible de l'ECS."""
        if ATTR_TEMPERATURE in kwargs:
            await self._async_update_dhw_params({"setpoint": kwargs[ATTR_TEMPERATURE]})

    @callback
    def _handle_coordinator_update(self) -> None:
        """Met à jour l'entité lors de la réception d'une trame MQTT."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Rafraîchit les attributs à partir des données internes."""
        self._attr_current_temperature = self.get_airzone_value(AZ_ACS_TEMP)
        self._attr_target_temperature = self.get_airzone_value(AZ_ACS_SETPOINT)
        self._attr_min_temp = self.get_airzone_value(AZ_ACS_MIN_TEMP) or 20.0
        self._attr_max_temp = self.get_airzone_value(AZ_ACS_MAX_TEMP) or 60.0