"""The XYT parser, at every boundary the spec names (section 42).

An extractor's output file is the entire interface between the two halves of this
route, and the interesting cases are all near-misses: three columns instead of
four, a float where an integer belongs, a theta one degree past the wrap. Each
one is a file BOZORTH3 might make some sense of and MINDTCT would never have
written.

The one case that is *not* an error is the empty file. MINDTCT finding nothing is
a fact about the print, and BOZORTH3 scores such a pair 0 quite happily.
"""

from __future__ import annotations

import pytest

from fpbench.adapters.nbis.xyt import (
    MAX_LINE_CHARS,
    MAX_MINUTIAE,
    QUALITY_MAX,
    QUALITY_MIN,
    THETA_MAX,
    THETA_MIN,
    NbisMinutia,
    XytFormatError,
    parse_xyt,
    read_xyt,
)

pytestmark = pytest.mark.nbis_contract


def line(x: int = 10, y: int = 20, theta: int = 30, quality: int = 40) -> str:
    return f"{x} {y} {theta} {quality}\n"


# --------------------------------------------------------------- accepted


def test_an_empty_file_is_a_template_with_no_minutiae():
    """Not a failure: NBIS looked and found nothing (spec section 27)."""
    assert parse_xyt("") == ()


def test_whitespace_only_is_also_empty():
    assert parse_xyt("\n\n   \n") == ()


def test_one_well_formed_line_is_one_minutia():
    assert parse_xyt(line(1, 2, 3, 4)) == (NbisMinutia(x=1, y=2, theta=3, quality=4),)


def test_a_file_without_a_trailing_newline_still_parses():
    assert len(parse_xyt("1 2 3 4")) == 1


def test_the_extreme_legal_values_are_accepted():
    text = line(0, 0, THETA_MIN, QUALITY_MIN) + line(5, 5, THETA_MAX, QUALITY_MAX)
    assert len(parse_xyt(text)) == 2


def test_exactly_the_maximum_number_of_minutiae_is_accepted():
    assert len(parse_xyt(line() * MAX_MINUTIAE)) == MAX_MINUTIAE


# --------------------------------------------------------------- rejected


def test_one_more_than_the_maximum_is_refused():
    with pytest.raises(XytFormatError, match="more than"):
        parse_xyt(line() * (MAX_MINUTIAE + 1))


@pytest.mark.parametrize(
    "text",
    [
        "1 2 3\n",
        "1 2 3 4 5\n",
        "1 2 3 4.0\n",
        "1.5 2 3 4\n",
        "1 2 3 four\n",
        "1 2 3 +4\n",
        "1 2 3 0x4\n",
        "1 2 3 4_0\n",
    ],
    ids=[
        "three-columns",
        "five-columns",
        "float-quality",
        "float-x",
        "word",
        "explicit-sign",
        "hexadecimal",
        "underscore-separator",
    ],
)
def test_a_line_that_is_not_four_integers_is_refused(text):
    with pytest.raises(XytFormatError) as raised:
        parse_xyt(text)
    assert raised.value.kind == "invalid_extractor_output"


@pytest.mark.parametrize(
    "text",
    [line(-1, 2), line(1, -2)],
    ids=["negative-x", "negative-y"],
)
def test_a_negative_coordinate_is_refused(text):
    with pytest.raises(XytFormatError, match="negative"):
        parse_xyt(text)


@pytest.mark.parametrize("theta", [THETA_MIN - 1, THETA_MAX + 1, 3600])
def test_a_theta_outside_the_format_is_refused(theta):
    with pytest.raises(XytFormatError, match="theta"):
        parse_xyt(line(theta=theta))


@pytest.mark.parametrize("quality", [QUALITY_MIN - 1, QUALITY_MAX + 1, 1000])
def test_a_quality_outside_the_format_is_refused(quality):
    with pytest.raises(XytFormatError, match="quality"):
        parse_xyt(line(quality=quality))


def test_a_nul_byte_is_refused():
    with pytest.raises(XytFormatError, match="NUL"):
        parse_xyt("1 2 3 4\n\x00\n")


def test_an_unreasonably_long_line_is_refused():
    padded = " " * (MAX_LINE_CHARS + 1) + "1 2 3 4\n"
    with pytest.raises(XytFormatError, match="long"):
        parse_xyt(padded)


# ------------------------------------------------------------ raster bounds


def test_a_minutia_outside_the_raster_is_refused():
    with pytest.raises(XytFormatError, match="horizontally"):
        parse_xyt(line(x=300), image_width=250, image_height=250)
    with pytest.raises(XytFormatError, match="vertically"):
        parse_xyt(line(y=300), image_width=250, image_height=250)


def test_the_last_pixel_is_inside_the_raster():
    assert len(parse_xyt(line(x=249, y=249), image_width=250, image_height=250)) == 1


def test_bounds_are_only_checked_when_they_are_known():
    """``None`` skips the check rather than inventing a raster size."""
    assert len(parse_xyt(line(x=99999, y=99999))) == 1


# -------------------------------------------------------------- the file


def test_a_missing_file_is_missing_output(tmp_path):
    with pytest.raises(XytFormatError) as raised:
        read_xyt(tmp_path / "absent.xyt")
    assert raised.value.kind == "missing_extractor_output"


def test_a_directory_is_not_a_template(tmp_path):
    directory = tmp_path / "left-nbis.xyt"
    directory.mkdir()
    with pytest.raises(XytFormatError, match="regular file"):
        read_xyt(directory)


def test_a_symlinked_template_is_refused(tmp_path):
    target = tmp_path / "real.xyt"
    target.write_text("1 2 3 4\n", encoding="ascii")
    link = tmp_path / "link.xyt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    with pytest.raises(XytFormatError, match="symlink"):
        read_xyt(link)


def test_a_hard_linked_template_is_refused(tmp_path):
    target = tmp_path / "real.xyt"
    target.write_text("1 2 3 4\n", encoding="ascii")
    link = tmp_path / "hard.xyt"
    try:
        import os

        os.link(target, link)
    except (OSError, NotImplementedError, AttributeError):  # pragma: no cover
        pytest.skip("this platform will not create hard links")
    with pytest.raises(XytFormatError, match="hard links"):
        read_xyt(link)


def test_a_non_ascii_template_is_refused(tmp_path):
    path = tmp_path / "left-nbis.xyt"
    path.write_bytes(b"1 2 3 4\n\xff\xfe\n")
    with pytest.raises(XytFormatError, match="ASCII"):
        read_xyt(path)


def test_an_empty_file_on_disk_reads_as_no_minutiae(tmp_path):
    path = tmp_path / "left-nbis.xyt"
    path.write_bytes(b"")
    assert read_xyt(path) == ()


def test_the_parser_does_not_reorder_or_deduplicate(tmp_path):
    """This project carries NBIS's output; it does not filter it (section 7)."""
    text = line(9, 9, 9, 9) + line(1, 1, 1, 1) + line(9, 9, 9, 9)
    parsed = parse_xyt(text)
    assert [item.x for item in parsed] == [9, 1, 9]
