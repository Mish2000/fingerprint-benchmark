"""An observation is two integers and their provenance, and it hashes over both.

The hash is what makes a metric set tamper-evident, so these tests move one
field at a time and assert the hash notices. Scope is included deliberately:
relabelling an SD300A observation as SD300B changes no count and is exactly the
kind of edit that would otherwise survive.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import MetricObservationStatus, MetricScopeKind
from fpbench.core.metric_models import (
    MetricObservation,
    MetricScope,
    fraction_text,
    metric_observation_hash,
)

pytestmark = pytest.mark.metrics

DECISIONS = "a" * 64
ELIGIBILITY = "b" * 64
VIEW = "c" * 64
POLICY = "d" * 64


class _Probe:
    def __init__(self, fields):
        for name, value in fields.items():
            setattr(self, name, value)


def _observation(**overrides) -> MetricObservation:
    fields = {
        "ordinal": 0,
        "metric_id": "plain_self_match_rate_decided",
        "scope": MetricScope(MetricScopeKind.RELEASE, "SD300A"),
        "numerator_count": 8,
        "denominator_count": 9,
        "status": MetricObservationStatus.DEFINED,
        "source_decision_set_fingerprint": DECISIONS,
        "source_eligibility_set_fingerprint": ELIGIBILITY,
        "source_view_fingerprint": VIEW,
        "metric_policy_fingerprint": POLICY,
    }
    fields.update(overrides)
    fields.setdefault(
        "fraction_text",
        fraction_text(fields["numerator_count"], fields["denominator_count"]),
    )
    probe = _Probe(fields)
    return MetricObservation(
        observation_hash=metric_observation_hash(probe), **fields
    )


def test_fraction_text_must_match_the_counts() -> None:
    with pytest.raises(ValueError, match="the integers are the authority"):
        _observation(fraction_text="8/10")


def test_a_defined_observation_requires_a_positive_denominator() -> None:
    with pytest.raises(ValueError, match="needs something to divide by"):
        _observation(
            numerator_count=0,
            denominator_count=0,
            status=MetricObservationStatus.DEFINED,
            fraction_text=None,
        )


def test_an_undefined_observation_requires_a_zero_denominator() -> None:
    with pytest.raises(ValueError, match="undefined only when"):
        _observation(status=MetricObservationStatus.UNDEFINED_ZERO_DENOMINATOR)


def test_an_undefined_observation_carries_no_fraction() -> None:
    observation = _observation(
        numerator_count=0,
        denominator_count=0,
        status=MetricObservationStatus.UNDEFINED_ZERO_DENOMINATOR,
    )
    assert observation.fraction_text is None
    assert observation.percentage(decimal_places=4) is None


def test_an_undefined_observation_counts_nothing() -> None:
    with pytest.raises(ValueError, match="counts nothing"):
        _observation(
            numerator_count=1,
            denominator_count=0,
            status=MetricObservationStatus.UNDEFINED_ZERO_DENOMINATOR,
            fraction_text=None,
        )


def test_a_numerator_cannot_exceed_its_denominator() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        _observation(numerator_count=10, denominator_count=9)


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", MetricScope(MetricScopeKind.RELEASE, "SD300B")),
        ("scope", MetricScope(MetricScopeKind.POOLED)),
        ("numerator_count", 7),
        ("denominator_count", 10),
        ("source_view_fingerprint", "e" * 64),
        ("source_decision_set_fingerprint", "f" * 64),
        ("source_eligibility_set_fingerprint", "0" * 64),
        ("metric_policy_fingerprint", "1" * 64),
        ("metric_id", "plain_self_match_rate_attempt"),
        ("ordinal", 3),
    ],
)
def test_the_hash_covers_every_load_bearing_field(field, value) -> None:
    original = _observation()
    changed = _observation(**{field: value})
    assert changed.observation_hash != original.observation_hash


def test_a_forged_hash_is_refused() -> None:
    original = _observation()
    with pytest.raises(ValueError, match="does not cover"):
        MetricObservation(
            ordinal=original.ordinal,
            metric_id=original.metric_id,
            scope=original.scope,
            numerator_count=7,
            denominator_count=9,
            status=original.status,
            fraction_text="7/9",
            source_decision_set_fingerprint=DECISIONS,
            source_eligibility_set_fingerprint=ELIGIBILITY,
            source_view_fingerprint=VIEW,
            metric_policy_fingerprint=POLICY,
            observation_hash=original.observation_hash,
        )
