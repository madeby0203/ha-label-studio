#!/usr/bin/env python3
"""Render a label locally, useful for iterating without Home Assistant or USB."""

import argparse

from label_renderer import render_label


parser = argparse.ArgumentParser()
parser.add_argument("output", help="PNG output path")
parser.add_argument("--size", default="99010", choices=("99010", "11354"))
parser.add_argument("--text", action="append", default=[])
parser.add_argument("--icon")
parser.add_argument("--emoji")
parser.add_argument("--date")
parser.add_argument("--qr")
args = parser.parse_args()
render_label(lines=args.text or ["Test label"], label_size=args.size, icon=args.icon, emoji=args.emoji, date_text=args.date, qr_text=args.qr).save(args.output, dpi=(300, 300))