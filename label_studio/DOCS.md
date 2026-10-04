# Label Studio

Design and print labels on a DYMO LabelWriter connected to your Home Assistant by USB.

## Requirements

- Home Assistant OS or a Supervised installation (apps are not available on Container or Core installations).
- A DYMO LabelWriter of the 400 or 450 series, connected by USB. The LabelWriter 4XL and the 550 series use a different print head or protocol and are not supported.
- For print buttons in Home Assistant: an MQTT broker and the MQTT integration. The Mosquitto broker app is used automatically when it is installed.

## Getting started

1. Connect the LabelWriter to your Home Assistant by USB and start this app.
2. Open **Label Studio** from the sidebar.
3. Click the cog in the top right corner, tick the label sizes you use under **Label sizes** and choose your default. Save.
4. Type some text, check the preview and click **Print**.

The label screen follows your Home Assistant theme, including dark mode and custom themes.

## Designing a label

- **Text:** one line per row. Long lines wrap, and text is made as large as fits. Words that are too long for a line are hyphenated at syllable breaks; choose the **Hyphenation** language to match your text.
- **Font, weight and alignment:** Roboto, Roboto Condensed (fits more text), DejaVu Sans, DejaVu Serif or DejaVu Sans Mono, bold or regular, aligned left, centre or right.
- **Text size:** *Auto* makes the text as large as fits. Pick a size in points to use that size; the text only gets smaller if it does not fit.
- **Image:** choose *None*, *Icon* or *QR code*; a label has at most one image.
  - Icons: search all [Material Design Icons](https://pictogrammers.com/library/mdi/) by name, type `mdi:name`, or paste an emoji.
  - QR codes: any text or URL.
  - **Position** places the image left of, right of, above or below the text; **Size** scales it.
- **Date:** none, *Today, when printed* (filled in at the moment of printing) or a fixed date, in the format of your choice.
- **Advanced:** the icon margin (around the icon or QR code), text margin (around the text) and the space between them, in mm.

### Home Assistant templates

Text and QR codes can contain [Home Assistant templates](https://www.home-assistant.io/docs/configuration/templating/). They are filled in when the label is printed, also when printing from a button or an automation, and the preview shows the result. For example:

| Template | Prints |
|---|---|
| `{{ now().strftime('%d-%m-%Y') }}` | today's date |
| `{{ now().strftime('%H:%M') }}` | the current time |
| `{{ (now() + timedelta(days=3)).strftime('%d-%m') }}` | a date 3 days from now |
| `{{ states('sensor.freezer_temperature') }}` | the state of an entity |

Click **Use Home Assistant templates** under the text field for these examples.

## Label sizes, favourites and print corrections

All 55 labels of DYMO's LabelWriter 400/450 driver are available. Under **Printer settings → Label sizes**:

- **Tick your favourites.** Only favourites are offered on the label screen and to computers using the network printer.
- **Default label:** the size the label screen starts with, and the size preselected for network printing.
- **Print correction:** if a label type prints off-centre, correct it per label, in mm. Horizontal **+** moves the print right; vertical **−** moves it up. For example, if 11354 labels print 2 mm too low, set their vertical correction to −2.

Corrections apply to everything this app prints: the Print button, Home Assistant buttons and automations. The preview keeps showing the label as designed. Jobs from computers on the network are converted by DYMO's own driver and do not get the correction.

## Templates and Home Assistant buttons

Click **Save as template** to keep a label for later. Templates appear on the label screen, and, when MQTT is set up, each template becomes a button in Home Assistant on the **Label Studio** device, for example `button.label_studio_print_opened`. Pressing it prints the template, with dates and templates filled in at that moment. A **Last print** sensor on the same device shows the result of the latest print from Home Assistant.

MQTT is set up automatically when the Mosquitto broker app is installed. For another broker, fill in the MQTT options in the app's **Configuration** tab (see below). The **Templates** card on the label screen shows whether the connection works.

To put a print button on a dashboard, add a **Button** card for the template's button entity. In automations and scripts, use the `button.press` action on it.

### Printing from automations

Automations and scripts can also print any label, with or without a template, by publishing a JSON label to the `dymo_labels/print` MQTT topic:

```yaml
action: mqtt.publish
data:
  topic: dymo_labels/print
  payload: '{"template": "Opened", "copies": 2}'
```

A payload with `template` prints that template; any other fields override the template's settings. Without `template`, the payload describes a complete label:

```json
{
  "text": "Milk\nOpened {{ now().strftime('%d-%m') }}",
  "label_size": "11354",
  "graphic": "icon",
  "icon": "mdi:fridge",
  "image_position": "left",
  "copies": 1
}
```

| Field | Values |
|---|---|
| `text` | The text; one line per `\n`. Home Assistant templates allowed. |
| `label_size` | A DYMO label number, such as `11354` (57 × 32 mm) or `99010` (89 × 28 mm). |
| `graphic` | `icon`, `qr`, or empty for no image. Without it, an icon is used when set, else a QR code. |
| `icon` | `mdi:name` or an emoji. |
| `qr` | The QR code's content. Home Assistant templates allowed. |
| `image_position` | `left`, `right`, `top` or `bottom`. |
| `icon_size` | Image size, 20–100 (% of the largest that fits). |
| `font` | `roboto`, `roboto-condensed`, `dejavu-sans`, `dejavu-serif` or `dejavu-mono`. |
| `weight` | `bold` or `regular`. |
| `align` | `left`, `center` or `right`. |
| `text_size` | Font size in points; `0` or omitted for automatic. |
| `language` | Hyphenation: `nl_NL`, `en_US`, `de_DE` or `fr`. |
| `date` | `today` (filled in when printing), a date such as `2026-09-29`, or free text. |
| `date_format` | `%d-%m-%Y`, `%d/%m/%Y`, `%Y-%m-%d`, `%d %b %Y` or `%a %d %b`. |
| `icon_margin`, `text_margin`, `gap` | Spacing in mm. |
| `copies` | Number of labels. |

### The tagged layout

For labels made by other apps, such as inventory labels, `"layout": "tagged"` prints a fixed design: a tag in the top left, a large title, a line under it, a code in a box in the bottom left and a QR code in the bottom right. It can be printed white on black.

```json
{
  "layout": "tagged",
  "tag": "ITEM",
  "tag_style": "outline",
  "title": "Cordless drill",
  "subtitle": "Basement › Shelf B",
  "code": "I-0142",
  "qr": "I-0142",
  "invert": false,
  "label_size": "11354"
}
```

| Field | Values |
|---|---|
| `tag` | A short word in capitals, such as `LOCATION` or `ITEM`. Optional. |
| `tag_style` | `filled` (a solid pill) or `outline`. |
| `title` | The main text, made as large as fits on two lines at most. A title like `Box 2 · Camping gear` breaks after the dot. |
| `subtitle` | One smaller line under the title, shortened with … when too long. |
| `code` | A short code, printed in a box. |
| `qr` | The QR code's content. |
| `invert` | `true` prints white on black; the QR code keeps a white background so it still scans. |

The title, tag and subtitle use Figtree (included, SIL Open Font License); the code uses DejaVu Sans Mono. Other fields of the standard layout are ignored.

## Network printer

Label Studio can share the LabelWriter on your network, so computers and phones can print to it like any other printer. Turn on **Share this printer on the network** under **Printer settings**. It is off by default, and not available while the connection is set to CUPS.

The printer is announced over Bonjour/AirPrint as **DYMO LabelWriter**, so macOS, iOS, Windows and Linux find it when you add a printer. To add it by hand, use the address shown in the printer settings, such as `ipp://192.168.1.10:631/printers/DYMO`. Computers can choose from your favourite label sizes.

To announce itself on your network, the app runs on the host network. Its web interface only answers requests that come through Home Assistant, so it cannot be reached from other devices on port 8099.

## Configuration

Most settings are made on the label screen under **Printer settings**. The app's **Configuration** tab has:

| Option | Description |
|---|---|
| **Printer connection** (`backend`) | `direct` sends labels straight to the USB device; `cups` prints through a CUPS printer. |
| **USB device** (`device`) | The printer's device, usually `/dev/usb/lp0`. |
| **CUPS printer name** (`cups_printer`) | Used with the `cups` connection or the CUPS fallback. |
| **Fall back to CUPS** (`fallback_cups`) | Try CUPS when printing over direct USB fails. |
| **MQTT broker, port, username, password** | Your MQTT broker, for the print buttons. Leave the broker empty to use the Mosquitto broker app. |

## Troubleshooting

- **"USB printer device does not exist":** check that the printer is on and connected, then restart the app. The device is usually `/dev/usb/lp0`; a second USB printer may make it `/dev/usb/lp1`.
- **Labels print too high, too low or off to one side:** set a print correction for that label size (see above).
- **No buttons in Home Assistant:** check the **Templates** card on the label screen. If it says the app is not connected to MQTT, check the MQTT options and the app's log.
- **Computers do not find the network printer:** check the status under **Printer settings → Network printer**. Bonjour only works within one network (VLAN); otherwise add the printer by its address.

## Support

Report problems and ideas on [GitHub](https://github.com/madeby0203/ha-label-studio/issues).
