from __future__ import annotations

import pytest

from fpbench.core.enums import Impression
from fpbench.datasets.sd300.filenames import (
    FilenameParseError,
    parse_filename,
    try_parse,
)


def test_parses_a_plain_name():
    parsed = parse_filename("00001000_plain_500_11.png")
    assert parsed.subject == "00001000"
    assert parsed.impression is Impression.PLAIN
    assert parsed.ppi == 500
    assert parsed.frgp == 11
    assert parsed.extension == "png"


def test_parses_a_roll_name_at_2000_ppi():
    parsed = parse_filename("00001859_roll_2000_01.png")
    assert parsed.impression is Impression.ROLL
    assert parsed.ppi == 2000
    assert parsed.frgp == 1


def test_round_trips_through_str():
    assert str(parse_filename("00001000_roll_1000_09.png")) == "00001000_roll_1000_09.png"


@pytest.mark.parametrize(
    "name",
    [
        "checksum_500_png_plain.csv",
        "00001000_plain_500.png",
        "00001000_slap_500_11.png",
        "00001000_plain_500_11",
        "segmentation_coordinates_500.csv",
    ],
)
def test_rejects_names_that_are_not_images(name):
    assert try_parse(name) is None
    with pytest.raises(FilenameParseError):
        parse_filename(name)
