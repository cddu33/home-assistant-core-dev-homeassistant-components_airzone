"""Support for the Airzone MQTT sensors."""

from dataclasses import dataclass
from typing import Any, Final
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AirzoneMqttCoordinator
from .entity import AirzoneEntity, AirzoneSystemEntity, AirzoneWebServerEntity, AirzoneZoneEntity

_LOGGER = logging.getLogger(__name__)

# --- Constantes locales (Clés MQTT natives) ---
AZ_ECO_ADAPT = "eco_adapt"
AZ_POWER_W = "power"  # Consommation en Watts si pince ampèremétrique
AZ_RSSI = "rssi"
AZ_THERMOSTAT_SIGNAL = "radio_rssi" # À ajuster selon le JSON réel du thermostat
AZ_WIFI_CHANNEL = "wifi_channel"
AZ_WIFI_QUALITY = "wifi_quality"

# Mapping pour Eco-Adapt (conversion des valeurs de la machine vers strings.json)
ECO_ADAPT_MAP: dict[Any, str] = {
    0: "off",
    1: "manual",
    2: "a",
    3: "a_p",
    4: "a_pp",
    "off": "off",
    "manual": "manual",
    "a": "a",
    "a+": "a_p",
    "a++": "a_pp",
}

@dataclass(frozen=True)
class AirzoneSensorEntityDescription(SensorEntityDescription):
    """Description d'un capteur Airzone."""
    value_fn: callable = lambda val: val


# --- Capteurs du Webserver (Wi-Fi, Qualité du signal) ---
WEBSERVER_SENSOR_TYPES: Final[tuple[AirzoneSensorEntityDescription, ...]] = (
    AirzoneSensorEntityDescription(
        key=AZ_RSSI,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        translation_key="rssi",
    ),
    AirzoneSensorEntityDescription(
        key=AZ_WIFI_CHANNEL,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="wifi_channel",
    ),
    AirzoneSensorEntityDescription(
        key=AZ_WIFI_QUALITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        translation_key="wifi_quality",
    ),
)

# --- Capteurs du Système Global ---
SYSTEM_SENSOR_TYPES: Final[tuple[AirzoneSensorEntityDescription, ...]] = (
    AirzoneSensorEntityDescription(
        key=AZ_ECO_ADAPT,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="eco_adapt",
        value_fn=lambda val: ECO_ADAPT_MAP.get(val, val),
    ),
    AirzoneSensorEntityDescription(
        key=AZ_POWER_W,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        translation_key="power",
    ),
)

# --- Capteurs des Zones individuelles ---
ZONE_SENSOR_TYPES: Final[tuple[AirzoneSensorEntityDescription, ...]] = (
    AirzoneSensorEntityDescription(
        key=AZ_THERMOSTAT_SIGNAL,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        translation_key="thermostat_signal",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Ajoute les capteurs Airzone depuis le coordinateur MQTT."""
    coordinator: AirzoneMqttCoordinator = entry.runtime_data

    added_webserver = False
    added_systems: set[str] = set()
    added_zones: set[str] = set()

    def _async_entity_listener() -> None:
        """Crée les capteurs à la volée dès qu'on les découvre dans le payload MQTT."""
        entities: list[AirzoneSensor] = []
        nonlocal added_webserver

        # -- Webserver --
        webserver_data = coordinator.data.get("webserver", {})
        if webserver_data and not added_webserver:
            for desc in WEBSERVER_SENSOR_TYPES:
                # On ajoute le sensor s'il est présent dans le JSON, ou par défaut pour le Wi-Fi
                if desc.key in webserver_data or desc.key in [AZ_RSSI, AZ_WIFI_QUALITY]:
                    entities.append(AirzoneWebServerSensor(coordinator, desc, entry))
            added_webserver = True

        # -- Systèmes --
        systems_data = coordinator.data.get("systems", {})
        for sys_id in set(systems_data) - added_systems:
            sys_data = systems_data[sys_id]
            for desc in SYSTEM_SENSOR_TYPES:
                if desc.key in sys_data:
                    entities.append(AirzoneSystemSensor(coordinator, desc, entry, sys_id, sys_data))
            added_systems.add(sys_id)

        # -- Zones --
        zones_data = coordinator.data.get("zones", {})
        for z_id in set(zones_data) - added_zones:
            z_data = zones_data[z_id]
            for desc in ZONE_SENSOR_TYPES:
                if desc.key in z_data:
                    entities.append(AirzoneZoneSensor(coordinator, desc, entry, z_id, z_data))
            added_zones.add(z_id)

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneSensor(AirzoneEntity, SensorEntity):
    """Base d'un capteur standard Airzone."""

    entity_description: AirzoneSensorEntityDescription

    @callback
    def _handle_coordinator_update(self) -> None:
        """Met à jour les attributs lors de la réception d'un nouveau payload MQTT."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @callback
    def _async_update_attrs(self) -> None:
        """Extraction de la valeur et application de la fonction de formatage si nécessaire."""
        raw_val = self.get_airzone_value(self.entity_description.key)
        
        if raw_val is not None:
            self._attr_native_value = self.entity_description.value_fn(raw_val)
        else:
            self._attr_native_value = None


class AirzoneWebServerSensor(AirzoneWebServerEntity, AirzoneSensor):
    """Capteur rattaché à la passerelle WebServer (ex: Wi-Fi)."""

    def __init__(self, coord, desc, entry) -> None:
        super().__init__(coord, entry)
        self._attr_unique_id = f"{self._attr_unique_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()


class AirzoneSystemSensor(AirzoneSystemEntity, AirzoneSensor):
    """Capteur rattaché au système global (ex: Eco-Adapt)."""

    def __init__(self, coord, desc, entry, sys_id, sys_data) -> None:
        super().__init__(coord, entry, sys_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{sys_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()


class AirzoneZoneSensor(AirzoneZoneEntity, AirzoneSensor):
    """Capteur rattaché à une zone spécifique (ex: Signal thermostat)."""

    def __init__(self, coord, desc, entry, z_id, z_data) -> None:
        super().__init__(coord, entry, z_id, z_data)
        self._attr_unique_id = f"{self._attr_unique_id}_{z_id}_{desc.key}"
        self.entity_description = desc
        self._async_update_attrs()