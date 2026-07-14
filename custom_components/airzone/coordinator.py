"""Coordinator for the Airzone MQTT integration."""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# --- Structure interne exposée aux entités ---
AZD_SYSTEMS = "systems"
AZD_ZONES = "zones"
AZD_WEBSERVER = "webserver"

# --- Protocole MQTT Airzone (cf. lib Noltari/airzone-mqtt) ---
AMT_V1 = "v1"
AMT_INVOKE = "invoke"
AMT_RESPONSE = "response"
AMT_EVENTS = "events"
AMT_ONLINE = "online"
AMT_STATUS = "status"
AMT_REQUEST = "request"

API_AZ_GET_STATUS = "az.get_status"
API_AZ_SYSTEM = "az_system"
API_AZ_ZONE = "az_zone"

API_HEADERS = "headers"
API_BODY = "body"
API_CMD = "cmd"
API_DESTINATION = "destination"
API_REQ_ID = "req_id"
API_DEVICES = "devices"
API_DEVICE_ID = "device_id"
API_DEVICE_TYPE = "device_type"
API_SYSTEM_ID = "system_id"
API_META = "meta"
API_PARAMETERS = "parameters"
API_UNITS = "units"
API_IS_CONNECTED = "is_connected"
API_RANGE_SP = "range_sp"
API_MIN = "min"
API_MAX = "max"
API_ONLINE = "online"

# Délai d'attente de la réponse à l'invoke initial (secondes).
POLL_TIMEOUT = 10

type AirzoneConfigEntry = ConfigEntry["AirzoneMqttCoordinator"]


class AirzoneMqttCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Gère la réception et l'envoi de données Airzone via MQTT."""

    def __init__(
        self, hass: HomeAssistant, entry: AirzoneConfigEntry, topic_prefix: str
    ) -> None:
        """Initialisation du coordinateur."""
        self.topic_prefix = topic_prefix
        self.mqtt_prefix = f"{topic_prefix}/{AMT_V1}"
        self._unsub_listeners: list = []
        self.online: bool = False

        # Évènement + req_id pour corréler l'invoke initial et sa réponse.
        self._resp_event = asyncio.Event()
        self._req_id: str = ""

        # Structure attendue par les entités.
        self._data: dict[str, Any] = {
            AZD_WEBSERVER: {"mac": topic_prefix},
            AZD_SYSTEMS: {},
            AZD_ZONES: {},
        }

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{topic_prefix}",
            # Push : pas de polling périodique, on met à jour à chaque évènement MQTT.
            update_interval=None,
        )

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    async def async_init(self) -> None:
        """S'abonne aux topics MQTT puis récupère l'état initial des devices."""

        @callback
        def message_received(msg) -> None:
            self._async_process_mqtt_message(msg.topic, msg.payload)

        for suffix in (AMT_ONLINE, f"{AMT_RESPONSE}/#", f"{AMT_EVENTS}/#"):
            topic = f"{self.mqtt_prefix}/{suffix}"
            unsub = await mqtt.async_subscribe(self.hass, topic, message_received, qos=0)
            self._unsub_listeners.append(unsub)

        # Récupération initiale de la liste des devices (systèmes + zones).
        await self.async_request_status()

        self.async_set_updated_data(self._data)

    async def async_unload(self) -> None:
        """Désabonne proprement des topics MQTT."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    # ------------------------------------------------------------------
    # Requête d'init : az.get_status (récupération des devices)
    # ------------------------------------------------------------------
    def _new_req_id(self) -> str:
        """Génère un identifiant de requête unique."""
        now = datetime.now(tz=timezone.utc)
        stamp = (
            f"{now.year}/{now.month}/{now.day}-"
            f"{now.hour}:{now.minute}:{now.second}.{now.microsecond}"
        )
        return f"{AMT_REQUEST}-{stamp}-{self._safe(API_AZ_GET_STATUS)}"

    @staticmethod
    def _safe(topic: str) -> str:
        """Rend une chaîne utilisable dans un topic (pas de point)."""
        return topic.replace(".", "_")

    async def async_request_status(self) -> None:
        """Envoie l'invoke `az.get_status` et attend la réponse (devices)."""
        self._req_id = self._new_req_id()
        destination = f"{self.mqtt_prefix}/{AMT_RESPONSE}/{self._safe(API_AZ_GET_STATUS)}"

        payload = {
            API_HEADERS: {
                API_CMD: API_AZ_GET_STATUS,
                API_DESTINATION: destination,
                API_REQ_ID: self._req_id,
            },
            API_BODY: None,
        }

        self._resp_event.clear()
        await mqtt.async_publish(
            self.hass, f"{self.mqtt_prefix}/{AMT_INVOKE}", json.dumps(payload), qos=0
        )

        try:
            async with asyncio.timeout(POLL_TIMEOUT):
                await self._resp_event.wait()
        except TimeoutError:
            _LOGGER.warning(
                "Airzone MQTT: pas de réponse à az.get_status sur %s "
                "(les devices apparaîtront à la réception d'évènements)",
                self.mqtt_prefix,
            )

    # ------------------------------------------------------------------
    # Réception / parsing
    # ------------------------------------------------------------------
    @callback
    def _async_process_mqtt_message(self, topic: str, payload: Any) -> None:
        """Route un message MQTT entrant vers le bon handler."""
        rel = topic.removeprefix(f"{self.mqtt_prefix}/").split("/")
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.error("Airzone MQTT: JSON invalide sur %s: %s", topic, payload)
            return

        head = rel[0] if rel else ""
        if head == AMT_ONLINE:
            self.online = bool(data.get(API_ONLINE, False))
            self._data[AZD_WEBSERVER][API_ONLINE] = self.online
        elif head == AMT_RESPONSE:
            self._handle_response(rel, data)
        elif head == AMT_EVENTS:
            self._handle_event(rel, data)

    def _handle_response(self, rel: list[str], data: dict[str, Any]) -> None:
        """Traite une réponse à un invoke (dont az.get_status)."""
        req_id = data.get(API_HEADERS, {}).get(API_REQ_ID)
        if req_id == self._req_id:
            self._resp_event.set()

        # rel = ["response", "az_get_status", ...]
        if len(rel) >= 2 and rel[1] == self._safe(API_AZ_GET_STATUS):
            body = data.get(API_BODY) or {}
            devices = body.get(API_DEVICES, [])
            for device in devices:
                self._upsert_device(device)
            self.async_set_updated_data(self._data)

    def _handle_event(self, rel: list[str], data: dict[str, Any]) -> None:
        """Traite un évènement push (mise à jour partielle d'un device)."""
        # rel = ["events", "status", ...]
        if len(rel) >= 2 and rel[1] == AMT_STATUS:
            body = data.get(API_BODY) or {}
            if body.get(API_DEVICE_TYPE):
                self._upsert_device(body)
                self.async_set_updated_data(self._data)

    def _upsert_device(self, device: dict[str, Any]) -> None:
        """Insère ou met à jour un device (système ou zone) dans _data."""
        dev_type = device.get(API_DEVICE_TYPE)
        device_id = device.get(API_DEVICE_ID)
        system_id = device.get(API_SYSTEM_ID)
        if device_id is None or system_id is None:
            return

        key = f"{system_id}:{device_id}"
        target = AZD_SYSTEMS if dev_type == API_AZ_SYSTEM else AZD_ZONES
        if dev_type not in (API_AZ_SYSTEM, API_AZ_ZONE):
            _LOGGER.warning("Airzone MQTT: device inconnu %s", device)
            return

        entry = self._data[target].setdefault(key, {})
        entry.update(self._flatten(device))
        entry.setdefault("zone_id", device_id)

    @staticmethod
    def _flatten(device: dict[str, Any]) -> dict[str, Any]:
        """Aplati meta + parameters d'un device en un dict plat pour les entités."""
        meta = device.get(API_META, {}) or {}
        params = device.get(API_PARAMETERS, {}) or {}

        flat: dict[str, Any] = {
            API_DEVICE_ID: device.get(API_DEVICE_ID),
            API_SYSTEM_ID: device.get(API_SYSTEM_ID),
            API_DEVICE_TYPE: device.get(API_DEVICE_TYPE),
        }
        if API_UNITS in meta:
            flat[API_UNITS] = meta[API_UNITS]

        flat.update(params)

        # Disponibilité (is_connected -> available attendu par les entités).
        if API_IS_CONNECTED in params:
            flat["available"] = bool(params[API_IS_CONNECTED])

        # range_sp {min,max} -> min_temp / max_temp attendus par climate.
        range_sp = params.get(API_RANGE_SP)
        if isinstance(range_sp, dict):
            if API_MIN in range_sp:
                flat["min_temp"] = range_sp[API_MIN]
            if API_MAX in range_sp:
                flat["max_temp"] = range_sp[API_MAX]

        return flat

    # ------------------------------------------------------------------
    # Envoi de commandes
    # ------------------------------------------------------------------
    async def async_send_rpc(self, command: str, params: dict[str, Any]) -> None:
        """Envoie une commande (invoke) MQTT vers l'équipement Airzone."""
        req_id = f"{AMT_REQUEST}-{self._new_req_id()}"
        payload = {
            API_HEADERS: {
                API_CMD: command,
                API_DESTINATION: f"{self.mqtt_prefix}/{AMT_RESPONSE}/{self._safe(command)}",
                API_REQ_ID: req_id,
            },
            API_BODY: params,
        }
        await mqtt.async_publish(
            self.hass, f"{self.mqtt_prefix}/{AMT_INVOKE}", json.dumps(payload), qos=0
        )
