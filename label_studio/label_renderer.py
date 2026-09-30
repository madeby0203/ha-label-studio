"""Render DYMO labels to 1-bit Pillow images."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps
import pyphen
import qrcode


DPI = 300


def mm(value: float) -> int:
    return round(value / 25.4 * DPI)


@dataclass(frozen=True)
class LabelSize:
    """A DYMO label, sized in points as DYMO's CUPS driver defines it.

    ``across`` runs along the print head and ``along`` in the feed direction.
    The label is designed in landscape: its long side is horizontal.
    """

    id: str
    description: str
    across: float
    along: float
    # The page size keyword in DYMO's driver, used for the network printer.
    ppd: str

    @property
    def feeds_along_width(self) -> bool:
        """True when the long side runs through the printer, so the image must be rotated."""
        return self.along > self.across

    @property
    def pixels(self) -> tuple[int, int]:
        long, short = max(self.across, self.along), min(self.across, self.along)
        return round(long / 72 * DPI), round(short / 72 * DPI)

    @property
    def millimetres(self) -> tuple[float, float]:
        return tuple(round(max(value, 0) / 72 * 25.4, 1) for value in (max(self.across, self.along), min(self.across, self.along)))

    @property
    def name(self) -> str:
        width, height = self.millimetres
        return f"{self.id.split('-')[0]} {self.description} ({width:g} × {height:g} mm)"


# Every label DYMO's LabelWriter 400 driver knows, generated from its PPD (lw400.ppd);
# duplicate aliases, continuous tape and banners are left out.
LABEL_SIZES = {size.id: size for size in (
    LabelSize("11351", "Jewelry Label", 153.6, 63.12, "w154h64"),
    LabelSize("11352", "Return Address Int", 72, 153.12, "w72h154"),
    LabelSize("11353", "Multi-Purpose", 72, 72, "w72h72"),
    LabelSize("11354", "Multi-Purpose", 162, 90, "w162h90"),
    LabelSize("11355", "Multi-Purpose", 54, 144, "w54h144"),
    LabelSize("11356", "White Name badge", 117.12, 252, "w118h252"),
    LabelSize("14681", "CD/DVD Label", 166.32, 187.2, "w167h188"),
    LabelSize("30252", "Address", 78.96, 252, "w79h252"),
    LabelSize("30253", "Address (2 up)", 166.32, 252, "w167h252"),
    LabelSize("30256", "Shipping", 166.56, 288, "w167h288"),
    LabelSize("30258", "Diskette", 153.12, 198, "w154h198"),
    LabelSize("30277", "File Folder (2 up)", 81.12, 247.44, "w82h248"),
    LabelSize("30299", "Jewelry Label (2 up)", 153.6, 63.12, "w154h64.1"),
    LabelSize("30320", "Address", 78.96, 252, "w79h252.1"),
    LabelSize("30321", "Large Address", 101.28, 251.04, "w102h252"),
    LabelSize("30323", "Shipping", 153.12, 285.84, "w154h286"),
    LabelSize("30324", "Diskette", 153.12, 198, "w154h198.1"),
    LabelSize("30325", "Video Spine", 54, 423.12, "w54h424"),
    LabelSize("30326", "Video Top", 130.56, 220.56, "w131h221"),
    LabelSize("30327", "File Folder", 56.4, 247.44, "w57h248"),
    LabelSize("30330", "Return Address", 54, 144, "w54h144.1"),
    LabelSize("30332", "1 in x 1 in", 72, 72, "w72h72.1"),
    LabelSize("30333", "1/2 in x 1 in (2 up)", 72, 72, "w72h72.2"),
    LabelSize("30334", "2-1/4 in x 1-1/4 in", 162, 90, "w162h90.1"),
    LabelSize("30335", "1/2 in x 1/2 in (4 up)", 72.96, 85.44, "w73h86"),
    LabelSize("30336", "1 in x 2-1/8 in", 72, 153.12, "w72h154.1"),
    LabelSize("30337", "Audio Cassette", 117.12, 252, "w118h252.1"),
    LabelSize("30339", "8mm Video (2 up)", 54, 202.56, "w54h203"),
    LabelSize("30345", "3/4 in x 2-1/2 in", 54, 180, "w54h180"),
    LabelSize("30346", "1/2 in x 1-7/8 in", 36, 135.12, "w36h136"),
    LabelSize("30347", "1 in x 1-1/2 in", 72, 108, "w72h108"),
    LabelSize("30348", "9/10 in x 1-1/4 in", 64.8, 90, "w65h90"),
    LabelSize("30364", "Name Badge Label", 166.56, 288, "w167h288.1"),
    LabelSize("30365", "Name Badge Card", 167.04, 252, "w168h252"),
    LabelSize("30370", "Zip Disk", 144, 168.72, "w144h169"),
    LabelSize("30373", "Price Tag Label", 70.32, 144, "w71h144"),
    LabelSize("30374", "Appointment Card", 144, 252, "w144h252"),
    LabelSize("30376", "Hanging File Insert", 79.2, 144, "w80h144"),
    LabelSize("30383", "PC Postage 3-Part", 162, 504, "w162h504"),
    LabelSize("30384", "PC Postage 2-Part", 166.56, 540, "w167h540"),
    LabelSize("30387", "PC Postage EPS", 166.56, 756, "w167h756"),
    LabelSize("30854", "CD Label", 166.32, 187.2, "w167h188.1"),
    LabelSize("30856", "Badge Card Label", 175.44, 291.6, "w176h292"),
    LabelSize("30857", "Badge Label", 166.56, 288, "w167h288.2"),
    LabelSize("30886", "CD Label", 111.36, 126, "w112h126"),
    LabelSize("99010", "Standard Address", 78.96, 252, "w79h252.2"),
    LabelSize("99012", "Large Address", 101.28, 251.04, "w102h252.1"),
    LabelSize("99014-name-badge-label", "Name Badge Label", 153.12, 285.84, "w154h286.1"),
    LabelSize("99014-shipping", "Shipping", 153.12, 285.84, "w154h286.2"),
    LabelSize("99015", "Diskette", 153.12, 198, "w154h198.2"),
    LabelSize("99016-video-spine", "Video Spine", 62.4, 418.56, "w63h419"),
    LabelSize("99016-video-top", "Video Top", 138.96, 220.56, "w139h221"),
    LabelSize("99017", "Suspension File", 36, 144, "w36h144"),
    LabelSize("99018", "Small Lever Arch", 107.76, 538.56, "w108h539"),
    LabelSize("99019", "Large Lever Arch", 166.56, 538.56, "w167h539"),
)}
DEFAULT_LABEL_SIZE = "11354"
# Label sizes offered on the main screen and to network clients until the user picks favourites.
DEFAULT_FAVORITES = ("11354", "99010")

# Default blank border kept around the icon, QR code and text, in mm.
MARGIN_MM = 2.5
# Default space between the icon, the text block and the QR code, in mm.
GAP_MM = 2.0
MAX_SPACING_MM = 10.0
MARGIN = mm(MARGIN_MM)
MIN_TEXT_SIZE = 14
DATE_SCALE = 0.6
# strftime pattern -> example shown in the web UI.
DATE_FORMATS = {
    "%d-%m-%Y": "29-09-2026",
    "%d/%m/%Y": "29/09/2026",
    "%Y-%m-%d": "2026-09-29",
    "%d %b %Y": "29 Sep 2026",
    "%a %d %b": "Tue 29 Sep",
}
DEFAULT_DATE_FORMAT = "%d-%m-%Y"
PARAGRAPH_SPACING = 0.3
# With automatic text size, words are hyphenated rather than shrinking the text
# below this fraction of the text box height.
HYPHENATE_BELOW = 0.2
MIN_ICON_SIZE = 20
IMAGE_POSITIONS = ("left", "right", "top", "bottom")
HYPHENATION_LANGUAGES = {"nl_NL": "Nederlands", "en_US": "English", "de_DE": "Deutsch", "fr": "Français"}
DEFAULT_LANGUAGE = "nl_NL"


@dataclass(frozen=True)
class FontFamily:
    name: str
    regular: str
    bold: str


FONT_FAMILIES = {
    "roboto": FontFamily("Roboto", "Roboto-Regular.ttf", "Roboto-Bold.ttf"),
    "roboto-condensed": FontFamily("Roboto Condensed", "RobotoCondensed-Regular.ttf", "RobotoCondensed-Bold.ttf"),
    "dejavu-sans": FontFamily("DejaVu Sans", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "dejavu-serif": FontFamily("DejaVu Serif", "DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    "dejavu-mono": FontFamily("DejaVu Sans Mono", "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
}
DEFAULT_FONT = "roboto"

MDI_CSS = "materialdesignicons.css"
MDI_FONT = "materialdesignicons-webfont.ttf"
EMOJI_FONT = "NotoColorEmoji.ttf"
# Noto Color Emoji is a bitmap font that only loads at this size.
EMOJI_FONT_SIZE = 109

# A starting set for the icon picker; any other MDI name works as well.
HOME_ICONS = (
    "fridge", "fridge-outline", "stove", "microwave", "dishwasher", "washing-machine", "tumble-dryer",
    "coffee", "kettle", "food-apple", "food-drumstick", "cheese", "bread-slice", "egg", "fish", "carrot",
    "bottle-wine", "glass-mug-variant", "baby-bottle", "silverware-fork-knife", "snowflake", "fire",
    "spray-bottle", "broom", "trash-can", "recycle", "shower", "toilet", "toothbrush", "bed", "sofa",
    "lamp", "lightbulb", "power-plug", "battery", "flash", "fuse", "router-wireless", "television",
    "remote", "cable-data", "key", "lock", "door", "garage", "home", "tools", "hammer", "screwdriver",
    "wrench", "toolbox", "tape-measure", "paint-roller", "flower", "sprout", "watering-can", "leaf",
    "dog", "cat", "paw", "pill", "medical-bag", "hanger", "tshirt-crew", "shoe-sneaker", "gift",
    "package-variant-closed", "archive", "file-cabinet", "folder", "book-open-variant", "calendar",
    "alert", "check-circle", "information", "thermometer", "water", "car", "bike",
)

_FONT_ROOTS = [Path(entry) for entry in os.environ.get("FONT_DIRS", "").split(os.pathsep) if entry] + [
    Path("/usr/share/fonts"),
    Path("/usr/share/mdi"),
    Path(__file__).parent / "fonts",
]


@lru_cache(maxsize=None)
def find_font_file(name: str) -> Path | None:
    for root in _FONT_ROOTS:
        if root.is_dir():
            for match in root.rglob(name):
                return match
    return None


def available_fonts() -> dict[str, str]:
    fonts = {key: family.name for key, family in FONT_FAMILIES.items() if find_font_file(family.bold) or find_font_file(family.regular)}
    return fonts or {DEFAULT_FONT: "Default"}


@lru_cache(maxsize=512)
def _text_font(family: str, bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    chosen = FONT_FAMILIES.get(family, FONT_FAMILIES[DEFAULT_FONT])
    candidates = [chosen.bold, chosen.regular] if bold else [chosen.regular, chosen.bold]
    # Fall back to any installed family before Pillow's built-in font.
    candidates += [other.bold if bold else other.regular for other in FONT_FAMILIES.values()]
    for name in candidates:
        path = find_font_file(name)
        if path:
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


@lru_cache(maxsize=1)
def mdi_icons() -> dict[str, int]:
    """Map MDI icon names to their code points, read from the webfont's CSS."""
    css = find_font_file(MDI_CSS)
    if not css:
        return {}
    pattern = r'\.mdi-([a-z0-9-]+)::before\s*\{\s*content:\s*"\\([0-9A-Fa-f]+)"'
    return {name: int(code, 16) for name, code in re.findall(pattern, css.read_text())}


