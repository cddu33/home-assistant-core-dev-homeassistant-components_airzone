"""Support for the Airzone MQTT binary sensors."""

from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneEntity, AirzoneSystemEntity, AirzoneZoneEntity

# --- Constantes locales (Clés MQTT natives Airzone) ---
AZ_AIR_DEMAND = "air_demand"
AZ_ANTI_FREEZE = "anti_freeze"
AZ_BATTERY_LOW = "battery_low"
AZ_COLD_DEMAND = "cold_demand"
AZ_DEMAND = "demand"
AZ_ERRORS = "errors"
AZ_FLOOR_DEMAND = "floor_demand"
AZ_HEAT_DEMAND = "heat_demand"

@dataclass(frozen=True)
class AirzoneBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Description d'un capteur binaire Airzone."""
    attributes: dict[str, str] | None = None


# Types de capteurs pour le système global (Souvent les diagnostics d'erreurs)
SYSTEM_BINARY_SENSOR_TYPES: Final[tuple[AirzoneBinarySensorEntityDescription, ...]] = (
    AirzoneBinarySensorEntityDescription(
        attributes={"errors": AZ_ERRORS},
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        key="problems", # Clé virtuelle gérée dans la mise à jour
    ),
)

# Types de capteurs pour chaque zone
ZONE_BINARY_SENSOR_TYPES: Final[tuple[AirzoneBinarySensorEntityDescription, ...]] = (
    AirzoneBinarySensorEntityDescription(
        device_class=BinarySensorDeviceClass.RUNNING,
        key=AZ_AIR_DEMAND,
        translation_key="air_demand",
    ),
    AirzoneBinarySensorEntityDescription(
        entity_category=EntityCategory.DIAGNOSTIC,
        key=AZ_ANTI_FREEZE,
        translation_key="anti_freeze",
    ),
    AirzoneBinarySensorEntityDescription(
        device_class=BinarySensorDeviceClass.BATTERY,
        key=AZ_BATTERY_LOW,
    ),
    AirzoneBinarySensorEntityDescription(
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        key=AZ_COLD_DEMAND,
        translation_key="cold_demand",
    ),
    AirzoneBinarySensorEntityDescription(
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        key=AZ_DEMAND,
        translation_key="demand",
    ),
    AirzoneBinarySensorEntityDescription(
        device_class=BinarySensorDeviceClass.RUNNING,
        key=AZ_FLOOR_DEMAND,
        translation_key="floor_demand",
    ),
    AirzoneBinarySensorEntityDescription(
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        key=AZ_HEAT_DEMAND,
        translation_key="heat_demand",
    ),
    AirzoneBinarySensorEntityDescription(
        attributes={"errors": AZ_ERRORS},
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        key="problems",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Ajoute les capteurs binaires Airzone depuis le coordinateur MQTT."""
    coordinator: AirzoneMqttCoordinator = entry.runtime_data

    added_systems: set[str] = set()
    added_zones: set[str] = set()

    def _async_entity_listener() -> None:
        """Crée les capteurs à la volée dès qu'on les découvre dans le payload MQTT."""
        entities: list[AirzoneBinarySensor] = []

        # -- Systèmes --
        systems_data = coordinator.data.get("systems", {})
        for sys_id in set(systems_data) - added_systems:
            sys_data = systems_data[sys_id]
            for desc in SYSTEM_BINARY_SENSOR_TYPES:
                entities.append(AirzoneSystemBinarySensor(coordinator, desc, entry, sys_id, sys_data))
            added_systems.add(sys_id)

        # -- Zones --
        zones_data = coordinator.data.get("zones", {})
        for z_id in set(zones_data) - added_zones:
            z_data = zones_data[z_id]
            for desc in ZONE_BINARY_SENSOR_TYPES:
                # On ne crée le sensor que si la donnée existe, à l'exception de "problems"
                if desc.key == "problems" or desc.key in z_data:
                    entities.append(AirzoneZoneBinarySensor(coordinator, desc, entry, z_id, z_data))
            added_zones.add(z_id)

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneBinarySensor(AirzoneEntity, BinarySensorEntity):
    """Base d'un capteur binaire Airzone."""

    entity_description: AirzoneBinarySensorEntityDescription

    @callback
    def _handle_coordinator_update(self) -> None:
        """Met à jour les attributs lors de la réception d'un nouveau payload MQTT."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Extraction de l'état binaire."""
        
        # Gestion spécifique des erreurs (tableau MQTT vers booléen "Problem")
        if self.entity_description.key == "problems":
            errors = self.get_airzone_value(AZ_ERRORS) or []
            self._attr_is_on = len(errors) > 0
            if self.entity_description.attributes:
                self._attr_extra_state_attributes = {"errors": errors}
        else:
            val = self.get_airzone_value(self.entity_description.key)
            # En MQTT les données binaires peuvent être int(0/1) ou bool
            self._attr_is_on = bool(val) if val is not None else None


class AirzoneSystemBinarySensor(AirzoneSystemEntity, AirzoneBinarySensor):
    """Capteur binaire rattaché au système global."""

    def __init__(self, coord, desc, entry, sys_id, sys_data) -> None:
        super().__init__(coord, entry, sys_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{sys_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()


class AirzoneZoneBinarySensor(AirzoneZoneEntity, AirzoneBinarySensor):
    """Capteur binaire rattaché à une zone spécifique."""

    def __init__(self, coord, desc, entry, z_id, z_data) -> None:
        super().__init__(coord, entry, z_id, z_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{z_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()