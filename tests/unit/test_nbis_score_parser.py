"""BOZORTH3's one line of output, at every boundary the spec names (section 42).

The failure modes here are quiet ones. ``score=42`` means somebody added a flag,
two lines mean the tool ran in a mode this route did not ask for, and an empty
stdout means the comparison did not happen — none of which would look wrong in a
stored result if the parser were lenient.

``0`` is the case the whole module is arranged around: it is a score BOZORTH3
prints deliberately, and turning it into ``NO_SCORE`` would delete real outcomes
from a run.
"""

from __future__ import annotations

import pytest

from fpbench.adapters.nbis.score import (
    MAX_EXACT_INTEGER_SCORE,
    ScoreFormatError,
    parse_bozorth3_score,
)

pytestmark = pytest.mark.nbis_contract


# --------------------------------------------------------------- accepted


@pytest.mark.parametrize("text", ["0\n", "0", " 0 \n", "0\r\n"])
def test_zero_is_a_score(text):
    """Not a failure and never NO_SCORE (docs/adr/0006, spec section 26)."""
    assert parse_bozorth3_score(text) == 0


@pytest.mark.parametrize("text", ["42\n", "42", "42\n\n", "\n42\n"])
def test_an_ordinary_score_is_read(text):
    assert parse_bozorth3_score(text) == 42


def test_one_is_a_score():
    assert parse_bozorth3_score("1\n") == 1


def test_the_largest_exactly_storable_score_is_accepted():
    assert parse_bozorth3_score(f"{MAX_EXACT_INTEGER_SCORE}\n") == MAX_EXACT_INTEGER_SCORE


# --------------------------------------------------------------- rejected


@pytest.mark.parametrize(
    "text",
    ["", "\n", "   \n"],
    ids=["nothing", "one-newline", "whitespace"],
)
def test_an_empty_stdout_is_no_score(text):
    with pytest.raises(ScoreFormatError, match="printed nothing"):
        parse_bozorth3_score(text)


def test_two_lines_are_refused():
    with pytest.raises(ScoreFormatError, match="2 lines"):
        parse_bozorth3_score("42\n7\n")


@pytest.mark.parametrize(
    "text",
    [
        "score=42\n",
        "42.0\n",
        "NaN\n",
        "-1\n",
        "42 left.xyt right.xyt\n",
        "42 \tsomething\n",
        "0x2a\n",
        "٤٢\n",
    ],
    ids=[
        "labelled",
        "float",
        "not-a-number",
        "negative",
        "filenames-beside-it",
        "trailing-text",
        "hexadecimal",
        "non-ascii-digits",
    ],
)
def test_anything_other_than_one_integer_is_refused(text):
    with pytest.raises(ScoreFormatError):
        parse_bozorth3_score(text)


def test_a_value_too_large_to_store_exactly_is_refused():
    with pytest.raises(ScoreFormatError, match="too large"):
        parse_bozorth3_score(f"{MAX_EXACT_INTEGER_SCORE + 1}\n")


def test_the_excerpt_is_short_and_single_line():
    """A rogue stdout must not end up as a megabyte in a stored row."""
    with pytest.raises(ScoreFormatError) as raised:
        parse_bozorth3_score("x" * 10_000 + "\n" + "y" * 10_000 + "\n")
    assert "\n" not in raised.value.excerpt
    assert len(raised.value.excerpt) <= 200
