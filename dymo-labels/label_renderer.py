"""Render DYMO labels to 1-bit Pillow images."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
import qrcode


@dataclass(frozen=True)
class LabelSize:
    id: str
    name: str
    width_mm: float
    height_mm: float

    @property
    def pixels(self) -> tuple[int, int]:
        return round(self.width_mm / 25.4 * 300), round(self.height_mm / 25.4 * 300)


LABEL_SIZES = {
    "99010": LabelSize("99010", "89 x 28 mm", 89, 28),
    "11354": LabelSize("11354", "57 x 32 mm", 57, 32),
}

_FONT_DIRS = (
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf").parent,
    Path(__file__).parent / "fonts",
)
_MDI_ALIASES = {
    "mdi:fridge": "▣",
    "mdi:food-apple": "●",
    "mdi:home": "⌂",
    "mdi:alert": "!",
    "mdi:check": "✓",
    "mdi:printer": "▤",
}


def _find_font(*names: str) -> Path | None:
    for directory in _FONT_DIRS:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def _font(size: int, *, bold: bool = False, emoji: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ("NotoEmoji-Regular.ttf", "NotoColorEmoji.ttf") if emoji else (
        ("DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf") if bold else ("DejaVuSans.ttf", "NotoSans-Regular.ttf")
    )
    path = _find_font(*names)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_size: int, min_size: int = 8) -> ImageFont.ImageFont:
    for size in range(max_size, min_size - 1, -1):
        font = _font(size, bold=True)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
    return _font(min_size, bold=True)


def _normalise_icon(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("mdi:"):
        return _MDI_ALIASES.get(value.lower(), "■")
    return value


def _draw_centered(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.ImageFont) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=font)
    x = left + (right - left - bounds[2] + bounds[0]) // 2
    y = top + (bottom - top - bounds[3] + bounds[1]) // 2
    draw.text((x, y), text, fill=0, font=font)


def _draw_qr(image: Image.Image, value: str, size: int, margin: int) -> None:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=0)
    qr.add_data(value)
    qr.make(fit=True)
    code = qr.make_image(fill_color="black", back_color="white").convert("1")
    code.thumbnail((size, size), Image.Resampling.NEAREST)
    x = image.width - code.width - margin
    y = image.height - code.height - margin
    image.paste(code, (x, y))


def render_label(
    *,
    lines: Iterable[str],
    label_size: str = "99010",
    icon: str | None = None,
    emoji: str | None = None,
    date_text: str | None = None,
    qr_text: str | None = None,
    margin: int = 18,
) -> Image.Image:
    """Render a label at 300 DPI as a Pillow mode-1 image."""
    try:
        dimensions = LABEL_SIZES[label_size].pixels
    except KeyError as exc:
        raise ValueError(f"Unknown label size: {label_size}") from exc

    image = Image.new("1", dimensions, 1)
    draw = ImageDraw.Draw(image)
    content_width = image.width - margin * 2
    label_lines = [line for line in lines if line is not None and str(line).strip()]
    if date_text:
        label_lines.append(date_text)

    icon_text = _normalise_icon(icon) or emoji
    icon_height = 0
    if icon_text:
        icon_font = _font(min(72, image.height // 2), emoji=bool(emoji and not icon))
        icon_box = (margin, margin, margin + min(image.height - margin * 2, 100), image.height - margin)
        _draw_centered(draw, icon_box, icon_text, icon_font)
        icon_height = icon_box[2] - icon_box[0] + 10

    qr_size = min(image.height - margin * 2, 180) if qr_text else 0
    if qr_text:
        _draw_qr(image, qr_text, qr_size, margin)

    text_left = margin + icon_height if icon_text else margin
    text_right = image.width - margin - qr_size - (margin if qr_text else 0)
    available_width = max(20, text_right - text_left)
    line_height = max(18, image.height // max(2, len(label_lines) + 1))
    top = margin
    for line in label_lines:
        font = _fit_font(draw, str(line), available_width, min(52, line_height + 12))
        bounds = draw.textbbox((0, 0), str(line), font=font)
        y = top + max(0, (line_height - (bounds[3] - bounds[1])) // 2) - bounds[1]
        draw.text((text_left, y), str(line), fill=0, font=font)
        top += line_height

    return image


def render_request(request: dict) -> Image.Image:
    date_text = request.get("date")
    if date_text is True:
        date_text = date.today().isoformat()
    return render_label(
        lines=request.get("text", "").splitlines(),
        label_size=request.get("label_size", "99010"),
        icon=request.get("icon"),
        emoji=request.get("emoji"),
        date_text=date_text,
        qr_text=request.get("qr"),
    )