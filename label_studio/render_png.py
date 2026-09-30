#!/usr/bin/env python3
"""Render a label locally, useful for iterating without Home Assistant or USB."""

import argparse

from label_renderer import DEFAULT_FONT, DEFAULT_LABEL_SIZE, FONT_FAMILIES, LABEL_SIZES, render_label


parser = argparse.ArgumentParser()
parser.add_argument("output", help="PNG output path")
parser.add_argument("--size", default=DEFAULT_LABEL_SIZE, choices=tuple(LABEL_SIZES))
parser.add_argument("--text", action="append", default=[], help="a line of text; repeat for more lines")
parser.add_argument("--icon", help="mdi:name or an emoji")
parser.add_argument("--font", default=DEFAULT_FONT, choices=tuple(FONT_FAMILIES))
parser.add_argument("--regular", action="store_true", help="use the regular weight instead of bold")
parser.add_argument("--align", default="left", choices=("left", "center", "right"))
parser.add_argument("--date")
parser.add_argument("--qr")
args = parser.parse_args()
render_label(
    lines=args.text or ["Test label"],
    label_size=args.size,
    icon=args.icon,
    date_text=args.date,
    qr_text=args.qr,
    font=args.font,
    bold=not args.regular,
    align=args.align,
).save(args.output, dpi=(300, 300))
