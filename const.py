"""Constants for the Airzone integration."""

from typing import Final

from aioairzone.common import TemperatureUnit

from homeassistant.const import UnitOfTemperature

DOMAIN: Final = "airzone"
MANUFACTURER: Final = "Airzone"

AIOAIRZONE_DEVICE_TIMEOUT_SEC: Final = 10
API_TEMPERATURE_STEP: Final = 0.5

# Polling interval (seconds): configurable through the options flow.
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 10

TEMP_UNIT_LIB_TO_HASS: Final[dict[TemperatureUnit, str]] = {
    TemperatureUnit.CELSIUS: UnitOfTemperature.CELSIUS,
    TemperatureUnit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
}
