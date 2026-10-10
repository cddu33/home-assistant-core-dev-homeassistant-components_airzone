"""Constants for the Android TV Remote integration."""

from typing import Final

DOMAIN: Final = "androidtv_remote"

CONF_APPS = "apps"
CONF_ENABLE_IME: Final = "enable_ime"
CONF_ENABLE_IME_DEFAULT_VALUE: Final = True
CONF_APP_NAME = "app_name"
CONF_APP_ICON = "app_icon"

# Seconds an entity keeps its last known state after the connection drops,
# before being marked unavailable. Hides short disconnect/reconnect cycles
# (e.g. Epson projectors in standby that stop answering pings).
CONF_UNAVAILABLE_GRACE_PERIOD: Final = "unavailable_grace_period"
CONF_UNAVAILABLE_GRACE_PERIOD_DEFAULT_VALUE: Final = 60

# Seconds without any message from the device before the connection is
# considered dead. The upstream library hard-codes 16 seconds.
CONF_IDLE_TIMEOUT: Final = "idle_timeout"
CONF_IDLE_TIMEOUT_DEFAULT_VALUE: Final = 16
