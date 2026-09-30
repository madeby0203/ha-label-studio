from __future__ import annotations

from io import BytesIO
from ipaddress import ip_address, ip_network
import json
import logging
import os
from pathlib import Path
import subprocess
import threading

from flask import Flask, abort, jsonify, render_template, request, send_file

import ha
import print_server
from label_renderer import DATE_FORMATS, shift_image, DEFAULT_FAVORITES, DEFAULT_LANGUAGE, DEFAULT_LABEL_SIZE, GAP_MM, MARGIN_MM, HYPHENATION_LANGUAGES, LABEL_SIZES, available_fonts, find_font_file, home_icons, mdi_icons, render_request
from mqtt_bridge import MqttBridge
from printer import CupsPrinter, PrinterError, make_printer


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
TEMPLATES_FILE = DATA_DIR / "templates.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
# On the host network the web app is reachable from the LAN; only allow Home Assistant's
# ingress proxy (the Supervisor, on the internal hassio network) and the add-on itself.
TRUSTED_NETWORKS = (ip_network("127.0.0.0/8"), ip_network("::1/128"), ip_network("172.30.32.0/23"))
# Add-on configuration options that seed the printer settings of the web UI.
PRINTER_OPTIONS = ("backend", "device", "cups_printer", "fallback_cups")
# Largest print position correction per label, in mm.
MAX_OFFSET_MM = 10.0
app = Flask(__name__)
log = logging.getLogger("dymo_labels")
bridge: MqttBridge | None = None
network_printer = print_server.PrintServer()
_print_lock = threading.Lock()


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def _settings() -> dict:
    settings = {
        "backend": "direct",
        "device": "/dev/usb/lp0",
        "cups_printer": "DYMO",
        "fallback_cups": False,
        "favorite_labels": list(DEFAULT_FAVORITES),
        "default_label": DEFAULT_LABEL_SIZE,
        # Per label: {"x": mm, "y": mm} to correct where the printer puts the print.
        "label_offsets": {},
        "print_server": False,
    }
    options = _load(DATA_DIR / "options.json", {})
    settings.update({key: options[key] for key in PRINTER_OPTIONS if key in options})
    settings.update(_load(SETTINGS_FILE, {}))
    return settings


def _update_network_printer(settings: dict) -> None:
    """Start or stop sharing the printer to match the settings.

    Sharing is off when printing goes through CUPS: then the add-on is a CUPS client, not a server.
    """
    wanted = bool(settings.get("print_server")) and settings.get("backend") != "cups"
    if wanted and not network_printer.running:
        # Starting takes a few seconds; the web UI shows progress through the status.
        threading.Thread(
            target=network_printer.start,
            args=(settings.get("device") or "/dev/usb/lp0", settings["favorite_labels"], settings["default_label"]),
            daemon=True,
        ).start()
    elif not wanted and (network_printer.running or network_printer.status.get("enabled")):
        network_printer.stop()
    elif wanted and not network_printer.status.get("starting"):
        # Network clients only see the favourite label sizes.
        print_server.apply_label_sizes(settings["favorite_labels"], settings["default_label"])


def _templates() -> list[dict]:
    return _load(TEMPLATES_FILE, [])


def _templates_changed() -> None:
    if bridge:
        bridge.publish_templates()


def print_request(payload: dict) -> str:
    """Print a label request, optionally based on a saved template, and describe the result."""
    name = payload.get("template")
    if name:
        template = next((t for t in _templates() if t.get("name") == name), None)
        if template is None:
            raise ValueError(f"Unknown template: {name}")
        # Fields sent along with the template name override the saved ones.
        payload = {**template, **{key: value for key, value in payload.items() if key != "template"}}
    image = render_request(ha.resolve_templates(payload))
    settings = _settings()
    copies = int(payload.get("copies") or 1)
    label_size = payload.get("label_size") or DEFAULT_LABEL_SIZE
    rotate = LABEL_SIZES[label_size].feeds_along_width
    # Correct for where this printer puts this label type; the preview stays as designed.
    offset = settings["label_offsets"].get(label_size) or {}
    image = shift_image(image, offset.get("x", 0), offset.get("y", 0))
    with _print_lock:
        try:
            make_printer(settings).print_image(image, copies, rotate)
        except PrinterError:
            if settings.get("backend", "direct") != "direct" or not settings.get("fallback_cups", False):
                raise
            CupsPrinter(settings.get("cups_printer", "DYMO")).print_image(image, copies, rotate)
    return f"Printed {name}" if name else "Label sent to printer"


@app.before_request
def only_through_home_assistant():
    # Outside the add-on (local development) there is no ingress to go through.
    if not ha.supervisor_token():
        return None
    try:
        address = ip_address(request.remote_addr or "")
    except ValueError:
        abort(403)
    if not any(address in network for network in TRUSTED_NETWORKS):
        abort(403)
    return None


@app.get("/")
def index():
    return render_template(
        "index.html",
        sizes=[{"id": size.id, "name": size.name} for size in sorted(LABEL_SIZES.values(), key=lambda size: size.id)],
        fonts=available_fonts(),
        date_formats=DATE_FORMATS,
        languages=HYPHENATION_LANGUAGES,
        default_language=DEFAULT_LANGUAGE,
        margin=MARGIN_MM,
        gap=GAP_MM,
    )


