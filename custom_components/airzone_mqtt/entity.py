"""Entity classes for the Airzone MQTT integration."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AirzoneMqttCoordinator

_LOGGER = logging.getLogger(__name__)

# Anciennes constantes de aioairzone, redéfinies ici pour l'autonomie du module
AZD_AVAILABLE = "available"
AZD_FIRMWARE = "firmware"
AZD_FULL_NAME = "name"
AZD_HOT_WATER = "dhw"
AZD_ID = "zone_id"
AZD_MAC = "mac"
AZD_MODEL = "model"
AZD_NAME = "name"
AZD_SYSTEM = "system_id"
AZD_SYSTEMS = "systems"
AZD_THERMOSTAT_FW = "thermostat_fw"
AZD_THERMOSTAT_MODEL = "thermostat_model"
AZD_WEBSERVER = "webserver"
AZD_ZONES = "zones"


class AirzoneEntity(CoordinatorEntity[AirzoneMqttCoordinator]):
    """Classe de base pour une entité Airzone."""

    _attr_has_entity_name = True

    def get_airzone_value(self, key: str) -> Any:
        """Retourne la valeur de l'entité par sa clé."""
        raise NotImplementedError


class AirzoneSystemEntity(AirzoneEntity):
    """Représentation d'un Système Airzone global."""

    def __init__(
        self,
        coordinator: AirzoneMqttCoordinator,
        entry: ConfigEntry,
        system_data: dict[str, Any],
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator)

        self.system_id = system_data.get(AZD_SYSTEM, 1)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{self.system_id}")},
            manufacturer=MANUFACTURER,
            model=self.get_airzone_value(AZD_MODEL),
            name=f"System {self.system_id}",
            sw_version=self.get_airzone_value(AZD_FIRMWARE),
        )
        if AZD_WEBSERVER in self.coordinator.data:
            self._attr_device_info["via_device"] = (DOMAIN, f"{entry.entry_id}_ws")
        self._attr_unique_id = entry.unique_id or entry.entry_id

    @property
    def available(self) -> bool:
        """Retourne la disponibilité du système."""
        # En MQTT, on considère par défaut que c'est disponible si on reçoit des trames
        return super().available and self.get_airzone_value(AZD_AVAILABLE) is not False

    def get_airzone_value(self, key: str) -> Any:
        """Retourne la valeur par clé pour ce système."""
        value = None
        if system := self.coordinator.data.get(AZD_SYSTEMS, {}).get(str(self.system_id)):
            if key in system:
                value = system[key]
        return value

    async def _async_update_sys_params(self, params: dict[str, Any]) -> None:
        """Envoie les paramètres système via l'API RPC MQTT."""
        _LOGGER.debug("update_sys_params=%s", params)
        try:
            # Format RPC attendu pour un système
            rpc_params = {
                "system_id": self.system_id,
                "device_set_status": params
            }
            await self.coordinator.async_send_rpc("AzSystemSetStatus", rpc_params)
        except Exception as error:
            raise HomeAssistantError(
                f"Échec de l'envoi de la commande système {self.entity_id}: {error}"
            ) from error


class AirzoneHotWaterEntity(AirzoneEntity):
    """Représentation du module Eau Chaude Sanitaire (DHW) Airzone."""

    def __init__(
        self,
        coordinator: AirzoneMqttCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_dhw")},
            manufacturer=MANUFACTURER,
            model="DHW",
            name=self.get_airzone_value(AZD_NAME) or "Eau Chaude",
        )
        if AZD_WEBSERVER in self.coordinator.data:
            self._attr_device_info["via_device"] = (DOMAIN, f"{entry.entry_id}_ws")
        self._attr_unique_id = entry.unique_id or entry.entry_id

    def get_airzone_value(self, key: str) -> Any:
        """Retourne la valeur DHW par sa clé."""
        return self.coordinator.data.get(AZD_HOT_WATER, {}).get(key)

    async def _async_update_dhw_params(self, params: dict[str, Any]) -> None:
        """Envoie les paramètres DHW via l'API RPC MQTT."""
        _LOGGER.debug("update_dhw_params=%s", params)
        try:
            rpc_params = {
                "system_id": 0, # ECS est généralement sur le système 0
                "device_set_status": params
            }
            await self.coordinator.async_send_rpc("AzAcsSetStatus", rpc_params)
        except Exception as error:
            raise HomeAssistantError(f"Échec de la commande DHW: {error}") from error


class AirzoneWebServerEntity(AirzoneEntity):
    """Représentation de la passerelle WebServer/Aidoo."""

    def __init__(
        self,
        coordinator: AirzoneMqttCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator)

        mac = self.get_airzone_value(AZD_MAC) or coordinator.topic_prefix

        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_NETWORK_MAC, mac.upper())},
            identifiers={(DOMAIN, f"{entry.entry_id}_ws")},
            manufacturer=MANUFACTURER,
            model=self.get_airzone_value(AZD_MODEL) or "Webserver (MQTT)",
            name=self.get_airzone_value(AZD_FULL_NAME) or f"Airzone {mac}",
            sw_version=self.get_airzone_value(AZD_FIRMWARE),
        )
        self._attr_unique_id = entry.unique_id or entry.entry_id

    def get_airzone_value(self, key: str) -> Any:
        """Retourne la valeur du webserver par clé."""
        return self.coordinator.data.get(AZD_WEBSERVER, {}).get(key)


class AirzoneZoneEntity(AirzoneEntity):
    """Représentation d'une Zone (Thermostat) Airzone."""

    def __init__(
        self,
        coordinator: AirzoneMqttCoordinator,
        entry: ConfigEntry,
        system_zone_id: str,
        zone_data: dict[str, Any],
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator)

        self.system_id = zone_data.get(AZD_SYSTEM)
        self.system_zone_id = system_zone_id
        self.zone_id = zone_data.get(AZD_ID)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{system_zone_id}")},
            manufacturer=MANUFACTURER,
            model=self.get_airzone_value(AZD_THERMOSTAT_MODEL),
            name=zone_data.get(AZD_NAME, f"Zone {self.zone_id}"),
            sw_version=self.get_airzone_value(AZD_THERMOSTAT_FW),
            via_device=(DOMAIN, f"{entry.entry_id}_{self.system_id}"),
        )
        self._attr_unique_id = entry.unique_id or entry.entry_id

    @property
    def available(self) -> bool:
        """Retourne la disponibilité de la zone."""
        return super().available and self.get_airzone_value(AZD_AVAILABLE) is not False

    def get_airzone_value(self, key: str) -> Any:
        """Retourne la valeur de la zone par clé."""
        value = None
        if zone := self.coordinator.data.get(AZD_ZONES, {}).get(self.system_zone_id):
            if key in zone:
                value = zone[key]
        return value

    async def _async_update_hvac_params(self, params: dict[str, Any]) -> None:
        """Envoie les paramètres CVC de la zone via l'API RPC MQTT."""
        _LOGGER.debug("update_hvac_params=%s", params)
        try:
            # Format RPC attendu pour une zone
            rpc_params = {
                "system_id": self.system_id,
                "zone_id": self.zone_id,
                "device_set_status": params
            }
            await self.coordinator.async_send_rpc("AzZoneSetStatus", rpc_params)
        except Exception as error:
            raise HomeAssistantError(
                f"Échec de la commande de zone {self.entity_id}: {error}"
            ) from error