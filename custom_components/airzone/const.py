"""Constants for the Airzone integration."""

from typing import Final

from aioairzone.common import TemperatureUnit

from homeassistant.const import UnitOfTemperature

DOMAIN: Final = "airzone"
MANUFACTURER: Final = "Airzone"

# One update issues up to 4 serialized HTTP calls (HVAC, then DHW/systems/
# webserver), each with aioairzone's own 10s per-call timeout, so a 10s budget
# for the whole cycle could abort it with no single request having timed out.
AIOAIRZONE_DEVICE_TIMEOUT_SEC: Final = 20
API_TEMPERATURE_STEP: Final = 0.5

DEFAULT_SCAN_INTERVAL: Final = 60

TEMP_UNIT_LIB_TO_HASS: Final[dict[TemperatureUnit, str]] = {
    TemperatureUnit.CELSIUS: UnitOfTemperature.CELSIUS,
    TemperatureUnit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
}
