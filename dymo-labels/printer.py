"""USB and CUPS output for DYMO LabelWriter printers."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from PIL import Image


class PrinterError(RuntimeError):
    pass


def _pack_scanline(row: bytes) -> bytes:
    """Pack Pillow's 0/255 pixels into printer bitmap bytes, black as one."""
    packed = bytearray((len(row) + 7) // 8)
    for pixel, value in enumerate(row):
        if value < 128:
            packed[pixel // 8] |= 0x80 >> (pixel % 8)
    return bytes(packed)


class DirectDymoPrinter:
    """Minimal raster transport for the LabelWriter 400 USB protocol."""

    def __init__(self, device: str = "/dev/usb/lp0") -> None:
        self.device = device

    def print_image(self, image: Image.Image, copies: int = 1) -> None:
        if not os.path.exists(self.device):
            raise PrinterError(f"USB printer device does not exist: {self.device}")
        image = image.convert("1")
        width_bytes = (image.width + 7) // 8
        payload = bytearray(b"\x1b@")
        # ESC i M selects raster mode; ESC i P advances and prints the label.
        payload.extend(b"\x1biM")
        payload.extend(bytes((width_bytes & 0xFF, (width_bytes >> 8) & 0xFF)))
        for _ in range(max(1, copies)):
            for y in range(image.height):
                payload.extend(b"\x1biW")
                payload.extend(width_bytes.to_bytes(2, "little"))
                payload.extend(_pack_scanline(image.crop((0, y, image.width, y + 1)).convert("L").tobytes()))
            payload.extend(b"\x1biP")
        payload.extend(b"\x1b@")
        try:
            with Path(self.device).open("wb", buffering=0) as printer:
                printer.write(payload)
        except OSError as exc:
            raise PrinterError(f"Could not write to {self.device}: {exc}") from exc


class CupsPrinter:
    def __init__(self, printer_name: str = "DYMO") -> None:
        self.printer_name = printer_name

    def print_image(self, image: Image.Image, copies: int = 1) -> None:
        try:
            process = subprocess.run(
                ["lp", "-d", self.printer_name, "-n", str(max(1, copies)), "-o", "fit-to-page", "-t", "DYMO label"],
                input=_pbm(image),
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", b"").decode(errors="replace")
            raise PrinterError(f"CUPS print failed: {detail or exc}") from exc


def _pbm(image: Image.Image) -> bytes:
    image = image.convert("1")
    header = f"P4\n{image.width} {image.height}\n".encode("ascii")
    rows = b"".join(_pack_scanline(image.crop((0, y, image.width, y + 1)).convert("L").tobytes()) for y in range(image.height))
    return header + rows


def make_printer(settings: dict):
    backend = settings.get("backend", "direct")
    if backend == "cups":
        return CupsPrinter(settings.get("cups_printer", "DYMO"))
    return DirectDymoPrinter(settings.get("device", "/dev/usb/lp0"))