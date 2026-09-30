import json
import sys
import time
from datetime import date
from pathlib import Path

import pytest
from PIL import ImageOps

sys.path.insert(0, str(Path(__file__).parents[1] / "label_studio"))
import label_renderer
import mqtt_bridge


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app as module
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(module, "SETTINGS_FILE", tmp_path / "settings.json")
    printed = []
    monkeypatch.setattr(module, "make_printer", lambda settings: type("P", (), {"print_image": lambda self, image, copies, rotate: printed.append((image, copies, rotate))})())
    module.printed = printed
    return module


def test_dates_are_formatted_and_today_is_resolved_at_print_time():
    assert label_renderer.format_date("2026-09-29", "%d-%m-%Y") == "29-09-2026"
    assert label_renderer.format_date("today", "%Y-%m-%d") == date.today().isoformat()
    assert label_renderer.format_date(True) == date.today().strftime(label_renderer.DEFAULT_DATE_FORMAT)
    assert label_renderer.format_date("") is None
    assert label_renderer.format_date("best before summer") == "best before summer"


def test_template_print_applies_overrides(app_module):
    client = app_module.app.test_client()
    client.post("/api/templates", json={"name": "Opened", "text": "Opened", "date": "today", "copies": "1"})
    response = client.post("/api/templates/Opened/print", json={"copies": 2})
    assert response.json == {"ok": True, "message": "Printed Opened"}
    assert app_module.printed[-1][1] == 2


def test_unknown_template_is_an_error(app_module):
    response = app_module.app.test_client().post("/api/print", json={"template": "missing"})
    assert response.status_code == 500
    assert "Unknown template" in response.json["message"]


def test_settings_api_hides_mqtt_credentials(app_module, tmp_path):
    (tmp_path / "options.json").write_text(json.dumps({"mqtt_host": "broker", "mqtt_password": "secret"}))
    settings = app_module.app.test_client().get("/api/settings").json
    assert "mqtt_password" not in settings and settings["backend"] == "direct"


class FakeClient:
    def __init__(self):
        self.published = {}

    def publish(self, topic, payload, retain=False):
        self.published[topic] = payload

    def subscribe(self, topics):
        self.subscribed = topics


class Message:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


class ReasonCode:
    is_failure = False


def _bridge(templates, printed):
    bridge = mqtt_bridge.MqttBridge("broker", 1883, None, None, lambda: templates, lambda request: printed.append(request) or "Printed")
    bridge.client = FakeClient()
    bridge._on_connect(bridge.client, None, None, ReasonCode(), None)
    return bridge


def test_bridge_publishes_a_button_per_template_and_prints_on_press():
    printed = []
    bridge = _bridge([{"name": "Opened today", "icon": "mdi:fridge"}], printed)
    config = json.loads(bridge.client.published["homeassistant/button/dymo_labels_template_opened_today/config"])
    assert config["name"] == "Print Opened today"
    assert config["icon"] == "mdi:fridge"
    assert bridge.client.published["dymo_labels/status"] == "online"

    bridge._on_message(bridge.client, None, Message(config["command_topic"], b"PRESS"))
    for _ in range(50):
        if printed:
            break
        time.sleep(0.01)
    assert printed == [{"template": "Opened today"}]


def test_bridge_removes_buttons_of_deleted_templates():
    templates = [{"name": "A"}, {"name": "B"}]
    bridge = _bridge(templates, [])
    templates.pop()
    bridge.publish_templates()
    assert bridge.client.published["homeassistant/button/dymo_labels_template_b/config"] == ""
    # A retained button left over from an earlier run is removed as well.
    bridge._on_message(bridge.client, None, Message("homeassistant/button/dymo_labels_template_old/config", b"{}"))
    assert bridge.client.published["homeassistant/button/dymo_labels_template_old/config"] == ""


def test_web_app_only_answers_home_assistant_in_the_add_on(app_module, monkeypatch):
    monkeypatch.setattr(app_module.ha, "supervisor_token", lambda: "token")
    client = app_module.app.test_client()
    assert client.get("/api/status", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 403
    assert client.get("/api/status", environ_base={"REMOTE_ADDR": "172.30.32.2"}).status_code == 200


def test_settings_keep_valid_favourites_and_default(app_module):
    client = app_module.app.test_client()
    client.post("/api/settings", json={"backend": "direct", "favorite_labels": ["99010", "bogus"], "default_label": "11354"})
    settings = client.get("/api/settings").json
    assert settings["favorite_labels"] == ["99010"] and settings["default_label"] == "99010"


def test_print_corrections_move_the_printed_label_only(app_module):
    client = app_module.app.test_client()
    client.post("/api/settings", json={"backend": "direct", "favorite_labels": ["11354"],
                                       "label_offsets": {"11354": {"x": 0, "y": -2}, "99010": {"y": 3}, "bogus": {"y": 1}}})
    settings = client.get("/api/settings").json
    # Only non-zero corrections of known labels are kept, rounded and limited.
    assert settings["label_offsets"] == {"11354": {"y": -2.0}, "99010": {"y": 3.0}}

    body = {"text": "", "graphic": "qr", "qr": "x", "label_size": "11354"}
    client.post("/api/print", json=body)
    printed = app_module.printed[-1][0]
    preview = app_module.render_request(body)
    shift = label_renderer.mm(2)
    # The printed QR code sits 2 mm higher than in the preview.
    inverted = lambda image: ImageOps.invert(image.convert("L"))
    assert inverted(printed).getbbox()[1] == inverted(preview).getbbox()[1] - shift


def test_network_printer_is_off_by_default_and_never_shared_through_cups(app_module, tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text(json.dumps({"print_server": True, "backend": "direct"}))
    assert app_module.app.test_client().get("/api/settings").json["print_server"] is False
    started = []
    monkeypatch.setattr(app_module.network_printer, "start", lambda *args: started.append(args))
    client = app_module.app.test_client()
    client.post("/api/settings", json={"backend": "cups", "print_server": True, "favorite_labels": ["11354"]})
    assert client.get("/api/settings").json["print_server"] is False
    for _ in range(20):
        time.sleep(0.01)
    assert started == []
    client.post("/api/settings", json={"backend": "direct", "print_server": True, "favorite_labels": ["11354"]})
    for _ in range(50):
        if started:
            break
        time.sleep(0.01)
    assert started and started[0][1] == ["11354"]
