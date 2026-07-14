"""Config flow pour Airzone via MQTT."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import homeassistant.helpers.config_validation as cv

# Assure-toi d'avoir ajouté CONF_TOPIC_PREFIX dans ton fichier const.py
from .const import DOMAIN, CONF_TOPIC_PREFIX

_LOGGER = logging.getLogger(__name__)

# Le schéma demande l'alias / topic de départ
CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOPIC_PREFIX): cv.string,
    }
)

class AirZoneMqttConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère le flux de configuration pour un équipement Airzone MQTT."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gère la première étape déclenchée par l'utilisateur."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # On récupère l'alias en enlevant juste les espaces avant/après.
            # On NE change PAS la casse, car MQTT y est sensible.
            topic_prefix = user_input[CONF_TOPIC_PREFIX].strip()

            if not topic_prefix:
                errors["base"] = "empty_prefix"
            else:
                # On utilise cet alias comme identifiant unique
                await self.async_set_unique_id(topic_prefix)
                self._abort_if_unique_id_configured()

                # Création de l'entrée dans Home Assistant
                title = f"Airzone ({topic_prefix})"
                
                # On sauvegarde le préfixe pour pouvoir l'utiliser dans __init__.py
                return self.async_create_entry(
                    title=title, 
                    data={CONF_TOPIC_PREFIX: topic_prefix}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=CONFIG_SCHEMA,
            errors=errors,
        )