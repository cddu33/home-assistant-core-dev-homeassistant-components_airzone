"""Support for the Airzone diagnostics."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant

from .const import CONF_TOPIC_PREFIX
from .coordinator import AirzoneConfigEntry

# Données à masquer dans le fichier de config (pour la vie privée)
TO_REDACT_CONFIG = [
    CONF_UNIQUE_ID,
    CONF_TOPIC_PREFIX,
]

# Données à masquer dans le coordinateur MQTT
TO_REDACT_COORD = [
    "mac",
    "topic_prefix",
]

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: AirzoneConfigEntry
) -> dict[str, Any]:
    """Retourne les données de diagnostic de l'intégration pour Home Assistant."""
    coordinator = config_entry.runtime_data

    return {
        "config_entry": async_redact_data(config_entry.as_dict(), TO_REDACT_CONFIG),
        "coord_data": async_redact_data(coordinator.data, TO_REDACT_COORD),
    }