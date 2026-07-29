from __future__ import annotations

from fpbench.core.serialization import stable_hash, to_plain


def test_sets_are_serialized_in_a_stable_order():
    assert to_plain({"z", "a", "m"}) == ["a", "m", "z"]
    assert stable_hash({"z", "a", "m"}) == stable_hash({"m", "z", "a"})