def home_icons() -> list[str]:
    icons = mdi_icons()
    return [name for name in HOME_ICONS if name in icons]


def _fit_into_square(tile: Image.Image, size: int) -> Image.Image:
    """Scale a greyscale tile to fit a size x size white square, centred."""
    scale = min(size / tile.width, size / tile.height)
    tile = tile.resize((max(1, round(tile.width * scale)), max(1, round(tile.height * scale))), Image.Resampling.LANCZOS)
    square = Image.new("L", (size, size), 255)
    square.paste(tile, ((size - tile.width) // 2, (size - tile.height) // 2))
    return square


def _glyph_tile(text: str, font: ImageFont.ImageFont, size: int) -> Image.Image | None:
    canvas = Image.new("L", (size * 2, size * 2), 255)
    ImageDraw.Draw(canvas).text((size, size), text, font=font, fill=0, anchor="mm")
    bbox = ImageOps.invert(canvas).getbbox()
    if not bbox:
        return None
    return _fit_into_square(canvas.crop(bbox), size).point(lambda value: 0 if value < 128 else 255).convert("1")


def _emoji_tile(text: str, size: int) -> Image.Image | None:
    path = find_font_file(EMOJI_FONT)
    if not path:
        return None
    try:
        font = ImageFont.truetype(str(path), EMOJI_FONT_SIZE)
    except OSError:
        return None
    canvas = Image.new("RGBA", (EMOJI_FONT_SIZE * 3, EMOJI_FONT_SIZE * 3), (255, 255, 255, 0))
    ImageDraw.Draw(canvas).text((canvas.width // 2, canvas.height // 2), text, font=font, anchor="mm", embedded_color=True)
    bbox = canvas.getbbox()
    if not bbox:
        return None
    glyph = canvas.crop(bbox)
    flat = Image.new("RGBA", glyph.size, "white")
    flat.alpha_composite(glyph)
    # Stretch the emoji's colours over the full grey range so pale parts still show once dithered.
    grey = ImageOps.autocontrast(flat.convert("L"), cutoff=1)
    return _fit_into_square(grey, size).convert("1", dither=Image.Dither.FLOYDSTEINBERG)


def icon_tile(icon: str, size: int) -> Image.Image:
    """Render an ``mdi:name`` icon or an emoji as a size x size 1-bit image."""
    icon = icon.strip()
    if icon.lower().startswith("mdi:"):
        name = icon[4:].strip().lower()
        code = mdi_icons().get(name)
        font_path = find_font_file(MDI_FONT)
        if code is None or font_path is None:
            raise ValueError(f"Unknown icon: {icon}")
        tile = _glyph_tile(chr(code), ImageFont.truetype(str(font_path), size), size)
    else:
        tile = _emoji_tile(icon, size) or _glyph_tile(icon, _text_font(DEFAULT_FONT, True, size), size)
    if tile is None:
        raise ValueError(f"Cannot draw icon: {icon}")
    return tile


def _qr_tile(value: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
    qr.add_data(value)
    qr.make(fit=True)
    code = qr.make_image(fill_color="black", back_color="white").get_image().convert("1")
    # Whole-pixel modules keep the code sharp enough to scan.
    module = max(1, size // code.width)
    code = code.resize((code.width * module, code.height * module), Image.Resampling.NEAREST)
    tile = Image.new("1", (size, size), 1)
    tile.paste(code, ((size - code.width) // 2, (size - code.height) // 2))
    return tile


def _line_height(font: ImageFont.ImageFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


@lru_cache(maxsize=None)
def _hyphenator(language: str) -> pyphen.Pyphen:
    return pyphen.Pyphen(lang=language if language in HYPHENATION_LANGUAGES else DEFAULT_LANGUAGE)


def _split_word(word: str, font: ImageFont.ImageFont, room: float, language: str) -> tuple[str, str] | None:
    """Split a word at the last syllable break whose first part, plus a hyphen, fits in ``room``."""
    points = set(_hyphenator(language).positions(word))
    # Words that already contain a hyphen can break right after it.
    points |= {index + 1 for index, char in enumerate(word[:-1]) if char == "-"}
    for point in sorted(points, reverse=True):
        head = word[:point] if word[point - 1] == "-" else word[:point] + "-"
        if font.getlength(head) <= room:
            return head, word[point:]
    return None


def _force_split(word: str, font: ImageFont.ImageFont, width: int) -> tuple[str, str]:
    """Split at the last letter that fits, for words without a usable syllable break."""
    cut = len(word) - 1
    while cut > 1 and font.getlength(word[:cut] + "-") > width:
        cut -= 1
    return word[:cut] + "-", word[cut:]


def _wrap(text: str, font: ImageFont.ImageFont, width: int, hyphenate: bool, language: str) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if font.getlength(candidate) <= width:
            current = candidate
            continue
        if hyphenate and font.getlength(word) > width:
            # Start a word that is too long for any line on the current one, then hyphenate the rest.
            split = _split_word(word, font, width - font.getlength(current + " "), language) if current else None
            if split:
                lines.append(f"{current} {split[0]}")
                word = split[1]
            elif current:
                lines.append(current)
            while font.getlength(word) > width and len(word) > 1:
                head, word = _split_word(word, font, width, language) or _force_split(word, font, width)
                lines.append(head)
            current = word
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _ellipsize(text: str, font: ImageFont.ImageFont, width: int) -> str:
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


@dataclass(frozen=True)
class Line:
    text: str
    font: ImageFont.ImageFont
    # Extra space above the first line of each new paragraph.
    space_before: int = 0

    @property
    def height(self) -> int:
        return self.space_before + _line_height(self.font)


@dataclass(frozen=True)
class TextStyle:
    family: str = DEFAULT_FONT
    bold: bool = True
    language: str = DEFAULT_LANGUAGE


def _set_text(paragraphs: list[tuple[str, float]], size: int, width: int, style: TextStyle, hyphenate: bool) -> list[Line]:
    lines: list[Line] = []
    for text, scale in paragraphs:
        font = _text_font(style.family, style.bold, max(MIN_TEXT_SIZE, round(size * scale)))
        space = round(_line_height(font) * PARAGRAPH_SPACING) if lines else 0
        for index, line in enumerate(_wrap(text, font, width, hyphenate, style.language)):
            lines.append(Line(line, font, space if index == 0 else 0))
    return lines


def _fits(lines: list[Line], width: int, height: int) -> bool:
    return sum(line.height for line in lines) <= height and all(line.font.getlength(line.text) <= width for line in lines)


def _largest_fit(paragraphs, width: int, height: int, style: TextStyle, hyphenate: bool, cap: int) -> tuple[int, list[Line]] | None:
    low = MIN_TEXT_SIZE
    best = _set_text(paragraphs, low, width, style, hyphenate)
    if not _fits(best, width, height):
        return None
    high = max(low, cap)
    while low < high:
        middle = (low + high + 1) // 2
        lines = _set_text(paragraphs, middle, width, style, hyphenate)
        if _fits(lines, width, height):
            low, best = middle, lines
        else:
            high = middle - 1
    return low, best


def _layout_text(paragraphs: list[tuple[str, float]], width: int, height: int, style: TextStyle, size: int | None = None) -> list[Line]:
    """Set the text as large as fits, up to ``size`` pixels when given.

    Words stay whole unless that would make the text smaller than the requested
    size (or, sized automatically, than a fifth of the box height); then long
    words are hyphenated when that allows larger text.
    """
    cap = max(MIN_TEXT_SIZE, min(height, size or height))
    comfortable = cap if size else max(MIN_TEXT_SIZE, round(height * HYPHENATE_BELOW))
    whole = _largest_fit(paragraphs, width, height, style, False, cap)
    if whole and whole[0] >= min(comfortable, cap):
        return whole[1]
    hyphenated = _largest_fit(paragraphs, width, height, style, True, cap)
    options = [option for option in (whole, hyphenated) if option]
    if options:
        # max() keeps the first of equal sizes, so whole words win ties.
        return max(options, key=lambda option: option[0])[1]
    # Even the smallest size overflows: keep what fits and mark the cut.
    kept: list[Line] = []
    used = 0
    for line in _set_text(paragraphs, MIN_TEXT_SIZE, width, style, True):
        if used + line.height > height:
            break
        kept.append(line)
        used += line.height
    if kept:
        last = kept[-1]
        kept[-1] = Line(_ellipsize(last.text, last.font, width), last.font, last.space_before)
    return kept


def _text_tile(lines: list[Line], width: int, height: int, align: str, y: int | None = None) -> Image.Image:
    """Draw the lines in a box, vertically centred unless a top offset ``y`` is given."""
    tile = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(tile)
    if y is None:
        y = (height - sum(line.height for line in lines)) // 2
    for line in lines:
        y += line.space_before
        free = width - line.font.getlength(line.text)
        x = {"center": free / 2, "right": free}.get(align, 0)
        draw.text((x, y), line.text, font=line.font, fill=0, anchor="la")
        y += _line_height(line.font)
    return tile


def render_label(
    *,
    lines: Iterable[str],
    label_size: str = DEFAULT_LABEL_SIZE,
    icon: str | None = None,
    emoji: str | None = None,
    date_text: str | None = None,
    qr_text: str | None = None,
    font: str = DEFAULT_FONT,
    bold: bool = True,
    align: str = "left",
    text_size: float | None = None,
    icon_size: int = 100,
    language: str = DEFAULT_LANGUAGE,
    icon_margin: float = MARGIN_MM,
    text_margin: float = MARGIN_MM,
    gap: float = GAP_MM,
    image_position: str = "left",
) -> Image.Image:
    """Render a label at 300 DPI as a Pillow mode-1 image.

    ``text_size`` is the preferred font size in points (automatic when empty) and
    ``icon_size`` a percentage of the largest icon that fits. ``icon_margin``
    (around the icon and QR code), ``text_margin`` (around the text) and ``gap``
    (between them) are in mm. A label shows either an icon or, without one, a QR
    code, placed at ``image_position`` (left, right, top or bottom) relative to the text.
    """
    try:
        width, height = LABEL_SIZES[label_size].pixels
    except KeyError as exc:
        raise ValueError(f"Unknown label size: {label_size}") from exc

    image = Image.new("1", (width, height), 1)
    paragraphs = [(str(line).strip(), 1.0) for line in lines if line is not None and str(line).strip()]
    if date_text:
        paragraphs.append((str(date_text), DATE_SCALE if paragraphs else 1.0))
    icon = (icon or emoji or "").strip()
    qr_text = "" if icon else (qr_text or "").strip()

    icon_margin, text_margin, gap = (mm(max(0.0, min(MAX_SPACING_MM, value))) for value in (icon_margin, text_margin, gap))
    left, top, right, bottom = text_margin, text_margin, width - text_margin, height - text_margin

    # A label has one image: an icon, or else a QR code. Alone it fills the label; next to
    # text it takes a square beside it (left/right) or above/below it (top/bottom).
    if icon or qr_text:
        position = image_position if image_position in IMAGE_POSITIONS else "left"
        area_width, area_height = width - 2 * icon_margin, height - 2 * icon_margin
        if not paragraphs:
            side = min(area_width, area_height)
        elif position in ("left", "right"):
            side = min(area_height, round(area_width * 0.38))
        else:
            side = min(area_width, round(area_height * 0.5))
        side = max(MIN_ICON_SIZE, round(side * max(10, min(100, icon_size)) / 100))
        tile = icon_tile(icon, side) if icon else _qr_tile(qr_text, side)
        # Beside the text the image is centred vertically; above or below it, it follows the text alignment.
        x = {"left": icon_margin, "right": width - icon_margin - side}.get(align if position in ("top", "bottom") else "", (width - side) // 2)
        y = (height - side) // 2
        if not paragraphs:
            x = (width - side) // 2
        elif position == "left":
            x = icon_margin
            left = max(left, x + side + gap)
        elif position == "right":
            x = width - icon_margin - side
            right = min(right, x - gap)
        elif position == "top":
            y = icon_margin
            top = max(top, y + side + gap)
        else:
            y = height - icon_margin - side
            bottom = min(bottom, y - gap)

    box_width, box_height = right - left, bottom - top
    text_y = None
    if paragraphs and box_width > MIN_TEXT_SIZE and box_height > MIN_TEXT_SIZE:
        style = TextStyle(font, bold, language)
        size = round(text_size / 72 * DPI) if text_size else None
        text = _layout_text(paragraphs, box_width, box_height, style, size)
        if (icon or qr_text) and position in ("top", "bottom"):
            # Keep the text against the image and centre the two together on the label.
            shift = (box_height - sum(line.height for line in text)) // 2
            text_y = 0 if position == "top" else box_height - sum(line.height for line in text)
            y, text_y = (y + shift, shift) if position == "top" else (y - shift, text_y - shift)
        image.paste(_text_tile(text, box_width, box_height, align, text_y), (left, top))
    if icon or qr_text:
        image.paste(tile, (x, y))
    return image


def shift_image(image: Image.Image, x_mm: float = 0, y_mm: float = 0) -> Image.Image:
    """Move a label's content by x/y mm (positive: right/down); what moves off the label is lost."""
    dx, dy = mm(x_mm), mm(y_mm)
    if not dx and not dy:
        return image
    shifted = Image.new(image.mode, image.size, 1)
    shifted.paste(image, (dx, dy))
    return shifted


def format_date(value, date_format: str | None = None) -> str | None:
    """Turn ``today``/``true``, an ISO date or free text into the text printed on the label."""
    if value is None or value is False or str(value).strip() == "":
        return None
    if value is True or str(value).strip().lower() == "today":
        day = date.today()
    else:
        try:
            day = date.fromisoformat(str(value).strip())
        except ValueError:
            return str(value)
    return day.strftime(date_format if date_format in DATE_FORMATS else DEFAULT_DATE_FORMAT)


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render_request(request: dict) -> Image.Image:
    date_text = format_date(request.get("date"), request.get("date_format"))
    # "graphic" says which image the label shows; without it an icon wins over a QR code.
    graphic = request.get("graphic")
    icon = request.get("icon") or request.get("emoji")
    qr = request.get("qr")
    if graphic == "qr":
        icon = None
    elif graphic == "icon":
        qr = None
    elif graphic == "":
        icon = qr = None
    return render_label(
        lines=str(request.get("text") or "").splitlines(),
        label_size=request.get("label_size") or DEFAULT_LABEL_SIZE,
        icon=icon,
        date_text=date_text,
        qr_text=qr,
        font=request.get("font") or DEFAULT_FONT,
        bold=str(request.get("weight", "bold")).lower() != "regular",
        align=request.get("align") or "left",
        text_size=_number(request.get("text_size"), 0) or None,
        icon_size=round(_number(request.get("icon_size"), 100)),
        language=request.get("language") or DEFAULT_LANGUAGE,
        icon_margin=_number(request.get("icon_margin"), MARGIN_MM),
        text_margin=_number(request.get("text_margin"), MARGIN_MM),
        gap=_number(request.get("gap"), GAP_MM),
        image_position=request.get("image_position") or "left",
    )
