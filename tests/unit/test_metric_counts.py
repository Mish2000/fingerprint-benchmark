"""The count models refuse arithmetic that would corrupt a denominator.

Every rate in stage 5B divides one of these numbers by another, so an invariant
that held "usually" would produce percentages that are wrong in a way no reader
could see. These are the cheapest tests in the suite and they guard the most.
"""

from __future__ import annotations

import pytest

from fpbench.core.metric_models import (
    ConditionalOutcomeCounts,
    CountFamily,
    DecisionOutcomeCounts,
    EligibilityOutcomeCounts,
    EvaluationCountRecord,
    MetricScope,
    MetricScopeKind,
    count_record_hash,
)

pytestmark = pytest.mark.metrics

DIGEST = "a" * 64


def test_decision_counts_accept_a_consistent_tally() -> None:
    counts = DecisionOutcomeCounts(
        total_attempts=10,
        decided_attempts=9,
        match_count=8,
        non_match_count=1,
        undecidable_count=1,
    )
    assert counts.non_success_count == 2
    assert counts.as_mapping() == {
        "match": 8,
        "non_match": 1,
        "undecidable": 1,
        "decided": 9,
    }


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        DecisionOutcomeCounts(
            total_attempts=10,
            decided_attempts=10,
            match_count=11,
            non_match_count=-1,
            undecidable_count=0,
        )


def test_total_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="decided or undecidable"):
        DecisionOutcomeCounts(
            total_attempts=10,
            decided_attempts=9,
            match_count=8,
            non_match_count=1,
            undecidable_count=0,
        )


def test_decided_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="match or a non-match"):
        DecisionOutcomeCounts(
            total_attempts=10,
            decided_attempts=9,
            match_count=8,
            non_match_count=0,
            undecidable_count=1,
        )


def test_eligibility_total_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="eligible, ineligible or undetermined"):
        EligibilityOutcomeCounts(
            total_units=10,
            eligible_count=6,
            ineligible_count=3,
            undetermined_count=0,
        )


def test_conditional_inclusion_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="included or excluded"):
        ConditionalOutcomeCounts(
            total_rows=10,
            included_count=6,
            excluded_ineligible_count=3,
            excluded_undetermined_count=0,
            included_decided_count=6,
            included_match_count=5,
            included_non_match_count=1,
            included_undecidable_count=0,
        )


def test_conditional_decided_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="match or a non-match"):
        ConditionalOutcomeCounts(
            total_rows=10,
            included_count=6,
            excluded_ineligible_count=3,
            excluded_undetermined_count=1,
            included_decided_count=6,
            included_match_count=5,
            included_non_match_count=0,
            included_undecidable_count=0,
        )


def test_counts_add_componentwise() -> None:
    left = DecisionOutcomeCounts(
        total_attempts=10,
        decided_attempts=9,
        match_count=8,
        non_match_count=1,
        undecidable_count=1,
    )
    right = DecisionOutcomeCounts(
        total_attempts=5,
        decided_attempts=5,
        match_count=5,
        non_match_count=0,
        undecidable_count=0,
    )
    total = left + right
    assert (total.total_attempts, total.decided_attempts) == (15, 14)
    assert (total.match_count, total.non_match_count, total.undecidable_count) == (
        13,
        1,
        1,
    )


# ------------------------------------------------------------- count records


def _record(**overrides) -> EvaluationCountRecord:
    fields = {
        "ordinal": 0,
        "count_family": CountFamily.PLAIN_SELF,
        "scope": MetricScope(MetricScopeKind.RELEASE, "SD300A"),
        "total_count": 10,
        "counts": {"match": 8, "non_match": 1, "undecidable": 1, "decided": 9},
        "source_fingerprint": DIGEST,
    }
    fields.update(overrides)

    class _Probe:
        def __init__(self, values):
            for name, value in values.items():
                setattr(self, name, value)

    probe = _Probe(fields)
    return EvaluationCountRecord(count_record_hash=count_record_hash(probe), **fields)


def test_count_record_enforces_the_family_invariants_after_a_round_trip() -> None:
    # The record is built from a flat mapping, so the dataclass invariants have
    # to be re-run over it rather than assumed to have happened upstream.
    with pytest.raises(ValueError, match="decided or undecidable"):
        _record(counts={"match": 8, "non_match": 1, "undecidable": 0, "decided": 9})


def test_count_record_rejects_a_count_its_family_does_not_define() -> None:
    with pytest.raises(ValueError, match="does not define a count"):
        _record(
            counts={
                "match": 8,
                "non_match": 1,
                "undecidable": 1,
                "decided": 9,
                "included": 6,
            }
        )


def test_count_record_rejects_a_missing_count() -> None:
    with pytest.raises(ValueError, match="missing counts"):
        _record(counts={"match": 8, "non_match": 1, "undecidable": 1})


def test_count_record_mapping_is_defensively_frozen() -> None:
    mutable = {"match": 8, "non_match": 1, "undecidable": 1, "decided": 9}
    record = _record(counts=mutable)
    mutable["match"] = 999
    assert record.get("match") == 8
    with pytest.raises(TypeError):
        record.counts["match"] = 0  # type: ignore[index]


def test_pooled_scope_must_not_name_a_release() -> None:
    with pytest.raises(ValueError, match="must not name a release"):
        MetricScope(MetricScopeKind.POOLED, "SD300A")


def test_release_scope_must_name_one() -> None:
    with pytest.raises(ValueError, match="must name its release"):
        MetricScope(MetricScopeKind.RELEASE, None)
