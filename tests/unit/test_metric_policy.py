"""The policy file selects metrics. It cannot define one, and it cannot lie.

A config that could re-point ``plain_roll_mated_conditional_fnmr_decided`` at a
different denominator would be a config that could change a published result
without changing its name. So definitions live in code, the loader refuses
anything it does not recognise, and two flags — the FMR label and the exclusion
counts — are refusals rather than settings (docs/adr/0029, docs/adr/0030).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fpbench.core.errors import MetricPolicyError
from fpbench.core.metric_models import (
    MetricDenominator,
    MetricNumerator,
    metric_policy_fingerprint,
)
from fpbench.metrics import build_report_profile, load_metric_policy
from fpbench.metrics.policy import METRIC_CATALOGUE, METRIC_CATALOGUE_ORDER
from metricworld import DEFAULT_POLICY_PATH

pytestmark = pytest.mark.metrics


@pytest.fixture(scope="module")
def document() -> dict:
    return yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_the_committed_policy_loads_and_selects_the_whole_catalogue() -> None:
    policy = load_metric_policy(DEFAULT_POLICY_PATH)
    assert policy.policy_id == "plain_roll_biometric_metrics_v1"
    assert policy.metric_ids == METRIC_CATALOGUE_ORDER
    assert len(policy.metric_definitions) == len(METRIC_CATALOGUE)


def test_the_policy_fingerprint_covers_its_definitions() -> None:
    policy = load_metric_policy(DEFAULT_POLICY_PATH)
    assert policy.policy_fingerprint == metric_policy_fingerprint(policy)


def test_changing_a_denominator_changes_the_policy_fingerprint(document) -> None:
    from fpbench.metrics.policy import build_metric_policy

    original = load_metric_policy(DEFAULT_POLICY_PATH)
    tampered = tuple(
        definition
        if definition.metric_id != "plain_roll_mated_conditional_fnmr_decided"
        else type(definition)(
            metric_id=definition.metric_id,
            metric_family=definition.metric_family,
            numerator=definition.numerator,
            # The substitution this whole layer exists to prevent.
            denominator=MetricDenominator.INCLUDED_CONDITIONAL_ATTEMPTS,
            source_view_kind=definition.source_view_kind,
            source_protocol_stage=definition.source_protocol_stage,
            interpretation=definition.interpretation,
            prohibited_labels=definition.prohibited_labels,
        )
        for definition in original.metric_definitions
    )
    changed = build_metric_policy(
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        metric_definitions=tampered,
        percentage_decimal_places=original.percentage_decimal_places,
        always_show_fraction=original.always_show_fraction,
        zero_format=original.zero_format,
        metadata=dict(original.metadata),
    )
    assert changed.policy_fingerprint != original.policy_fingerprint


def test_display_precision_does_not_change_the_policy_fingerprint(document) -> None:
    from fpbench.metrics.policy import build_metric_policy

    original = load_metric_policy(DEFAULT_POLICY_PATH)
    rerendered = build_metric_policy(
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        metric_definitions=original.metric_definitions,
        percentage_decimal_places=6,
        always_show_fraction=original.always_show_fraction,
        zero_format=original.zero_format,
        metadata=dict(original.metadata),
    )
    # Rounding differently is a rendering choice. Letting it change the metric
    # identity would make every republication look like a new result.
    assert rerendered.policy_fingerprint == original.policy_fingerprint


def test_display_precision_does_change_the_report_profile_fingerprint() -> None:
    from fpbench.core.metric_models import report_profile_fingerprint

    profile = build_report_profile(
        profile_id="biometric_evaluation_markdown_en_v1",
        release_order=("SD300A", "SD300B", "SD300C"),
    )

    class _Probe:
        def __init__(self, source, **overrides):
            for name in (
                "report_profile_id",
                "percentage_decimal_places",
                "always_show_fraction",
                "include_pooled",
                "release_order",
                "language",
            ):
                setattr(self, name, getattr(source, name))
            for name, value in overrides.items():
                setattr(self, name, value)

    # Rendering is what the report profile is for, so precision reaches its
    # fingerprint even though it does not reach the policy's.
    assert report_profile_fingerprint(
        _Probe(profile, percentage_decimal_places=6)
    ) != profile.report_profile_fingerprint


def test_release_order_changes_the_report_profile_fingerprint() -> None:
    forwards = build_report_profile(
        profile_id="biometric_evaluation_markdown_en_v1",
        release_order=("SD300A", "SD300B", "SD300C"),
    )
    backwards = build_report_profile(
        profile_id="biometric_evaluation_markdown_en_v1",
        release_order=("SD300C", "SD300B", "SD300A"),
    )
    assert (
        backwards.report_profile_fingerprint != forwards.report_profile_fingerprint
    )


def test_labelling_the_sanity_set_as_fmr_is_refused(tmp_path, document) -> None:
    document = dict(document)
    document["negative_sanity"] = {
        **document["negative_sanity"],
        "label_as_fmr": True,
    }
    with pytest.raises(MetricPolicyError, match="may not be true"):
        load_metric_policy(_write(tmp_path, document))


def test_dropping_the_conditional_exclusion_counts_is_refused(
    tmp_path, document
) -> None:
    document = dict(document)
    document["mated_conditional"] = {
        **document["mated_conditional"],
        "retain_exclusion_reasons": False,
    }
    with pytest.raises(MetricPolicyError, match="cannot be read"):
        load_metric_policy(_write(tmp_path, document))


def test_averaging_release_percentages_is_refused(tmp_path, document) -> None:
    document = dict(document)
    document["unit_of_analysis"] = {
        **document["unit_of_analysis"],
        "pooled_aggregation": "mean_of_release_rates",
    }
    with pytest.raises(MetricPolicyError, match="sum counts"):
        load_metric_policy(_write(tmp_path, document))


def test_weighting_by_subject_is_refused(tmp_path, document) -> None:
    document = dict(document)
    document["unit_of_analysis"] = {
        **document["unit_of_analysis"],
        "subject_weighting": "equal_per_subject",
    }
    with pytest.raises(MetricPolicyError, match="not supported"):
        load_metric_policy(_write(tmp_path, document))


def test_an_unrecognised_switch_is_refused(tmp_path, document) -> None:
    document = dict(document)
    document["mated_unconditional"] = {
        **document["mated_unconditional"],
        "decision_fmr": True,
    }
    with pytest.raises(MetricPolicyError, match="do not name any metric"):
        load_metric_policy(_write(tmp_path, document))


def test_a_policy_that_computes_nothing_is_refused(tmp_path, document) -> None:
    document = dict(document)
    for section in ("eligibility", "mated_unconditional", "negative_sanity"):
        document[section] = {
            key: (False if isinstance(value, bool) else value)
            for key, value in document[section].items()
        }
    document["negative_sanity"]["label_as_fmr"] = False
    document["mated_conditional"] = {
        "selection_rate": False,
        "decision_fnmr": False,
        "attempt_non_success_rate": False,
        "retain_exclusion_reasons": True,
    }
    document["self"] = {
        "plain": {"match_rate_decided": False, "match_rate_attempt": False},
        "roll": {"match_rate_decided": False, "match_rate_attempt": False},
    }
    with pytest.raises(MetricPolicyError, match="computes nothing"):
        load_metric_policy(_write(tmp_path, document))


def test_every_catalogue_entry_names_a_numerator_and_a_denominator() -> None:
    for definition in METRIC_CATALOGUE.values():
        assert isinstance(definition.numerator, MetricNumerator)
        assert isinstance(definition.denominator, MetricDenominator)
        assert definition.interpretation.strip()


def test_an_unknown_report_profile_is_refused() -> None:
    with pytest.raises(MetricPolicyError, match="not one this project defines"):
        build_report_profile(profile_id="glossy_pdf_v1", release_order=("SD300A",))
