"""Options flow pour l'intégration Airzone MQTT."""

from typing import Any
import voluptuous as vol

from homeassistant import config_entries

from .const import CONF_TOPIC_PREFIX

class AirzoneOptionsFlow(config_entries.OptionsFlow):
    """Gère les options de configuration Airzone."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Initialisation des options."""
        if user_input is not None:
            # Met à jour l'entrée avec le nouveau préfixe
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TOPIC_PREFIX, 
                        default=self.config_entry.data.get(CONF_TOPIC_PREFIX)
                    ): str,
                }
            ),
        )