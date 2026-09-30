import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "dymo-labels"))
import label_renderer


def test_requested_sizes_are_300_dpi_and_monochrome():
    for label_id, expected in (("99010", (1051, 331)), ("11354", (673, 378))):
        image = label_renderer.render_label(
            lines=["Milk", "Use first"],
            label_size=label_id,
            icon="mdi:fridge",
            emoji="🥛",
            date_text="2026-09-29",
            qr_text="https://example.test/milk",
        )
        assert image.mode == "1"
        assert image.size == expected
        assert len(image.getcolors()) > 1


def test_unknown_size_is_rejected():
    try:
        label_renderer.render_label(lines=["test"], label_size="unknown")
    except ValueError as error:
        assert "Unknown label size" in str(error)
    else:
        raise AssertionError("unknown sizes must fail")