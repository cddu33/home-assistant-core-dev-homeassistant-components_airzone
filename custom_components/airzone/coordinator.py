"""Coordinator for the Airzone MQTT integration."""

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Clés historiquement utilisées par la bibliothèque HTTP (aioairzone).
# On les redéfinit ici en dur pour que tes entités continuent de trouver leurs données.
AZD_SYSTEMS = "systems"
AZD_ZONES = "zones"
AZD_WEBSERVER = "webserver"

type AirzoneConfigEntry = ConfigEntry["AirzoneMqttCoordinator"]

class AirzoneMqttCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Classe gérant la réception et l'envoi de données Airzone via MQTT."""

    def __init__(self, hass: HomeAssistant, entry: AirzoneConfigEntry, topic_prefix: str) -> None:
        """Initialisation du coordinateur."""
        self.topic_prefix = topic_prefix
        self._unsub_listeners = []
        
        # On initialise la structure de base attendue par tes entités
        self._data = {
            AZD_WEBSERVER: {"mac": topic_prefix},
            AZD_SYSTEMS: {},
            AZD_ZONES: {}
        }

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{topic_prefix}",
            # Le secret est ici : update_interval=None désactive le polling de Home Assistant.
            # Nous mettrons à jour les données manuellement à chaque message MQTT reçu.
            update_interval=None,
        )

    async def async_init(self) -> None:
        """S'abonne aux topics MQTT."""
        
        @callback
        def message_received(msg):
            """Gère les messages entrants poussés par Airzone."""
            self._async_process_mqtt_message(msg)

        # Abonnement aux événements de changement d'état (Push)
        topic_status = f"{self.topic_prefix}/v1/receive/device_status"
        unsub_status = await mqtt.async_subscribe(self.hass, topic_status, message_received, qos=1)
        self._unsub_listeners.append(unsub_status)
        
        # Optionnel pour plus tard : Publier une requête RPC initiale
        # pour forcer le Webserver à envoyer l'état de toutes les zones
        # au moment du démarrage de Home Assistant.

        self.async_set_updated_data(self._data)

    @callback
    def _async_process_mqtt_message(self, msg) -> None:
        """Traite le payload JSON et met à jour le dictionnaire interne."""
        try:
            payload = json.loads(msg.payload)
            
            # Format attendu selon la documentation API MQTT Airzone
            if "device_state" in payload:
                state = payload["device_state"]
                
                sys_id = state.get("system_id")
                zone_id = state.get("zone_id")
                
                if sys_id is not None and zone_id is not None:
                    sys_zone_id = f"{sys_id}_{zone_id}"
                    
                    # Création de l'arborescence si elle n'existe pas encore
                    if sys_zone_id not in self._data[AZD_ZONES]:
                        self._data[AZD_ZONES][sys_zone_id] = {}
                    if str(sys_id) not in self._data[AZD_SYSTEMS]:
                        self._data[AZD_SYSTEMS][str(sys_id)] = {}

                    # On fusionne les nouvelles données reçues avec les anciennes
                    self._data[AZD_ZONES][sys_zone_id].update(state)
                    
                    # Notifie Home Assistant que les données ont changé !
                    # Cela va déclencher le _handle_coordinator_update de tes entités.
                    self.async_set_updated_data(self._data)
                    
        except json.JSONDecodeError:
            _LOGGER.error("Impossible de parser le JSON MQTT: %s", msg.payload)
        except Exception as err:
            _LOGGER.error("Erreur lors de la mise à jour MQTT: %s", err)

    async def async_send_rpc(self, command: str, params: dict[str, Any]) -> None:
        """Envoie une commande RPC MQTT vers l'équipement Airzone."""
        topic_req = f"{self.topic_prefix}/v1/rpc/request"
        
        # Structure stricte de la requête RPC
        payload = {
            "origin": "HomeAssistant",
            "destination": f"client/{self.topic_prefix}",
            "req_id": "ha_req_1",
            "cmd": command,
            "params": params
        }
        
        await mqtt.async_publish(self.hass, topic_req, json.dumps(payload), qos=1)

    async def async_unload(self) -> None:
        """Désabonne proprement des topics MQTT lors de la suppression de l'intégration."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()