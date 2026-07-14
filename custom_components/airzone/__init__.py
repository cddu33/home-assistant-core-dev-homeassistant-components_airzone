"""The Airzone MQTT integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_TOPIC_PREFIX, DOMAIN, MANUFACTURER
# On importera notre futur gestionnaire MQTT qu'on va coder juste après
from .coordinator import AirzoneMqttCoordinator

# Liste des plateformes que ton intégration va gérer
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

_LOGGER = logging.getLogger(__name__)

# Typage moderne (HA 2024.x) pour attacher le coordinateur à l'entrée de config
type AirzoneConfigEntry = ConfigEntry[AirzoneMqttCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AirzoneConfigEntry) -> bool:
    """Configure Airzone MQTT à partir d'une entrée de configuration."""
    topic_prefix = entry.data[CONF_TOPIC_PREFIX]

    # Initialisation de notre gestionnaire central MQTT
    coordinator = AirzoneMqttCoordinator(hass, entry, topic_prefix)
    
    # On abonne notre coordinateur aux topics MQTT de base
    await coordinator.async_init()

    # On attache le coordinateur à l'entrée de config pour que les plateformes (climate.py, etc.) y accèdent
    entry.runtime_data = coordinator

    # Enregistrement du Webserver (la passerelle principale) dans le Device Registry de HA
    device_registry = dr.async_get(hass)
    
    # Si le préfixe fait 12 caractères, c'est probablement la vraie MAC, on la déclare formellement
    connections = set()
    if len(topic_prefix) == 12:
        connections.add((dr.CONNECTION_NETWORK_MAC, topic_prefix.upper()))

    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections=connections,
        identifiers={(DOMAIN, topic_prefix)},
        manufacturer=MANUFACTURER,
        name=f"Airzone Webserver ({topic_prefix})",
        model="Webserver / Aidoo (MQTT)",
    )

    # HA va maintenant charger les fichiers climate.py, sensor.py, etc.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AirzoneConfigEntry) -> bool:
    """Décharge une entrée de configuration."""
    
    # On se désabonne proprement des topics MQTT
    if entry.runtime_data:
        await entry.runtime_data.async_unload()

    # On décharge les plateformes
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)