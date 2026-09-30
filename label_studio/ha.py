"""Access to Home Assistant through the Supervisor, available when running as an add-on."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPERVISOR_URL = "http://supervisor"
# s6-overlay keeps the container environment here when a process does not inherit it.
S6_ENVIRONMENT = Path("/run/s6/container_environment")
# Label fields that may contain Home Assistant templates such as {{ states('sensor.x') }}.
TEMPLATE_FIELDS = ("text", "qr")


def supervisor_token() -> str | None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        return token
    try:
        return (S6_ENVIRONMENT / "SUPERVISOR_TOKEN").read_text().strip() or None
    except OSError:
        return None


def _request(path: str, body: dict | None = None) -> bytes:
    token = supervisor_token()
    if not token:
        raise ValueError("Home Assistant is not reachable outside the add-on")
    request = Request(
        SUPERVISOR_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip()
        raise ValueError(detail[:300] or f"Home Assistant returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach Home Assistant: {exc.reason}") from exc


def has_template(value) -> bool:
    return isinstance(value, str) and ("{{" in value or "{%" in value)


def render_template(template: str) -> str:
    try:
        return _request("/core/api/template", {"template": template}).decode()
    except ValueError as exc:
        raise ValueError(f"Template error: {exc}") from exc


def resolve_templates(payload: dict) -> dict:
    """Return a copy of a label request with Home Assistant templates filled in."""
    resolved = dict(payload)
    for field in TEMPLATE_FIELDS:
        if has_template(resolved.get(field)):
            resolved[field] = render_template(resolved[field])
    return resolved


def mqtt_service() -> dict | None:
    """Broker details when the Mosquitto add-on provides the MQTT service."""
    try:
        return json.loads(_request("/services/mqtt")).get("data") or None
    except (ValueError, json.JSONDecodeError):
        return None