@app.get("/api/status")
def status():
    return jsonify(
        mqtt=bridge is not None,
        mqtt_connected=bool(bridge and bridge.connected),
        print_server=network_printer.status,
    )


@app.get("/api/icons")
def icons():
    return jsonify(all=mdi_icons(), home=home_icons())


@app.get("/mdi-font")
def mdi_font():
    """The icon webfont, so the picker shows the same glyphs that get printed."""
    for name, mimetype in (("materialdesignicons-webfont.woff2", "font/woff2"), ("materialdesignicons-webfont.ttf", "font/ttf")):
        path = find_font_file(name)
        if path:
            return send_file(path, mimetype=mimetype, max_age=86400)
    abort(404)


# Web fonts for the interface; Home Assistant's own font files are not reachable from the page.
WEB_FONTS = {"roboto-400": "Roboto-Regular.ttf", "roboto-500": "Roboto-Medium.ttf", "roboto-700": "Roboto-Bold.ttf"}


@app.get("/webfont/<name>")
def web_font(name: str):
    path = find_font_file(WEB_FONTS[name]) if name in WEB_FONTS else None
    if not path:
        abort(404)
    return send_file(path, mimetype="font/ttf", max_age=86400)


@app.post("/api/preview")
def preview():
    try:
        image = render_request(ha.resolve_templates(request.get_json(silent=True) or {}))
    except ValueError as exc:
        return jsonify(ok=False, message=str(exc)), 400
    buffer = BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


@app.route("/api/templates", methods=["GET", "POST"])
def templates():
    saved = _templates()
    if request.method == "POST":
        item = request.get_json(silent=True) or {}
        if not str(item.get("name") or "").strip():
            return jsonify(ok=False, message="A template needs a name"), 400
        saved = [old for old in saved if old.get("name") != item.get("name")]
        saved.append(item)
        _save(TEMPLATES_FILE, saved)
        _templates_changed()
    return jsonify(saved)


@app.delete("/api/templates/<name>")
def delete_template(name: str):
    saved = [item for item in _templates() if item.get("name") != name]
    _save(TEMPLATES_FILE, saved)
    _templates_changed()
    return jsonify(saved)


@app.post("/api/templates/<name>/print")
def print_template(name: str):
    return _print_response({**(request.get_json(silent=True) or {}), "template": name})


@app.post("/api/print")
def print_label():
    return _print_response(request.get_json(silent=True) or {})


def _print_response(payload: dict):
    try:
        return jsonify(ok=True, message=print_request(payload))
    except (PrinterError, ValueError, TypeError) as exc:
        return jsonify(ok=False, message=str(exc)), 500


@app.get("/api/settings")
def settings():
    return jsonify(_settings())


@app.post("/api/settings")
def save_settings():
    value = request.get_json(silent=True) or {}
    favorites = [label for label in value.get("favorite_labels") or [] if label in LABEL_SIZES]
    value["favorite_labels"] = favorites or [DEFAULT_LABEL_SIZE]
    if value.get("default_label") not in value["favorite_labels"]:
        value["default_label"] = value["favorite_labels"][0]
    value["label_offsets"] = _clean_offsets(value.get("label_offsets"))
    value["print_server"] = bool(value.get("print_server")) and value.get("backend") != "cups"
    _save(SETTINGS_FILE, value)
    try:
        _update_network_printer(_settings())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        log.error("Could not update the network printer: %s", exc)
        return jsonify(ok=True, message="Saved, but the network printer could not be updated; see the add-on log")
    return jsonify(ok=True)


def _clean_offsets(offsets) -> dict:
    """Keep non-zero corrections for known labels, limited to a sensible range."""
    cleaned = {}
    for label, offset in (offsets or {}).items() if isinstance(offsets, dict) else ():
        if label not in LABEL_SIZES or not isinstance(offset, dict):
            continue
        values = {}
        for axis in ("x", "y"):
            try:
                amount = round(max(-MAX_OFFSET_MM, min(MAX_OFFSET_MM, float(offset.get(axis) or 0))), 1)
            except (TypeError, ValueError):
                amount = 0
            if amount:
                values[axis] = amount
        if values:
            cleaned[label] = values
    return cleaned


def _start_mqtt() -> MqttBridge | None:
    options = _load(DATA_DIR / "options.json", {})
    host = options.get("mqtt_host")
    port = options.get("mqtt_port") or 1883
    username, password = options.get("mqtt_username"), options.get("mqtt_password")
    if not host:
        service = ha.mqtt_service()
        if not service:
            log.info("No MQTT broker configured; Home Assistant buttons are disabled")
            return None
        host, port = service["host"], service["port"]
        username, password = service.get("username"), service.get("password")
    mqtt_bridge = MqttBridge(host, int(port), username, password, _templates, print_request)
    mqtt_bridge.start()
    return mqtt_bridge


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bridge = _start_mqtt()
    _update_network_printer(_settings())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8099")))