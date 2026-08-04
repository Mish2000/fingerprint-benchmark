"""Four comparators, one boundary each, and a legacy grammar that did not move.

Stage 7D needs a strict rule, because NIST's guide describes a BOZORTH3 score
*greater than* 40 as usually indicating a true match while SourceAFIS documents
a score *of at least* 40. Two different sentences; the project now has two
different comparators rather than one comparator and a convention.

Everything here is about the score that sits exactly on the threshold, because
that is the only score the four comparators disagree about, and it is exactly
the score a float, an epsilon or a rounding step would decide instead of the
profile (docs/adr/0055, spec sections 14, 16, 17 and 18).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fpbench.core.decision_models import (
    DECISION_PROFILE_SCHEMA_VERSION,
    DECISION_PROFILE_SCHEMA_VERSIONS,
    DecisionProfile,
    ThresholdComparator,
    ThresholdOrigin,
    comparators_for,
    decision_profile_fingerprint,
)
from fpbench.core.enums import DecisionValue, ScoreDirection
from fpbench.core.errors import DecisionProfileError
from fpbench.decisions import build_decision_profile, decide_score

pytestmark = [pytest.mark.decisions, pytest.mark.stage7d_contract]


def _profile(
    *,
    comparator: ThresholdComparator,
    schema_version: str = "2",
    threshold: str = "40",
    direction: ScoreDirection | None = None,
    **overrides,
) -> DecisionProfile:
    if direction is None:
        direction = (
            ScoreDirection.LOWER_IS_BETTER
            if comparator
            in (ThresholdComparator.LESS_THAN, ThresholdComparator.LESS_THAN_OR_EQUAL)
            else ScoreDirection.HIGHER_IS_BETTER
        )
    fields = {
        "schema_version": schema_version,
        "profile_id": "test_profile_v1",
        "display_name": "Test",
        "profile_version": "1",
        "origin": ThresholdOrigin.DOCUMENTED_NATIVE,
        "algorithm_id": "test_matcher",
        "implementation_version": "1",
        "algorithm_fingerprint": "a" * 64,
        "score_direction": direction,
        "comparator": comparator,
        "threshold": threshold,
        "source_kind": "upstream_documentation",
        "source_reference": "test",
        "source_version": "1",
        "allowed_execution_profiles": ("identity_png_v1",),
        "calibration_performed": False,
        "calibration_manifest_fingerprint": None,
        "metadata": {},
    }
    fields.update(overrides)
    return build_decision_profile(**fields)


# ------------------------------------------------------------- the boundary
#
# The table the specification writes out in full (section 18), transcribed
# without simplification. 39, 40 and 41 against threshold 40, four comparators,
# twelve answers.

_BOUNDARY_CASES = [
    (ThresholdComparator.GREATER_THAN, 39, DecisionValue.NON_MATCH),
    (ThresholdComparator.GREATER_THAN, 40, DecisionValue.NON_MATCH),
    (ThresholdComparator.GREATER_THAN, 41, DecisionValue.MATCH),
    (ThresholdComparator.GREATER_THAN_OR_EQUAL, 39, DecisionValue.NON_MATCH),
    (ThresholdComparator.GREATER_THAN_OR_EQUAL, 40, DecisionValue.MATCH),
    (ThresholdComparator.GREATER_THAN_OR_EQUAL, 41, DecisionValue.MATCH),
    (ThresholdComparator.LESS_THAN, 39, DecisionValue.MATCH),
    (ThresholdComparator.LESS_THAN, 40, DecisionValue.NON_MATCH),
    (ThresholdComparator.LESS_THAN, 41, DecisionValue.NON_MATCH),
    (ThresholdComparator.LESS_THAN_OR_EQUAL, 39, DecisionValue.MATCH),
    (ThresholdComparator.LESS_THAN_OR_EQUAL, 40, DecisionValue.MATCH),
    (ThresholdComparator.LESS_THAN_OR_EQUAL, 41, DecisionValue.NON_MATCH),
]


@pytest.mark.parametrize("comparator, score, expected", _BOUNDARY_CASES)
def test_every_comparator_decides_the_boundary_as_written(comparator, score, expected):
    profile = _profile(comparator=comparator)
    assert decide_score(score=score, profile=profile) is expected


@pytest.mark.parametrize(
    "comparator, expected",
    [
        (ThresholdComparator.GREATER_THAN, DecisionValue.NON_MATCH),
        (ThresholdComparator.GREATER_THAN_OR_EQUAL, DecisionValue.MATCH),
        (ThresholdComparator.LESS_THAN, DecisionValue.NON_MATCH),
        (ThresholdComparator.LESS_THAN_OR_EQUAL, DecisionValue.MATCH),
    ],
)
def test_equality_at_the_threshold_is_settled_in_decimal(comparator, expected):
    """``40.0000000000000000`` is exactly 40, and is treated as exactly 40.

    Sixteen trailing zeros is the shape of a number that has been through a
    formatter, and the point of the case is that the formatting has no effect:
    the comparison is decimal, so the score either is the threshold or is not,
    and the comparator alone decides what that means (spec section 18).
    """
    profile = _profile(comparator=comparator)
    assert decide_score(score=40.0000000000000000, profile=profile) is expected
    assert Decimal(str(40.0000000000000000)) == profile.threshold_value


def test_the_two_greater_comparators_differ_only_at_the_threshold():
    strict = _profile(comparator=ThresholdComparator.GREATER_THAN)
    inclusive = _profile(comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL)
    for score in (0, 1, 39, 39.999999, 40.000001, 41, 1000):
        assert decide_score(score=score, profile=strict) is decide_score(
            score=score, profile=inclusive
        )
    assert decide_score(score=40, profile=strict) is DecisionValue.NON_MATCH
    assert decide_score(score=40, profile=inclusive) is DecisionValue.MATCH


def test_a_strict_comparator_has_no_epsilon_either():
    profile = _profile(comparator=ThresholdComparator.GREATER_THAN)
    assert decide_score(score=40 + 1e-12, profile=profile) is DecisionValue.MATCH
    assert decide_score(score=40 - 1e-12, profile=profile) is DecisionValue.NON_MATCH


def test_a_bozorth_score_of_zero_is_a_non_match_not_a_failure():
    """Spec section 30: 0 is a score, so it is decided, and it decides NON_MATCH."""
    profile = _profile(comparator=ThresholdComparator.GREATER_THAN)
    assert decide_score(score=0, profile=profile) is DecisionValue.NON_MATCH
    assert decide_score(score=0.0, profile=profile) is DecisionValue.NON_MATCH


# ------------------------------------------------------- direction and schema


@pytest.mark.parametrize(
    "schema_version, direction, comparator",
    [
        ("2", ScoreDirection.HIGHER_IS_BETTER, ThresholdComparator.LESS_THAN),
        (
            "2",
            ScoreDirection.HIGHER_IS_BETTER,
            ThresholdComparator.LESS_THAN_OR_EQUAL,
        ),
        ("2", ScoreDirection.LOWER_IS_BETTER, ThresholdComparator.GREATER_THAN),
        (
            "2",
            ScoreDirection.LOWER_IS_BETTER,
            ThresholdComparator.GREATER_THAN_OR_EQUAL,
        ),
    ],
)
def test_a_comparator_that_contradicts_the_score_direction_is_refused(
    schema_version, direction, comparator
):
    with pytest.raises(DecisionProfileError, match="inverts every decision"):
        _profile(
            comparator=comparator, direction=direction, schema_version=schema_version
        )


@pytest.mark.parametrize(
    "comparator", [ThresholdComparator.GREATER_THAN, ThresholdComparator.LESS_THAN]
)
def test_schema_one_refuses_a_strict_comparator(comparator):
    """Section 15: schema 1 is not quietly widened when schema 2 arrives."""
    with pytest.raises(DecisionProfileError, match="schema 2"):
        _profile(comparator=comparator, schema_version="1")


def test_schema_one_still_accepts_its_own_comparators():
    for comparator in (
        ThresholdComparator.GREATER_THAN_OR_EQUAL,
        ThresholdComparator.LESS_THAN_OR_EQUAL,
    ):
        assert _profile(comparator=comparator, schema_version="1").comparator is (
            comparator
        )


def test_the_allowed_comparator_tables_are_exactly_the_specified_ones():
    assert comparators_for("1", ScoreDirection.HIGHER_IS_BETTER) == frozenset(
        {ThresholdComparator.GREATER_THAN_OR_EQUAL}
    )
    assert comparators_for("1", ScoreDirection.LOWER_IS_BETTER) == frozenset(
        {ThresholdComparator.LESS_THAN_OR_EQUAL}
    )
    assert comparators_for("2", ScoreDirection.HIGHER_IS_BETTER) == frozenset(
        {ThresholdComparator.GREATER_THAN, ThresholdComparator.GREATER_THAN_OR_EQUAL}
    )
    assert comparators_for("2", ScoreDirection.LOWER_IS_BETTER) == frozenset(
        {ThresholdComparator.LESS_THAN, ThresholdComparator.LESS_THAN_OR_EQUAL}
    )


@pytest.mark.parametrize("version", ["0", "3", "2.0", "", "latest"])
def test_an_unknown_profile_schema_version_is_refused(version):
    with pytest.raises(DecisionProfileError, match="not supported"):
        _profile(
            comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL,
            schema_version=version,
        )


def test_a_profile_without_a_schema_version_is_read_as_schema_one():
    profile = build_decision_profile(
        profile_id="legacy_profile_v1",
        display_name="Legacy",
        profile_version="1",
        origin=ThresholdOrigin.DOCUMENTED_NATIVE,
        algorithm_id="test_matcher",
        implementation_version="1",
        algorithm_fingerprint="a" * 64,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL,
        threshold="40",
        source_kind="upstream_documentation",
        source_reference="test",
        source_version="1",
        allowed_execution_profiles=("identity_png_v1",),
        calibration_performed=False,
        calibration_manifest_fingerprint=None,
        metadata={},
    )
    assert profile.schema_version == DECISION_PROFILE_SCHEMA_VERSION == "1"


# ----------------------------------------------------------- the fingerprints


def test_the_two_schemas_fingerprint_differently_for_identical_content():
    """Section 15: schema 2 gets a mapping of its own.

    Same algorithm, same threshold, same inclusive comparator, same everything —
    and still two identities, because a schema-2 profile was read under a grammar
    in which ``greater_than`` was a possibility and a schema-1 profile was not.
    """
    schema_one = _profile(
        comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL, schema_version="1"
    )
    schema_two = _profile(
        comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL, schema_version="2"
    )
    assert schema_one.profile_fingerprint != schema_two.profile_fingerprint


def test_a_strict_profile_does_not_collide_with_its_inclusive_twin():
    strict = _profile(comparator=ThresholdComparator.GREATER_THAN)
    inclusive = _profile(comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL)
    assert strict.profile_fingerprint != inclusive.profile_fingerprint


def test_the_schema_one_fingerprint_mapping_is_byte_for_byte_what_it_was():
    """The exact digest four published SourceAFIS artefacts were derived under.

    Recomputed here from a literal, so that a future edit to the mapping — a
    field added, a tag renamed, the schema version read from somewhere else —
    fails this test rather than silently invalidating
    ``decisionset_0122544e71b1`` and ``decisionset_df0d584bdede``.
    """
    from fpbench.core.serialization import stable_hash

    profile = _profile(
        comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL, schema_version="1"
    )
    expected = stable_hash(
        {
            "schema": "decision_profile_fingerprint_v1",
            "decision_profile_schema_version": "1",
            "profile_id": "test_profile_v1",
            "profile_version": "1",
            "algorithm_id": "test_matcher",
            "implementation_version": "1",
            "algorithm_fingerprint": "a" * 64,
            "score_direction": "higher_is_better",
            "comparator": "greater_than_or_equal",
            "threshold": "40",
            "origin": "documented_native",
            "source_kind": "upstream_documentation",
            "source_reference": "test",
            "source_version": "1",
            "allowed_execution_profiles": ["identity_png_v1"],
            "calibration_performed": False,
            "calibration_manifest_fingerprint": None,
            "metadata": {},
        },
        length=64,
    )
    assert profile.profile_fingerprint == expected
    assert decision_profile_fingerprint(profile) == expected


def test_the_schema_version_is_one_of_exactly_two():
    assert DECISION_PROFILE_SCHEMA_VERSIONS == ("1", "2")


def test_strictness_is_a_property_of_the_comparator_not_of_the_caller():
    assert ThresholdComparator.GREATER_THAN.is_strict is True
    assert ThresholdComparator.LESS_THAN.is_strict is True
    assert ThresholdComparator.GREATER_THAN_OR_EQUAL.is_strict is False
    assert ThresholdComparator.LESS_THAN_OR_EQUAL.is_strict is False
