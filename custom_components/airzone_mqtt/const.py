"""Constants for the Airzone MQTT integration."""

from typing import Final

from homeassistant.const import UnitOfTemperature

DOMAIN: Final = "airzone_mqtt"
MANUFACTURER: Final = "Airzone"
CONF_TOPIC_PREFIX: Final = "topic_prefix"

API_TEMPERATURE_STEP: Final = 0.5

# Selon la doc API MQTT d'Airzone, 0 = Celsius, 1 = Fahrenheit
TEMP_UNIT_MAP: Final[dict[int, str]] = {
    0: UnitOfTemperature.CELSIUS,
    1: UnitOfTemperature.FAHRENHEIT,
}