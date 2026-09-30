"""Expose label templates to Home Assistant as MQTT discovery buttons."""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Callable

import paho.mqtt.client as mqtt


log = logging.getLogger(__name__)

TOPIC = "dymo_labels"
AVAILABILITY_TOPIC = f"{TOPIC}/status"
LAST_PRINT_TOPIC = f"{TOPIC}/last_print"
PRINT_TOPIC = f"{TOPIC}/print"
DISCOVERY_PREFIX = "homeassistant"
BUTTON_PREFIX = "dymo_labels_template_"
DEVICE = {
    "identifiers": ["dymo_labels"],
    "name": "Label Studio",
    "manufacturer": "Label Studio",
    "model": "DYMO LabelWriter",
}


def template_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "template"


class MqttBridge:
    """Publishes one button per template and prints when Home Assistant presses one.

    Anything can also be printed by publishing a label request as JSON to
    ``dymo_labels/print``, e.g. ``{"template": "Opened"}`` or
    ``{"text": "Milk", "icon": "mdi:fridge"}``.
    """

    def __init__(self, host: str, port: int, username: str | None, password: str | None,
                 load_templates: Callable[[], list[dict]], print_label: Callable[[dict], str]) -> None:
        self.host, self.port = host, port
        self.load_templates = load_templates
        self.print_label = print_label
        self.connected = False
        self._buttons: dict[str, str] = {}
        self._lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dymo-labels")
        if username:
            self.client.username_pw_set(username, password or None)
        self.client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        log.info("Connecting to MQTT broker %s:%s", self.host, self.port)
        self.client.connect_async(self.host, self.port)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("Connected to MQTT broker")
        self.connected = True
        client.subscribe([
            (f"{TOPIC}/template/+/press", 0),
            (PRINT_TOPIC, 0),
            # Retained discovery messages reveal buttons of templates deleted while we were offline.
            (f"{DISCOVERY_PREFIX}/button/+/config", 0),
        ])
        client.publish(f"{DISCOVERY_PREFIX}/sensor/dymo_labels_last_print/config", json.dumps({
            "name": "Last print",
            "unique_id": "dymo_labels_last_print",
            "state_topic": LAST_PRINT_TOPIC,
            "availability_topic": AVAILABILITY_TOPIC,
            "icon": "mdi:printer",
            "device": DEVICE,
        }), retain=True)
        self.publish_templates()
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self.connected = False
        log.warning("Disconnected from MQTT broker: %s", reason_code)

    def publish_templates(self) -> None:
        """Create a button for every template and remove buttons of deleted ones."""
        if not self.connected:
            return
        buttons = {template_slug(t["name"]): t for t in self.load_templates() if t.get("name")}
        with self._lock:
            stale = set(self._buttons) - set(buttons)
            self._buttons = {slug: t["name"] for slug, t in buttons.items()}
        for slug in stale:
            self._remove_button(slug)
        for slug, template in buttons.items():
            icon = template.get("icon") or ""
            self.client.publish(self._config_topic(slug), json.dumps({
                "name": f"Print {template['name']}",
                "unique_id": BUTTON_PREFIX + slug,
                "command_topic": f"{TOPIC}/template/{slug}/press",
                "availability_topic": AVAILABILITY_TOPIC,
                "icon": icon if icon.startswith("mdi:") else "mdi:printer",
                "device": DEVICE,
            }), retain=True)

    def _config_topic(self, slug: str) -> str:
        return f"{DISCOVERY_PREFIX}/button/{BUTTON_PREFIX}{slug}/config"

    def _remove_button(self, slug: str) -> None:
        self.client.publish(self._config_topic(slug), "", retain=True)

    def _on_message(self, client, userdata, message) -> None:
        topic = message.topic
        if topic.startswith(f"{DISCOVERY_PREFIX}/button/"):
            object_id = topic.split("/")[2]
            slug = object_id[len(BUTTON_PREFIX):]
            with self._lock:
                known = slug in self._buttons
            if object_id.startswith(BUTTON_PREFIX) and message.payload and not known:
                self._remove_button(slug)
            return
        if topic == PRINT_TOPIC:
            try:
                request = json.loads(message.payload or b"{}")
                if not isinstance(request, dict):
                    raise ValueError("expected a JSON object")
            except ValueError as exc:
                self._report(f"Invalid print request: {exc}")
                return
        else:
            with self._lock:
                name = self._buttons.get(topic.split("/")[2])
            if name is None:
                return
            request = {"template": name}
        # Printing can take a while; keep the MQTT network loop responsive.
        threading.Thread(target=self._print, args=(request,), daemon=True).start()

    def _print(self, request: dict) -> None:
        try:
            self._report(self.print_label(request))
        except Exception as exc:  # reported to Home Assistant rather than lost in a thread
            log.exception("Print from Home Assistant failed")
            self._report(f"Failed: {exc}")

    def _report(self, message: str) -> None:
        self.client.publish(LAST_PRINT_TOPIC, message[:255], retain=True)
