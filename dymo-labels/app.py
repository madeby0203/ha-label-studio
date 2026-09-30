from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import tempfile

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, url_for

from label_renderer import LABEL_SIZES, render_request
from printer import CupsPrinter, PrinterError, make_printer


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
TEMPLATES_FILE = DATA_DIR / "templates.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
app = Flask(__name__)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def _settings() -> dict:
    settings = {"backend": "direct", "device": "/dev/usb/lp0", "cups_printer": "DYMO"}
    settings.update(_load(DATA_DIR / "options.json", {}))
    settings.update(_load(SETTINGS_FILE, {}))
    return settings


PAGE = """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>DYMO Labels</title>
<style>body{font:16px system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;color:#17212b}main{display:grid;grid-template-columns:minmax(300px,1fr) minmax(280px,1fr);gap:2rem}label{display:block;margin:.8rem 0;font-weight:600}input,textarea,select,button{font:inherit;padding:.55rem;border:1px solid #9ba8b2;border-radius:4px;box-sizing:border-box;width:100%}textarea{min-height:130px}button{background:#0c6674;color:white;border:0;cursor:pointer;margin-top:.8rem}.row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}.preview{border:1px solid #b8c3c9;padding:1rem;background:#f5f7f7}.preview img{max-width:100%;image-rendering:pixelated;background:white}.saved{border-top:1px solid #ccd4d8;margin-top:1rem;padding-top:1rem}@media(max-width:700px){main{grid-template-columns:1fr}}</style></head>
<body><h1>DYMO Labels</h1><main><section><form id=form><label>Text<textarea id=text>Milk\nUse first</textarea></label><div class=row><label>Label size<select id=label_size>{% for id,size in sizes.items() %}<option value={{id}}>{{size.name}} ({{id}})</option>{% endfor %}</select></label><label>Copies<input id=copies type=number min=1 max=99 value=1></label></div><div class=row><label>MDI icon<input id=icon list=mdi-icons placeholder='mdi:fridge'><datalist id=mdi-icons><option value='mdi:fridge'><option value='mdi:home'><option value='mdi:printer'><option value='mdi:alert'><option value='mdi:check'><option value='mdi:food-apple'></datalist></label><label>Emoji<input id=emoji list=emoji-list placeholder='🥛'><datalist id=emoji-list><option value='🥛'><option value='🍎'><option value='🏠'><option value='✅'><option value='⚠️'></datalist></label></div><div class=row><label>Date<input id=date type=date></label><label>QR value<input id=qr placeholder='optional URL or text'></label></div><button type=button onclick='printLabel()'>Print label</button><button type=button onclick='saveTemplate()'>Save template</button></form><div class=saved><b>Saved templates</b><div id=templates></div></div></section><section class=preview><h2>Live preview</h2><img id=preview alt='Label preview'><p id=status></p><hr><h2>Printer connection</h2><label>Backend<select id=backend><option value=direct>Direct USB</option><option value=cups>CUPS</option></select></label><label>USB device<input id=device value='/dev/usb/lp0'></label><label>CUPS printer name<input id=cups_printer value='DYMO'></label><button type=button onclick='saveSettings()'>Save connection</button></section></main><script>
const fields=['text','label_size','copies','icon','emoji','date','qr']; const value=()=>Object.fromEntries(fields.map(id=>[id,document.getElementById(id).value]));
async function refresh(){let r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value())});document.getElementById('preview').src=URL.createObjectURL(await r.blob())} fields.forEach(id=>document.getElementById(id).addEventListener('input',refresh));
async function printLabel(){let r=await fetch('/api/print',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value())});document.getElementById('status').textContent=(await r.json()).message||'Done'}
async function saveTemplate(){let name=prompt('Template name');if(!name)return;await fetch('/api/templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,...value()})});loadTemplates()}
async function saveSettings(){let settings=Object.fromEntries(['backend','device','cups_printer'].map(id=>[id,document.getElementById(id).value]));await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});document.getElementById('status').textContent='Connection saved'}
async function loadTemplates(){let data=await (await fetch('/api/templates')).json();document.getElementById('templates').innerHTML=data.map(t=>`<button onclick='load(${JSON.stringify(t)})'>${t.name}</button>`).join('')} async function loadSettings(){let s=await (await fetch('/api/settings')).json();['backend','device','cups_printer'].forEach(id=>{if(s[id])document.getElementById(id).value=s[id]})} function load(t){fields.forEach(id=>{if(t[id]!==undefined)document.getElementById(id).value=t[id]});refresh()} loadTemplates();loadSettings();refresh();
</script></body></html>"""


@app.get("/")
def index():
    return render_template_string(PAGE, sizes=LABEL_SIZES)


@app.post("/api/preview")
def preview():
    image = render_request(request.get_json(silent=True) or {})
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    image.save(handle.name, format="PNG", dpi=(300, 300))
    return send_file(handle.name, mimetype="image/png")


@app.route("/api/templates", methods=["GET", "POST"])
def templates():
    saved = _load(TEMPLATES_FILE, [])
    if request.method == "POST":
        item = request.get_json(silent=True) or {}
        saved = [old for old in saved if old.get("name") != item.get("name")]
        saved.append(item)
        _save(TEMPLATES_FILE, saved)
    return jsonify(saved)


@app.post("/api/print")
def print_label():
    payload = request.get_json(silent=True) or {}
    try:
        image = render_request(payload)
        settings = _settings()
        copies = int(payload.get("copies", 1))
        try:
            make_printer(settings).print_image(image, copies)
        except PrinterError:
            if settings.get("backend", "direct") != "direct":
                raise
            CupsPrinter(settings.get("cups_printer", "DYMO")).print_image(image, copies)
        return jsonify(ok=True, message="Label sent to printer")
    except (PrinterError, ValueError, TypeError) as exc:
        return jsonify(ok=False, message=str(exc)), 500


@app.get("/api/settings")
def settings():
    return jsonify(_settings())


@app.post("/api/settings")
def save_settings():
    value = request.get_json(silent=True) or {}
    _save(SETTINGS_FILE, value)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8099")))