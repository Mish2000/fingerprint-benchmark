"""The four-line function everything else in the stage rests on.

A threshold comparison is trivial to write and easy to get subtly wrong: an
epsilon "for safety", a round to two places "to match the report", a float
threshold that is not quite the number in the config. Each of those moves the
boundary by an amount nobody wrote down, and each would change which fingers
are eligible.

So these tests pin the boundary exactly, and pin the *shape* of the function:
it takes a score and a profile, and there is no argument through which the
protocol stage or the ground truth could reach it (docs/adr/0010).
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from fpbench.core.decision_models import (
    DecisionProfile,
    ThresholdComparator,
    ThresholdOrigin,
    canonical_threshold,
)
from fpbench.core.enums import DecisionValue, ScoreDirection
from fpbench.core.errors import DecisionDerivationError, DecisionProfileError
from fpbench.decisions import build_decision_profile, decide_score

pytestmark = pytest.mark.decisions


def _profile(
    *,
    threshold: str = "40",
    direction: ScoreDirection = ScoreDirection.HIGHER_IS_BETTER,
    comparator: ThresholdComparator | None = None,
) -> DecisionProfile:
    return build_decision_profile(
        profile_id="test_profile_v1",
        display_name="Test",
        profile_version="1",
        origin=ThresholdOrigin.DOCUMENTED_NATIVE,
        algorithm_id="test_matcher",
        implementation_version="1",
        algorithm_fingerprint="a" * 64,
        score_direction=direction,
        comparator=comparator
        or (
            ThresholdComparator.GREATER_THAN_OR_EQUAL
            if direction is ScoreDirection.HIGHER_IS_BETTER
            else ThresholdComparator.LESS_THAN_OR_EQUAL
        ),
        threshold=threshold,
        source_kind="upstream_documentation",
        source_reference="test",
        source_version="1",
        allowed_execution_profiles=("identity_png_v1",),
        calibration_performed=False,
        calibration_manifest_fingerprint=None,
        metadata={},
    )


# ------------------------------------------------------------- the boundary


@pytest.mark.parametrize(
    "score, expected",
    [
        (39.999999, DecisionValue.NON_MATCH),
        (39.99999999999999, DecisionValue.NON_MATCH),
        (40.0, DecisionValue.MATCH),
        (40.000001, DecisionValue.MATCH),
        (0.0, DecisionValue.NON_MATCH),
        (1e6, DecisionValue.MATCH),
    ],
)
def test_the_boundary_is_exactly_where_the_profile_puts_it(score, expected):
    assert decide_score(score=score, profile=_profile()) is expected


def test_a_score_equal_to_the_threshold_matches():
    """``>=`` means what it says. Forty is a match."""
    assert decide_score(score=40.0, profile=_profile()) is DecisionValue.MATCH


def test_nothing_is_rounded_before_comparing():
    """39.6 would match if anyone rounded to units. Nobody does."""
    assert decide_score(score=39.6, profile=_profile()) is DecisionValue.NON_MATCH
    assert decide_score(score=39.5, profile=_profile()) is DecisionValue.NON_MATCH


def test_there_is_no_epsilon():
    tiny = 40.0 - 1e-12
    assert decide_score(score=tiny, profile=_profile()) is DecisionValue.NON_MATCH


def test_a_lower_is_better_profile_compares_the_other_way():
    profile = _profile(direction=ScoreDirection.LOWER_IS_BETTER)
    assert decide_score(score=39.0, profile=profile) is DecisionValue.MATCH
    assert decide_score(score=40.0, profile=profile) is DecisionValue.MATCH
    assert decide_score(score=41.0, profile=profile) is DecisionValue.NON_MATCH


# -------------------------------------------------------------- non-numbers


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_score_is_refused_rather_than_classified(score):
    """A NaN is the absence of a score, not a low one."""
    with pytest.raises(DecisionDerivationError, match="finite"):
        decide_score(score=score, profile=_profile())


# ------------------------------------------------------------- determinism


def test_the_same_input_always_produces_the_same_decision():
    profile = _profile()
    first = [decide_score(score=41.5, profile=profile) for _ in range(50)]
    assert len(set(first)) == 1


def test_the_function_cannot_be_told_what_the_pair_is():
    """docs/adr/0010, checked mechanically.

    There is no parameter through which a protocol stage, a ground truth or a
    subject could reach the comparison, so a decision cannot depend on knowing
    the answer.
    """
    parameters = set(inspect.signature(decide_score).parameters)
    assert parameters == {"score", "profile"}
    forbidden = {"stage", "protocol_stage", "ground_truth", "pair", "pair_id", "truth"}
    assert forbidden.isdisjoint(parameters)


# ----------------------------------------------------------- canonicalisation


@pytest.mark.parametrize(
    "written, canonical",
    [
        ("40", "40"),
        ("40.0", "40"),
        ("40.00", "40"),
        ("4e1", "40"),
        ("+40", "40"),
        (" 40 ", "40"),
        ("40.5", "40.5"),
        ("40.50", "40.5"),
        ("0", "0"),
        ("0.0", "0"),
        ("-3.20", "-3.2"),
        (Decimal("40"), "40"),
        (40, "40"),
    ],
)
def test_thresholds_canonicalise_deterministically(written, canonical):
    assert canonical_threshold(written) == canonical


@pytest.mark.parametrize("written", ["NaN", "nan", "Infinity", "-Infinity", "inf"])
def test_a_non_finite_threshold_is_refused(written):
    with pytest.raises(DecisionProfileError):
        canonical_threshold(written)


@pytest.mark.parametrize("written", ["", "   ", "forty", "4o", "40,0"])
def test_an_unparseable_threshold_is_refused(written):
    with pytest.raises(DecisionProfileError):
        canonical_threshold(written)


def test_two_spellings_of_one_threshold_produce_one_fingerprint():
    assert (
        _profile(threshold="40").profile_fingerprint
        == _profile(threshold="40.0").profile_fingerprint
    )


def test_a_different_threshold_produces_a_different_fingerprint():
    assert (
        _profile(threshold="40").profile_fingerprint
        != _profile(threshold="41").profile_fingerprint
    )
