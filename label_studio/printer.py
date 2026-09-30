"""USB and CUPS output for DYMO LabelWriter printers."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess

from PIL import Image


class PrinterError(RuntimeError):
    pass


# Shared with the CUPS backend, so network print jobs and add-on prints never interleave.
LOCK_FILE = Path(os.environ.get("DYMO_LOCK_FILE", "/run/dymo-labels.lock"))


ESC = 0x1B
SYN = 0x16
# The LabelWriter 400/450 head is 672 dots (56 mm at 300 dpi) wide.
MAX_HEAD_BYTES = 84


def _raster_rows(image: Image.Image) -> tuple[int, list[bytes]]:
    """Pack a 1-bit image into printer rows, one byte per 8 dots, black as one."""
    image = image.convert("1")
    width_bytes = (image.width + 7) // 8
    if image.width % 8:
        padded = Image.new("1", (width_bytes * 8, image.height), 1)
        padded.paste(image, (0, 0))
        image = padded
    # Pillow packs white as one, the printer burns a dot for every one bit.
    data = bytes(value ^ 0xFF for value in image.tobytes())
    return width_bytes, [data[i : i + width_bytes] for i in range(0, len(data), width_bytes)]


class DirectDymoPrinter:
    """Raster transport for the DYMO LabelWriter 400/450 USB protocol."""

    def __init__(self, device: str = "/dev/usb/lp0") -> None:
        self.device = device

    def print_image(self, image: Image.Image, copies: int = 1, rotate: bool = False) -> None:
        if not os.path.exists(self.device):
            raise PrinterError(f"USB printer device does not exist: {self.device}")
        # Each raster line runs across the print head, i.e. across the label's feed direction.
        if rotate:
            image = image.transpose(Image.Transpose.ROTATE_270)
        # Some labels are a little wider than the head (57-59 mm on 56 mm); like DYMO's own
        # driver, leave off what the head cannot reach. The label margins keep it blank.
        head_dots = MAX_HEAD_BYTES * 8
        image = image.crop((0, 0, min(image.width, head_dots), image.height))
        width_bytes, rows = _raster_rows(image)

        # A run of ESC bytes resynchronises the printer if a previous job was cut off.
        # Deliberately no ESC @ reset: it marks the printer as at top-of-form, which skips
        # the reverse feed back from the tear-bar and prints several mm too low.
        payload = bytearray([ESC] * 156)
        payload += bytes((ESC, ord("h")))  # 300 x 300 dpi text mode
        payload += bytes((ESC, ord("e")))  # normal density
        payload += bytes((ESC, ord("B"), 0))  # dot tab: start at the label edge
        payload += bytes((ESC, ord("D"), width_bytes))  # bytes per raster line
        copies = max(1, copies)
        for copy in range(copies):
            for row in rows:
                payload.append(SYN)
                payload += row
            # Short form feed between copies; a full form feed moves the last label to the tear-bar.
            payload += bytes((ESC, ord("G" if copy < copies - 1 else "E")))
        try:
            with LOCK_FILE.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with Path(self.device).open("wb", buffering=0) as printer:
                    printer.write(payload)
        except OSError as exc:
            raise PrinterError(f"Could not write to {self.device}: {exc}") from exc


class CupsPrinter:
    def __init__(self, printer_name: str = "DYMO") -> None:
        self.printer_name = printer_name

    def print_image(self, image: Image.Image, copies: int = 1, rotate: bool = False) -> None:
        # The CUPS driver handles orientation itself via fit-to-page.
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
    header = f"P4\n{image.width} {image.height}\n".encode("ascii")
    return header + b"".join(_raster_rows(image)[1])


def make_printer(settings: dict):
    backend = settings.get("backend", "direct")
    if backend == "cups":
        return CupsPrinter(settings.get("cups_printer", "DYMO"))
    return DirectDymoPrinter(settings.get("device", "/dev/usb/lp0"))