"""The impostor sanity check may never be named, labelled or read as an FMR.

Names travel further than caveats: a metric id ends up in a spreadsheet column
long after the docstring explaining it has been left behind. So the refusal is
enforced in three places — the id, the definition's prohibited labels, and the
report's prose — and tested in all three (docs/adr/0025, docs/adr/0030).

The tests deliberately do **not** grep for the substring ``FMR``. The report is
*supposed* to contain the sentence "This is not a general false-match rate
estimate", and a blunt substring assertion would force that sentence out of the
document to stay green — which is the opposite of what it is for (spec section
75). What they check instead is the assertion form: ``FMR =``, ``FMR:`` and
``false-match rate = ``.
"""

from __future__ import annotations

import re

import pytest

from fpbench.core.errors import MetricPolicyError
from fpbench.core.metric_models import (
    FORBIDDEN_METRIC_TOKENS,
    require_honest_metric_id,
)
from fpbench.metrics.policy import METRIC_CATALOGUE
from metricworld import SPEC_EXAMPLE_SCRIPT, UnitScript, build_metric_world

pytestmark = pytest.mark.metrics

SANITY_METRICS = (
    "plain_roll_non_mated_sanity_match_rate_decided",
    "plain_roll_non_mated_sanity_match_rate_attempt",
)

#: Forms that assert a rate. Each is a way the sanity fraction could be
#: presented as an FMR; none of them can appear.
_ASSERTION_FORMS = (
    re.compile(r"\bFMR\s*[=:]", re.IGNORECASE),
    re.compile(r"false[- ]match rate\s*[=:]", re.IGNORECASE),
    re.compile(r"\bFMR\s+(?:is|was)\s+\d", re.IGNORECASE),
)


@pytest.mark.parametrize("metric_id", SANITY_METRICS)
def test_the_sanity_metric_ids_say_sanity(metric_id) -> None:
    assert "sanity" in metric_id
    assert metric_id in METRIC_CATALOGUE


@pytest.mark.parametrize("metric_id", SANITY_METRICS)
def test_the_sanity_definitions_prohibit_the_fmr_labels(metric_id) -> None:
    definition = METRIC_CATALOGUE[metric_id]
    assert "general_fmr" in definition.prohibited_labels
    assert "population_fmr" in definition.prohibited_labels
    assert "impostor_fmr" in definition.prohibited_labels


def test_the_policy_stores_what_the_negative_set_is() -> None:
    """The metadata reaches the policy fingerprint, so removing it is visible.

    Stage 5A's view manifest carries the same facts, and the metric set pins
    that view's fingerprint. Keeping a copy in the policy means a reader holding
    only ``metric-policy.json`` still learns that the negative fraction is a
    closed-set sanity check (spec section 45).
    """
    from fpbench.metrics import load_metric_policy
    from metricworld import DEFAULT_POLICY_PATH

    policy = load_metric_policy(DEFAULT_POLICY_PATH)
    assert policy.metadata["negative_sanity_negative_kind"] == (
        "same_subject_different_finger"
    )
    assert policy.metadata["negative_sanity_pairing_strategy"] == (
        "cyclic_finger_shift"
    )
    assert policy.metadata["negative_sanity_closed_set"] == "true"
    assert policy.metadata["negative_sanity_primary_fmr_estimate"] == "false"
    assert policy.metadata["negative_sanity_purpose"] == "negative_sanity_check"


def test_dropping_the_negative_metadata_changes_the_policy_fingerprint() -> None:
    from fpbench.metrics import load_metric_policy
    from fpbench.metrics.policy import build_metric_policy
    from metricworld import DEFAULT_POLICY_PATH

    original = load_metric_policy(DEFAULT_POLICY_PATH)
    stripped = build_metric_policy(
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        metric_definitions=original.metric_definitions,
        percentage_decimal_places=original.percentage_decimal_places,
        always_show_fraction=original.always_show_fraction,
        zero_format=original.zero_format,
        metadata={
            key: value
            for key, value in original.metadata.items()
            if key != "negative_sanity_primary_fmr_estimate"
        },
    )
    assert stripped.policy_fingerprint != original.policy_fingerprint


@pytest.mark.parametrize("token", sorted(FORBIDDEN_METRIC_TOKENS))
def test_a_metric_id_claiming_a_population_rate_is_refused(token) -> None:
    with pytest.raises(MetricPolicyError, match="population-level false-match rate"):
        require_honest_metric_id(f"plain_roll_{token}_v1")


def test_a_qualified_fnmr_is_still_allowed() -> None:
    # ``fnmr`` is forbidden in a *view* name, because a view claims a
    # population. A metric that names its denominator in the same breath is a
    # legitimate thing to call an FNMR.
    assert require_honest_metric_id("plain_roll_mated_unconditional_fnmr_decided")


@pytest.fixture(scope="module")
def report() -> str:
    world = build_metric_world({"SD300A": SPEC_EXAMPLE_SCRIPT})
    counts = world.counts()
    observations = world.observations(counts)
    return world.render(world.manifest(counts, observations), counts, observations)


def test_the_report_carries_the_closed_set_caveat(report) -> None:
    assert "closed" in report.lower()
    assert "closed cohort" in report or "closed set" in report.lower()


def test_the_report_carries_the_same_subject_different_finger_caveat(report) -> None:
    assert "Same-subject different-finger negative sanity check" in report
    assert "same_subject_different_finger" in report
    assert "different* fingers of the *same* subject" in report


def test_the_report_states_the_refusal_explicitly(report) -> None:
    assert "not a general" in report and "false-match rate" in report


@pytest.mark.parametrize("pattern", _ASSERTION_FORMS)
def test_the_report_never_asserts_a_false_match_rate(report, pattern) -> None:
    assert pattern.search(report) is None


def test_zero_matches_render_as_an_observed_fraction() -> None:
    clean = tuple(UnitScript() for _ in range(10))
    world = build_metric_world({"SD300A": clean})
    counts = world.counts()
    observations = world.observations(counts)
    markdown = world.render(world.manifest(counts, observations), counts, observations)

    assert "Observed 0/10 matching decisions in this sanity set." in markdown
    # Never as a probability claim, and never as an absence of false matches.
    assert "no false matches" not in markdown.lower()
    assert "FMR was zero" not in markdown
    assert "zero false matches" not in markdown.lower()


def test_a_non_zero_sanity_count_renders_with_the_required_wording(report) -> None:
    assert (
        "Observed matches in the closed-set same-subject different-finger "
        "negative sanity check: 1/10." in report
    )
