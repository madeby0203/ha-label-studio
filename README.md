# DYMO Labels Home Assistant add-on

This repository contains a Home Assistant add-on for a USB DYMO LabelWriter 400. Open the add-on through ingress to render a live preview, save templates, choose a label size, and print. The connection section accepts `/dev/usb/lp0` or a CUPS printer name.

The JSON API is available at `POST /api/print` through the add-on ingress URL:

```json
{
  "text": "Milk\nUse first",
  "label_size": "99010",
  "icon": "mdi:fridge",
  "copies": 1,
  "date": true,
  "qr": "https://example.test/milk"
}
```

Render a local preview without Docker:

```sh
python3 -m pip install -r dymo-labels/requirements.txt
python3 dymo-labels/render_png.py /tmp/label.png --text Milk --icon mdi:fridge --qr https://example.test
```