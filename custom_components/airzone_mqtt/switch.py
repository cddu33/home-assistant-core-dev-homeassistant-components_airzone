"""Support for the Airzone MQTT switches."""

from dataclasses import dataclass
from typing import Any, Final
import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneEntity, AirzoneSystemEntity, AirzoneZoneEntity

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class AirzoneSwitchEntityDescription(SwitchEntityDescription):
    """Description d'un Switch Airzone."""
    api_param: str


# --- Définit ici tes interrupteurs si besoin ---
# Par exemple, si tu as une option binaire MQTT "auto_mode" sur ton système
SYSTEM_SWITCH_TYPES: Final[tuple[AirzoneSwitchEntityDescription, ...]] = (
    # AirzoneSwitchEntityDescription(
    #     key="auto_mode",
    #     api_param="auto_mode",
    #     entity_category=EntityCategory.CONFIG,
    #     translation_key="auto_mode",
    # ),
)

ZONE_SWITCH_TYPES: Final[tuple[AirzoneSwitchEntityDescription, ...]] = (
    # À remplir selon les besoins
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Ajoute les switchs Airzone."""
    coordinator: AirzoneMqttCoordinator = entry.runtime_data
    added_systems: set[str] = set()
    added_zones: set[str] = set()

    def _async_entity_listener() -> None:
        entities: list[SwitchEntity] = []

        # --- Systèmes ---
        systems_data = coordinator.data.get("systems", {})
        for sys_id in set(systems_data) - added_systems:
            sys_data = systems_data[sys_id]
            for desc in SYSTEM_SWITCH_TYPES:
                if desc.key in sys_data:
                    entities.append(AirzoneSystemSwitch(coordinator, desc, entry, sys_id, sys_data))
            added_systems.add(sys_id)

        # --- Zones ---
        zones_data = coordinator.data.get("zones", {})
        for z_id in set(zones_data) - added_zones:
            z_data = zones_data[z_id]
            for desc in ZONE_SWITCH_TYPES:
                if desc.key in z_data:
                    entities.append(AirzoneZoneSwitch(coordinator, desc, entry, z_id, z_data))
            added_zones.add(z_id)

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneBaseSwitch(AirzoneEntity, SwitchEntity):
    """Classe de base pour un Switch Airzone."""

    entity_description: AirzoneSwitchEntityDescription

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Met à jour l'état du switch (ON/OFF) depuis les données MQTT."""
        val = self.get_airzone_value(self.entity_description.key)
        self._attr_is_on = bool(val) if val is not None else None


class AirzoneSystemSwitch(AirzoneSystemEntity, AirzoneBaseSwitch):
    """Switch pour le Système global."""

    def __init__(self, coord, desc, entry, sys_id, sys_data) -> None:
        super().__init__(coord, entry, sys_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{sys_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_update_sys_params({self.entity_description.api_param: 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_update_sys_params({self.entity_description.api_param: 0})


class AirzoneZoneSwitch(AirzoneZoneEntity, AirzoneBaseSwitch):
    """Switch pour une Zone individuelle."""

    def __init__(self, coord, desc, entry, z_id, z_data) -> None:
        super().__init__(coord, entry, z_id, z_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{z_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_update_hvac_params({self.entity_description.api_param: 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_update_hvac_params({self.entity_description.api_param: 0})