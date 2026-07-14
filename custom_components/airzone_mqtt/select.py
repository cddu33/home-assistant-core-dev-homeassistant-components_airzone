"""Support for the Airzone MQTT select entities."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneEntity, AirzoneSystemEntity, AirzoneZoneEntity

# --- Constantes locales pour remplacer les enums aioairzone ---
# Ces valeurs correspondent au protocole Airzone standard
GRILLE_ANGLE_DICT: Final[dict[str, int]] = {"90deg": 90, "50deg": 50, "45deg": 45, "40deg": 40}
MODE_DICT: Final[dict[str, str]] = {
    "cool": "cool", "dry": "dry", "fan": "fan", 
    "heat": "heat", "heat_cool": "auto", "stop": "stop"
}
SLEEP_DICT: Final[dict[str, int]] = {"off": 0, "30m": 30, "60m": 60, "90m": 90}
Q_ADAPT_DICT: Final[dict[str, str]] = {
    "standard": "standard", "power": "power", "silence": "silence", 
    "minimum": "minimum", "maximum": "maximum"
}
COLD_STAGE_DICT: Final[dict[str, str]] = {"air": "air", "radiant": "radiant", "combined": "combined"}
HEAT_STAGE_DICT: Final[dict[str, str]] = {"air": "air", "radiant": "radiant", "combined": "combined"}

# --- Keys MQTT ---
AZ_Q_ADAPT = "q_adapt"
AZ_SLEEP = "sleep"
AZ_MODE = "mode"
AZ_MODES = "mode_available"
AZ_COLD_ANGLE = "cold_angle"
AZ_HEAT_ANGLE = "heat_angle"
AZ_COLD_STAGE = "cold_stage"
AZ_COLD_STAGES = "cold_stages"
AZ_HEAT_STAGE = "heat_stage"
AZ_HEAT_STAGES = "heat_stages"
AZ_MASTER = "master"

@dataclass(frozen=True, kw_only=True)
class AirzoneSelectDescription(SelectEntityDescription):
    """Description des entités select."""
    api_param: str
    options_dict: dict[str, Any]
    options_fn: Callable[[dict[str, Any], dict[str, Any]], list[str]] = (
        lambda zone_data, value: list(value)
    )

SYSTEM_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param="q_adapt",
        entity_category=EntityCategory.CONFIG,
        key=AZ_Q_ADAPT,
        options_dict=Q_ADAPT_DICT,
        translation_key="q_adapt",
    ),
)

SYSTEM_ZONES_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param="sleep",
        entity_category=EntityCategory.CONFIG,
        key=AZ_SLEEP,
        options_dict=SLEEP_DICT,
        translation_key="all_zones_sleep",
    ),
)

MAIN_ZONE_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param="mode",
        key=AZ_MODE,
        options_dict=MODE_DICT,
        options_fn=lambda zd, v: [k for k, v in v.items() if v in zd.get(AZ_MODES, [])],
        translation_key="modes",
    ),
)

ZONE_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param="cold_angle",
        entity_category=EntityCategory.CONFIG,
        key=AZ_COLD_ANGLE,
        options_dict=GRILLE_ANGLE_DICT,
        translation_key="grille_angles",
    ),
    AirzoneSelectDescription(
        api_param="heat_angle",
        entity_category=EntityCategory.CONFIG,
        key=AZ_HEAT_ANGLE,
        options_dict=GRILLE_ANGLE_DICT,
        translation_key="heat_angles",
    ),
    AirzoneSelectDescription(
        api_param="sleep",
        entity_category=EntityCategory.CONFIG,
        key=AZ_SLEEP,
        options_dict=SLEEP_DICT,
        translation_key="sleep_times",
    ),
    AirzoneSelectDescription(
        api_param="cold_stage",
        entity_category=EntityCategory.CONFIG,
        key=AZ_COLD_STAGE,
        options_dict=COLD_STAGE_DICT,
        options_fn=lambda zd, v: [k for k, val in v.items() if val in zd.get(AZ_COLD_STAGES, [])],
        translation_key="cold_stage",
    ),
    AirzoneSelectDescription(
        api_param="heat_stage",
        entity_category=EntityCategory.CONFIG,
        key=AZ_HEAT_STAGE,
        options_dict=HEAT_STAGE_DICT,
        options_fn=lambda zd, v: [k for k, val in v.items() if val in zd.get(AZ_HEAT_STAGES, [])],
        translation_key="heat_stage",
    ),
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator: AirzoneMqttCoordinator = entry.runtime_data
    added_systems, added_zones = set(), set()

    def _async_entity_listener() -> None:
        entities = []
        systems_data = coordinator.data.get("systems", {})
        for sys_id in set(systems_data) - added_systems:
            entities.extend(AirzoneSystemSelect(coordinator, desc, entry, sys_id, systems_data[sys_id]) 
                            for desc in SYSTEM_SELECT_TYPES if desc.key in systems_data[sys_id])
            entities.extend(AirzoneSystemZonesSelect(coordinator, desc, entry, sys_id) 
                            for desc in SYSTEM_ZONES_SELECT_TYPES)
            added_systems.add(sys_id)

        zones_data = coordinator.data.get("zones", {})
        for z_id in set(zones_data) - added_zones:
            zd = zones_data[z_id]
            if zd.get(AZ_MASTER):
                entities.extend(AirzoneZoneSelect(coordinator, desc, entry, z_id, zd) for desc in MAIN_ZONE_SELECT_TYPES if desc.key in zd)
            entities.extend(AirzoneZoneSelect(coordinator, desc, entry, z_id, zd) for desc in ZONE_SELECT_TYPES if desc.key in zd)
            added_zones.add(z_id)
        async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()

class AirzoneBaseSelect(AirzoneEntity, SelectEntity):
    entity_description: AirzoneSelectDescription
    values_dict: dict[str, Any]

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_current_option = self.values_dict.get(self.get_airzone_value(self.entity_description.key))
        super()._handle_coordinator_update()

class AirzoneSystemSelect(AirzoneSystemEntity, AirzoneBaseSelect):
    def __init__(self, coord, desc, entry, sys_id, sys_data):
        super().__init__(coord, entry, sys_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{sys_id}_{desc.key}"
        self.entity_description = desc
        self._attr_options = desc.options_fn(sys_data, desc.options_dict)
        self.values_dict = {v: k for k, v in desc.options_dict.items()}
        self._attr_current_option = self.values_dict.get(self.get_airzone_value(desc.key))

    async def async_select_option(self, option: str) -> None:
        val = self.entity_description.options_dict[option]
        await self._async_update_sys_params({self.entity_description.api_param: val})

class AirzoneSystemZonesSelect(AirzoneSystemEntity, AirzoneBaseSelect):
    def __init__(self, coord, desc, entry, sys_id):
        super().__init__(coord, entry, coord.data["systems"][sys_id])
        self._attr_unique_id = f"{self._attr_unique_id}_{sys_id}_all_zones_{desc.key}"
        self.entity_description = desc
        self._attr_options = list(desc.options_dict)
        self.values_dict = {v: k for k, v in desc.options_dict.items()}
        self._attr_current_option = self.values_dict.get(self.get_airzone_value(desc.key))

    async def async_select_option(self, option: str) -> None:
        val = self.entity_description.options_dict[option]
        param = self.entity_description.api_param
        # Fan-out sur toutes les zones du système via RPC
        for z_id, z_data in self.coordinator.data.get("zones", {}).items():
            if z_data.get("system_id") == self.system_id:
                await self.coordinator.async_send_rpc("AzZoneSetStatus", {
                    "system_id": self.system_id, "zone_id": z_data["zone_id"],
                    "device_set_status": {param: val}
                })

class AirzoneZoneSelect(AirzoneZoneEntity, AirzoneBaseSelect):
    def __init__(self, coord, desc, entry, z_id, z_data):
        super().__init__(coord, entry, z_id, z_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{z_id}_{desc.key}"
        self.entity_description = desc
        self._attr_options = desc.options_fn(z_data, desc.options_dict)
        if len(self._attr_options) <= 1: self._attr_entity_registry_enabled_default = False
        self.values_dict = {v: k for k, v in desc.options_dict.items()}
        self._attr_current_option = self.values_dict.get(self.get_airzone_value(desc.key))

    async def async_select_option(self, option: str) -> None:
        val = self.entity_description.options_dict[option]
        await self._async_update_hvac_params({self.entity_description.api_param: val})