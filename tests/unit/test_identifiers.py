from __future__ import annotations

import pytest

from fpbench.core.identifiers import InvalidIdentifierError, compose_id, validate_id


def test_composes_lowercase_segments():
    assert compose_id("SD300A", "00001000", "plain", "f01") == "sd300a_00001000_plain_f01"


def test_empty_segments_are_dropped():
    assert compose_id("a", "", "b") == "a_b"


@pytest.mark.parametrize("value", ["a b", "a__b", "_a", "a-", "A", "a.b", ""])
def test_rejects_values_that_are_unsafe_as_path_components(value):
    with pytest.raises(InvalidIdentifierError):
        validate_id(value)
