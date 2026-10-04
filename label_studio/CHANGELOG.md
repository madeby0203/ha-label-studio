# Changelog

## 1.1.1

- The tagged layout's title is set in Bricolage Grotesque Bold, as in the design (was Figtree Black).

## 1.1.0

- The tagged layout (`"layout": "tagged"`): a tag, a large title, a line under it, a boxed code and a QR code, black on white or inverted. Used for inventory labels from Homebase.
- Figtree is included as the font for the tagged layout.

## 1.0.0

First public release.

- Label designer with live preview, fonts, automatic text fitting and hyphenation.
- One image per label: a Material Design icon, an emoji or a QR code, left, right, above or below the text.
- Dates filled in when printing, and Home Assistant templates in text and QR codes.
- Templates, each published as a print button in Home Assistant through MQTT discovery.
- All LabelWriter 400/450 label sizes, favourites and per-label print corrections.
- Optional network printer (CUPS with DYMO's driver, announced over Bonjour/AirPrint).
- Interface that follows your Home Assistant theme.
