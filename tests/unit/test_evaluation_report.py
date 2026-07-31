"""The report shows fractions, hides nothing, and claims nothing extra.

Two failure modes are being tested for. The first is *rounding away the
evidence*: a report that printed ``0.6%`` would be unfalsifiable, so every rate
carries its fraction. The second is *leaking the rows*: a report is the artefact
most likely to be pasted into a document, so it must contain no score, no
subject and no path (spec sections 51, 76).
"""

from __future__ import annotations

import re

import pytest

from fpbench.core.errors import EvaluationReportError
from fpbench.metrics import render_report
from metricworld import SPEC_EXAMPLE_SCRIPT, all_matching, build_metric_world

pytestmark = pytest.mark.metrics

_FRACTION = re.compile(r"\d+/\d+ \(\d+\.\d{4}%\)")


@pytest.fixture(scope="module")
def world():
    return build_metric_world(
        {
            "SD300A": SPEC_EXAMPLE_SCRIPT,
            "SD300B": all_matching(10),
            "SD300C": all_matching(10),
        }
    )


@pytest.fixture(scope="module")
def parts(world):
    counts = world.counts()
    observations = world.observations(counts)
    return counts, observations, world.manifest(counts, observations)


@pytest.fixture(scope="module")
def report(world, parts) -> str:
    counts, observations, manifest = parts
    return world.render(manifest, counts, observations)


def test_every_rate_is_shown_as_a_fraction_and_a_percentage(report) -> None:
    assert len(_FRACTION.findall(report)) > 30
    # A bare percentage with no fraction beside it should not occur.
    bare = re.findall(r"\|\s*\d+\.\d{4}%\s*\|", report)
    assert bare == []


def test_percentages_are_rounded_only_for_display(world, parts, report) -> None:
    _, observations, _ = parts
    observation = world.observation(
        observations, "plain_self_match_rate_decided", "SD300A"
    )
    assert observation.fraction_text == "8/9"
    assert "8/9 (88.8889%)" in report


def test_counts_remain_exact_in_the_tables(report) -> None:
    # SD300A's ten units, and the exact scripted breakdown beside them.
    assert "| SD300A | 10 | 8 | 1 | 1 |" in report


def test_a_pooled_row_is_present_in_every_table(report) -> None:
    assert report.count("| pooled |") >= 6


def test_release_order_follows_the_report_profile(report) -> None:
    positions = [report.index(f"| {release} |") for release in ("SD300A", "SD300B", "SD300C")]
    assert positions == sorted(positions)


def test_the_threshold_and_comparator_are_shown(report) -> None:
    assert "`40` (greater_than_or_equal, origin `documented_native`)" in report


def test_the_decision_profile_is_shown(report) -> None:
    assert "| Decision profile | `test_documented_profile_v1` |" in report


def test_all_ten_mandatory_sections_are_present(report) -> None:
    for heading in (
        "## 1. Evaluation identity",
        "## 2. Protocol and threshold",
        "## 3. Important limitations",
        "## 4. SELF results",
        "## 5. SELF eligibility",
        "## 6. Unconditional PLAIN–ROLL genuine results",
        "## 7. SELF-conditional PLAIN–ROLL genuine results",
        "## 8. Same-subject different-finger negative sanity check",
        "## 9. Operational and failure accounting",
        "## 10. What these results do not establish",
    ):
        assert heading in report


def test_the_conditional_table_publishes_its_selection_and_exclusions(report) -> None:
    for column in (
        "Selection rate",
        "Excluded: ineligible",
        "Excluded: undetermined",
        "Included",
        "Conditional decision FNMR",
    ):
        assert column in report


def test_no_raw_score_appears(report) -> None:
    lowered = report.lower()
    for forbidden in ("raw_score", "raw score", "score of", "similarity score"):
        assert forbidden not in lowered


def test_no_subject_or_image_identifier_appears(report) -> None:
    lowered = report.lower()
    for forbidden in ("subject_id", "image_id", "pair_id", "job_id", "selfunit_"):
        assert forbidden not in lowered


def test_no_absolute_path_appears(report) -> None:
    assert not re.search(r"[A-Za-z]:[\\/]", report)
    assert "\\" not in report
    for line in report.splitlines():
        assert not line.strip().startswith("/")


def test_no_threshold_optimality_or_resolution_claim(report) -> None:
    lowered = report.lower()
    for forbidden in (
        "best threshold",
        "optimal threshold",
        "better resolution",
        "outperform",
        "statistically significant",
    ):
        assert forbidden not in lowered


def test_the_report_is_byte_identical_across_renders(world, parts) -> None:
    counts, observations, manifest = parts
    first = world.render(manifest, counts, observations)
    second = world.render(manifest, counts, observations)
    assert first == second
    assert "\r" not in first


def test_a_metric_the_set_does_not_hold_is_refused_rather_than_computed(
    world, parts
) -> None:
    counts, observations, manifest = parts
    trimmed = tuple(
        observation
        for observation in observations
        if observation.metric_id != "plain_self_match_rate_decided"
    )
    with pytest.raises(EvaluationReportError, match="never computed while formatting"):
        render_report(
            context=world.report_context(manifest),
            manifest=manifest,
            policy=world.policy,
            report_profile=world.report_profile,
            counts=counts,
            observations=trimmed,
        )
