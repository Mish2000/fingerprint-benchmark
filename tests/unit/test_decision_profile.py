"""A threshold is only as trustworthy as the story of where it came from.

Two failure modes matter more than the rest, and both are quiet.

The first is **misdescribing a threshold's origin** — presenting a number the
algorithm's authors published as though this project had measured it. That is
what ``origin`` exists to prevent, and why a calibrated profile without a
calibration manifest is refused outright.

The second is **calibrating on the test cohort**: choosing a threshold from the
same 50 subjects the results are later reported over. It would improve every
number and invalidate all of them, and it is the one form of leakage a config
file could introduce by accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fpbench.core.decision_models import ThresholdComparator, ThresholdOrigin
from fpbench.core.enums import ScoreDirection
from fpbench.core.errors import (
    DecisionProfileApplicabilityError,
    DecisionProfileError,
)
from fpbench.decisions import (
    build_decision_profile,
    load_decision_profile,
    require_profile_applies_to_run,
)
from runworld import build_world

pytestmark = pytest.mark.decisions

REPO = Path(__file__).resolve().parents[2]
DOCUMENTED_40 = (
    REPO / "configs" / "decisions" / "sourceafis_java_3_18_1_documented_40_v1.yaml"
)


def _fields(**overrides):
    fields = {
        "profile_id": "test_profile_v1",
        "display_name": "Test",
        "profile_version": "1",
        "origin": ThresholdOrigin.DOCUMENTED_NATIVE,
        "algorithm_id": "test_matcher",
        "implementation_version": "1",
        "algorithm_fingerprint": "a" * 64,
        "score_direction": ScoreDirection.HIGHER_IS_BETTER,
        "comparator": ThresholdComparator.GREATER_THAN_OR_EQUAL,
        "threshold": "40",
        "source_kind": "upstream_documentation",
        "source_reference": "test",
        "source_version": "1",
        "allowed_execution_profiles": ("identity_png_v1",),
        "calibration_performed": False,
        "calibration_manifest_fingerprint": None,
        "metadata": {},
    }
    fields.update(overrides)
    return fields


# --------------------------------------------------------------- the config


def test_the_committed_documented_profile_loads():
    profile = load_decision_profile(DOCUMENTED_40, algorithm_fingerprint="b" * 64)
    assert profile.profile_id == "sourceafis_java_3_18_1_documented_40_v1"
    assert profile.threshold == "40"
    assert profile.comparator is ThresholdComparator.GREATER_THAN_OR_EQUAL
    assert profile.origin is ThresholdOrigin.DOCUMENTED_NATIVE
    assert profile.algorithm_id == "sourceafis_java"
    assert profile.implementation_version == "3.18.1"
    assert profile.allowed_execution_profiles == ("native_identity_60s_v1",)


def test_the_documented_profile_is_not_a_calibrated_one():
    profile = load_decision_profile(DOCUMENTED_40, algorithm_fingerprint="b" * 64)
    assert not profile.calibration_performed
    assert profile.calibration_manifest_fingerprint is None
    assert profile.metadata["calibration_test_cohort_used"] == "false"


def test_the_upstream_claim_is_kept_as_provenance_not_as_a_finding():
    profile = load_decision_profile(DOCUMENTED_40, algorithm_fingerprint="b" * 64)
    assert profile.metadata["upstream_claim"] == "approximate_fmr_0_0001"
    assert profile.metadata["upstream_claim_is_not_benchmark_result"] == "true"


def test_the_profile_binds_to_the_algorithm_build_it_is_loaded_against():
    first = load_decision_profile(DOCUMENTED_40, algorithm_fingerprint="b" * 64)
    second = load_decision_profile(DOCUMENTED_40, algorithm_fingerprint="c" * 64)
    assert first.profile_fingerprint != second.profile_fingerprint


def test_a_pinned_fingerprint_that_disagrees_is_refused(tmp_path):
    document = yaml.safe_load(DOCUMENTED_40.read_text(encoding="utf-8"))
    document["algorithm"]["fingerprint"] = "d" * 64
    path = tmp_path / "pinned.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(DecisionProfileError, match="pins algorithm fingerprint"):
        load_decision_profile(path, algorithm_fingerprint="b" * 64)


def test_calibration_on_the_test_cohort_is_refused(tmp_path):
    document = yaml.safe_load(DOCUMENTED_40.read_text(encoding="utf-8"))
    document["calibration"]["test_cohort_used"] = True
    path = tmp_path / "leaky.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(DecisionProfileError, match="TEST cohort"):
        load_decision_profile(path, algorithm_fingerprint="b" * 64)


def test_a_missing_profile_file_is_refused(tmp_path):
    with pytest.raises(DecisionProfileError, match="not found"):
        load_decision_profile(tmp_path / "absent.yaml", algorithm_fingerprint="b" * 64)


# ------------------------------------------------------------- invariants


def test_a_comparator_that_contradicts_the_score_direction_is_refused():
    with pytest.raises(DecisionProfileError, match="requires comparator"):
        build_decision_profile(
            **_fields(comparator=ThresholdComparator.LESS_THAN_OR_EQUAL)
        )


def test_a_profile_must_name_an_execution_profile():
    with pytest.raises(DecisionProfileError, match="at least one execution profile"):
        build_decision_profile(**_fields(allowed_execution_profiles=()))


def test_a_calibrated_origin_without_a_manifest_is_refused():
    with pytest.raises(DecisionProfileError, match="cannot be executed yet"):
        build_decision_profile(
            **_fields(origin=ThresholdOrigin.CALIBRATED_DEVELOPMENT)
        )


def test_an_external_fixed_profile_is_refused_until_a_later_stage():
    with pytest.raises(DecisionProfileError, match="cannot be executed yet"):
        build_decision_profile(**_fields(origin=ThresholdOrigin.EXTERNAL_FIXED))


def test_claiming_calibration_without_a_manifest_is_refused():
    with pytest.raises(DecisionProfileError, match="must name the calibration"):
        build_decision_profile(**_fields(calibration_performed=True))


def test_citing_a_manifest_without_calibrating_is_refused():
    with pytest.raises(DecisionProfileError, match="must not cite"):
        build_decision_profile(
            **_fields(calibration_manifest_fingerprint="e" * 64)
        )


def test_a_documented_profile_without_calibration_is_accepted():
    profile = build_decision_profile(**_fields())
    assert profile.origin is ThresholdOrigin.DOCUMENTED_NATIVE
    assert not profile.calibration_performed


@pytest.mark.parametrize("threshold", ["NaN", "Infinity", ""])
def test_an_unusable_threshold_is_refused(threshold):
    with pytest.raises(DecisionProfileError):
        build_decision_profile(**_fields(threshold=threshold))


# ------------------------------------------------------------ fingerprint


def test_the_display_name_is_not_part_of_the_identity():
    first = build_decision_profile(**_fields(display_name="One"))
    second = build_decision_profile(**_fields(display_name="Two"))
    assert first.profile_fingerprint == second.profile_fingerprint


@pytest.mark.parametrize(
    "field, value",
    [
        ("threshold", "41"),
        ("source_reference", "somewhere_else"),
        ("source_kind", "external_standard"),
        ("source_version", "2"),
        ("profile_version", "2"),
        ("algorithm_fingerprint", "f" * 64),
        ("implementation_version", "3.19.0"),
        ("allowed_execution_profiles", ("other_profile_v1",)),
    ],
)
def test_a_change_that_could_change_a_decision_changes_the_fingerprint(field, value):
    base = build_decision_profile(**_fields())
    other = build_decision_profile(**_fields(**{field: value}))
    assert base.profile_fingerprint != other.profile_fingerprint


def test_building_the_same_profile_twice_is_stable():
    """No timestamp, no path, no ordering: the same inputs, the same identity."""
    assert (
        build_decision_profile(**_fields()).profile_fingerprint
        == build_decision_profile(**_fields()).profile_fingerprint
    )


# ------------------------------------------------------------ applicability


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path)


def test_a_matching_profile_applies(world):
    profile = build_decision_profile(
        **_fields(
            algorithm_id=world.run.algorithm.algorithm_id,
            implementation_version=world.run.algorithm.implementation_version,
            algorithm_fingerprint=world.run.algorithm_fingerprint,
            score_direction=world.run.algorithm.score_direction,
            allowed_execution_profiles=(world.run.execution_profile.profile_id,),
        )
    )
    require_profile_applies_to_run(profile=profile, run=world.run)


def test_a_profile_for_another_algorithm_is_refused(world):
    profile = build_decision_profile(
        **_fields(
            algorithm_fingerprint=world.run.algorithm_fingerprint,
            allowed_execution_profiles=(world.run.execution_profile.profile_id,),
        )
    )
    with pytest.raises(DecisionProfileApplicabilityError, match="algorithm_id"):
        require_profile_applies_to_run(profile=profile, run=world.run)


def test_a_profile_for_another_build_of_the_same_algorithm_is_refused(world):
    """Same matcher, different jar. "Score 40 means match" is a claim about a build."""
    profile = build_decision_profile(
        **_fields(
            algorithm_id=world.run.algorithm.algorithm_id,
            implementation_version=world.run.algorithm.implementation_version,
            algorithm_fingerprint="9" * 64,
            allowed_execution_profiles=(world.run.execution_profile.profile_id,),
        )
    )
    with pytest.raises(
        DecisionProfileApplicabilityError, match="algorithm_fingerprint"
    ):
        require_profile_applies_to_run(profile=profile, run=world.run)


def test_a_profile_for_another_execution_profile_is_refused(world):
    profile = build_decision_profile(
        **_fields(
            algorithm_id=world.run.algorithm.algorithm_id,
            implementation_version=world.run.algorithm.implementation_version,
            algorithm_fingerprint=world.run.algorithm_fingerprint,
            allowed_execution_profiles=("some_other_profile_v1",),
        )
    )
    with pytest.raises(DecisionProfileApplicabilityError, match="execution profiles"):
        require_profile_applies_to_run(profile=profile, run=world.run)
