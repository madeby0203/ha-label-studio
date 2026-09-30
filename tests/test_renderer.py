import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "label_studio"))
import label_renderer


def _ink_outside_margin(image):
    margin = label_renderer.MARGIN
    inner = image.crop((margin, margin, image.width - margin, image.height - margin))
    return image.histogram()[0] - inner.histogram()[0]


def test_requested_sizes_are_300_dpi_and_monochrome():
    for label_id, expected in (("99010", (1050, 329)), ("11354", (675, 375))):
        image = label_renderer.render_label(
            lines=["Milk", "Use first"],
            label_size=label_id,
            date_text="2026-09-29",
            qr_text="https://example.test/milk",
        )
        assert image.mode == "1"
        assert image.size == expected
        assert len(image.getcolors()) > 1


def test_unknown_size_is_rejected():
    with pytest.raises(ValueError, match="Unknown label size"):
        label_renderer.render_label(lines=["test"], label_size="unknown")


@pytest.mark.parametrize("lines", [
    ["Short"],
    ["A much longer line of text that has to wrap over several rows to fit on the label"],
    ["Supercalifragilisticexpialidociousandevenlongerwordthatcannotfit"],
    ["word " * 800],
])
@pytest.mark.parametrize("label_size", sorted(label_renderer.LABEL_SIZES))
def test_text_never_reaches_the_margin(lines, label_size):
    image = label_renderer.render_label(lines=lines, label_size=label_size, qr_text="https://example.test")
    assert _ink_outside_margin(image) == 0


@pytest.mark.parametrize("family", sorted(label_renderer.FONT_FAMILIES))
def test_whole_words_are_kept_together_when_they_fit(family):
    # Wide enough for the word at a comfortable size in any font, so it must not be hyphenated.
    lines = label_renderer._layout_text([("Batteries", 1.0)], 800, 300, label_renderer.TextStyle(family=family))
    assert [line.text for line in lines] == ["Batteries"]


def test_overflowing_text_is_cut_with_an_ellipsis():
    lines = label_renderer._layout_text([("word " * 5000, 1.0)], 200, 100, label_renderer.TextStyle())
    assert lines[-1].text.endswith("…")
    assert sum(line.height for line in lines) <= 100


def test_unknown_mdi_icon_is_reported():
    with pytest.raises(ValueError, match="Unknown icon"):
        label_renderer.render_label(lines=["x"], icon="mdi:definitely-not-an-icon")


def test_long_words_are_hyphenated_at_syllables():
    font = label_renderer._text_font(label_renderer.DEFAULT_FONT, True, 60)
    width = round(font.getlength("kerstver-"))
    lines = label_renderer._wrap("kerstversiering", font, width, True, "nl_NL")
    assert lines[0].endswith("-") and "".join(line.rstrip("-") for line in lines) == "kerstversiering"
    assert all(font.getlength(line) <= width for line in lines)


def test_existing_hyphens_are_used_without_doubling():
    font = label_renderer._text_font(label_renderer.DEFAULT_FONT, True, 60)
    head, tail = label_renderer._split_word("Wi-Fi", font, font.getlength("Wi-"), "en_US")
    assert (head, tail) == ("Wi-", "Fi")


def test_a_long_word_is_hyphenated_instead_of_shrunk():
    word = "Supercalifragilisticexpialidocious"
    style = label_renderer.TextStyle(language="en_US")
    lines = label_renderer._layout_text([(word, 1.0)], 400, 300, style)
    assert len(lines) > 1 and lines[0].text.endswith("-")
    assert lines[0].font.size > 300 * label_renderer.HYPHENATE_BELOW


def test_fixed_text_size_is_a_maximum():
    style = label_renderer.TextStyle()
    lines = label_renderer._layout_text([("Milk", 1.0)], 600, 300, style, size=50)
    assert lines[0].font.size == 50


def test_icon_size_leaves_more_room_for_text():
    full = label_renderer.render_label(lines=["x"], icon="🥛", icon_size=100)
    small = label_renderer.render_label(lines=["x"], icon="🥛", icon_size=40)
    ink = lambda image: image.histogram()[0]
    assert ink(small) != ink(full)


def test_text_margin_is_kept_clear():
    image = label_renderer.render_label(lines=["word " * 200], text_margin=6)
    edge = label_renderer.mm(6)
    inner = image.crop((edge, edge, image.width - edge, image.height - edge))
    assert image.histogram()[0] == inner.histogram()[0]


def test_smaller_icon_margin_allows_a_larger_icon():
    tight = label_renderer.render_label(lines=[], icon="mdi:fridge", icon_margin=0.5)
    loose = label_renderer.render_label(lines=[], icon="mdi:fridge", icon_margin=6)
    assert tight.histogram()[0] > loose.histogram()[0]


def test_catalogue_matches_the_labelwriter_driver():
    sizes = label_renderer.LABEL_SIZES
    assert len(sizes) > 50
    assert sizes["11354"].ppd == "w162h90" and not sizes["11354"].feeds_along_width
    assert sizes["99010"].ppd == "w79h252.2" and sizes["99010"].feeds_along_width
    assert len({size.ppd for size in sizes.values()}) == len(sizes)
    for size in sizes.values():
        image = label_renderer.render_label(lines=["Test"], label_size=size.id)
        assert image.size == size.pixels and image.width >= image.height


def _ink_box(image, box):
    return image.crop(box).histogram()[0]


@pytest.mark.parametrize("position", label_renderer.IMAGE_POSITIONS)
def test_image_is_placed_on_the_chosen_side(position):
    image = label_renderer.render_label(lines=["Milk"], icon="mdi:fridge", image_position=position)
    w, h = image.size
    halves = {"left": (0, 0, w // 2, h), "right": (w // 2, 0, w, h), "top": (0, 0, w, h // 2), "bottom": (0, h // 2, w, h)}
    opposite = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[position]
    # The icon is a solid block of ink, so its half holds much more black than the text's half.
    assert _ink_box(image, halves[position]) > _ink_box(image, halves[opposite])


def test_a_label_shows_an_icon_or_a_qr_code_never_both():
    both = label_renderer.render_request({"text": "x", "icon": "mdi:fridge", "qr": "https://example.test"})
    icon_only = label_renderer.render_request({"text": "x", "icon": "mdi:fridge"})
    assert both.tobytes() == icon_only.tobytes()
    qr = label_renderer.render_request({"text": "x", "icon": "mdi:fridge", "qr": "https://example.test", "graphic": "qr"})
    qr_only = label_renderer.render_request({"text": "x", "qr": "https://example.test"})
    assert qr.tobytes() == qr_only.tobytes()
    none = label_renderer.render_request({"text": "x", "icon": "mdi:fridge", "qr": "y", "graphic": ""})
    assert none.tobytes() == label_renderer.render_request({"text": "x"}).tobytes()
