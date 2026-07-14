"""Config flow pour Airzone via MQTT."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_TOPIC_PREFIX

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOPIC_PREFIX): cv.string,
    }
)

class AirZoneMqttConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère le flux de configuration pour un équipement Airzone MQTT."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Retourne le flux d'options."""
        from .options_flow import AirzoneOptionsFlow
        return AirzoneOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gère la première étape déclenchée par l'utilisateur."""
        errors: dict[str, str] = {}

        if user_input is not None:
            topic_prefix = user_input[CONF_TOPIC_PREFIX].strip()

            if not topic_prefix:
                errors["base"] = "empty_prefix"
            else:
                await self.async_set_unique_id(topic_prefix)
                self._abort_if_unique_id_configured()

                title = f"Airzone ({topic_prefix})"
                
                return self.async_create_entry(
                    title=title, 
                    data={CONF_TOPIC_PREFIX: topic_prefix}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=CONFIG_SCHEMA,
            errors=errors,
        )