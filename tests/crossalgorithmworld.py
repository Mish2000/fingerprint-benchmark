"""A small two-algorithm world, built by hand, for the stage 7D contract suite.

The real comparison reads six verified artefacts per side. Reproducing all of
them would mean reproducing two research runs, and the questions this suite asks
— what happens when the eligible sets differ, when one side fails a comparison,
when a pair id moves, when a transition cell is removed — are questions about the
comparison layer and not about the layers beneath it.

So the sides are built from simple stand-ins carrying exactly the attributes
:mod:`fpbench.cross_algorithm` reads. Nothing here fakes a *score*: the
comparison layer cannot read one, which is the property the structural suite
proves and this one relies on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Mapping, Sequence

from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionValue,
    GroundTruth,
    ProtocolStage,
    SelfEligibilityStatus,
    ThresholdOrigin,
)
from fpbench.cross_algorithm import ComparisonSide

__all__ = [
    "RELEASES",
    "UNITS_PER_RELEASE",
    "digest",
    "build_world",
    "WorldSide",
    "protocol_for",
]

RELEASES = ("SD300A", "SD300B", "SD300C")

#: Two units per release keeps every table small enough to read in a failure
#: message and still exercises pooling across three releases.
UNITS_PER_RELEASE = 2


def digest(seed: str) -> str:
    """A deterministic 64-character stand-in for a real fingerprint."""
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


@dataclass
class WorldSide:
    """One algorithm's outcomes, expressed as decisions rather than scores."""

    label: str
    #: ``(stage, unit_index) -> outcome``. Missing entries default to a match.
    outcomes: Mapping[tuple[str, int], str] = field(default_factory=dict)
    calibrated: bool = False
    test_cohort: bool = False
    equated: bool = False
    execution_profile_hash: str = "profile-hash"
    eligibility_policy_id: str = "plain_and_roll_self_must_match"
    eligibility_policy_version: str = "1"
    metric_policy_fingerprint: str = field(default_factory=lambda: digest("metric"))


_STAGES = (
    ProtocolStage.PLAIN_SELF,
    ProtocolStage.ROLL_SELF,
    ProtocolStage.PLAIN_ROLL_MATED,
    ProtocolStage.PLAIN_ROLL_NON_MATED,
)


def _unit_keys() -> list[tuple[str, int]]:
    return [
        (release, index)
        for release in RELEASES
        for index in range(UNITS_PER_RELEASE)
    ]


def _pair_id(stage: ProtocolStage, release: str, index: int) -> str:
    return f"pair_{stage.value}_{release}_{index}"


def build_pairs() -> Mapping[str, SimpleNamespace]:
    pairs: dict[str, SimpleNamespace] = {}
    for release, index in _unit_keys():
        for stage in _STAGES:
            pair_id = _pair_id(stage, release, index)
            pairs[pair_id] = SimpleNamespace(
                pair_id=pair_id,
                release=release,
                protocol_stage=stage,
                ground_truth=(
                    GroundTruth.NON_MATED
                    if stage is ProtocolStage.PLAIN_ROLL_NON_MATED
                    else GroundTruth.MATED
                ),
            )
    return pairs


def _decision_record(
    *, pair_id: str, outcome: str, side_label: str
) -> SimpleNamespace:
    if outcome == "undecidable":
        status = DecisionApplicationStatus.UNDECIDABLE
        decision = None
    else:
        status = DecisionApplicationStatus.DECIDED
        decision = (
            DecisionValue.MATCH if outcome == "match" else DecisionValue.NON_MATCH
        )
    return SimpleNamespace(
        pair_id=pair_id,
        application_status=status,
        decision=decision,
        decision_record_hash=digest(f"{side_label}:decision:{pair_id}:{outcome}"),
        source_result_hash=digest(f"{side_label}:result:{pair_id}"),
    )


def _eligibility_status(
    plain: str, roll: str
) -> SelfEligibilityStatus:
    if "non_match" in (plain, roll):
        return SelfEligibilityStatus.INELIGIBLE
    if "undecidable" in (plain, roll):
        return SelfEligibilityStatus.UNDETERMINED
    return SelfEligibilityStatus.ELIGIBLE


def build_side(side: WorldSide) -> ComparisonSide:
    """Turn a table of outcomes into everything the comparison layer reads."""
    decisions = []
    eligibility_records = []
    for release, index in _unit_keys():
        outcomes = {}
        for stage in _STAGES:
            key = (stage.value, _unit_keys().index((release, index)))
            outcome = side.outcomes.get(key, "match")
            outcomes[stage.value] = outcome
            decisions.append(
                _decision_record(
                    pair_id=_pair_id(stage, release, index),
                    outcome=outcome,
                    side_label=side.label,
                )
            )
        unit_id = f"unit_{release.lower()}_{index}"
        status = _eligibility_status(
            outcomes[ProtocolStage.PLAIN_SELF.value],
            outcomes[ProtocolStage.ROLL_SELF.value],
        )
        eligibility_records.append(
            SimpleNamespace(
                eligibility_unit_id=unit_id,
                release=release,
                mated_pair_id=_pair_id(
                    ProtocolStage.PLAIN_ROLL_MATED, release, index
                ),
                status=status,
                eligibility_record_hash=digest(
                    f"{side.label}:unit:{unit_id}:{status.value}"
                ),
            )
        )

    metadata = {
        "calibration_test_cohort_used": "true" if side.test_cohort else "false",
        "claims.equivalent_to_sourceafis_operating_point": (
            "true" if side.equated else "false"
        ),
    }
    return ComparisonSide(
        label=side.label,
        run=SimpleNamespace(
            run_id=f"run_{side.label}",
            run_fingerprint=digest(f"run:{side.label}"),
            execution_profile_hash=side.execution_profile_hash,
        ),
        result_set=SimpleNamespace(
            result_set_id=f"resultset_{side.label}",
            result_set_fingerprint=digest(f"resultset:{side.label}"),
        ),
        decision_profile=SimpleNamespace(
            profile_id=f"profile_{side.label}",
            profile_fingerprint=digest(f"profile:{side.label}"),
            origin=ThresholdOrigin.DOCUMENTED_NATIVE,
            calibration_performed=side.calibrated,
            metadata=metadata,
        ),
        decision_manifest=SimpleNamespace(
            decision_set_id=f"decisionset_{side.label}",
            decision_set_fingerprint=digest(f"decisionset:{side.label}"),
        ),
        decisions=tuple(decisions),
        eligibility_manifest=SimpleNamespace(
            eligibility_set_id=f"eligibilityset_{side.label}",
            eligibility_set_fingerprint=digest(f"eligibilityset:{side.label}"),
            policy_id=side.eligibility_policy_id,
            policy_version=side.eligibility_policy_version,
        ),
        eligibility_records=tuple(eligibility_records),
        metric_manifest=SimpleNamespace(
            metric_set_id=f"metricset_{side.label}",
            metric_set_fingerprint=digest(f"metricset:{side.label}"),
            metric_policy_fingerprint=side.metric_policy_fingerprint,
            decision_set_id=f"decisionset_{side.label}",
        ),
        stage_finalization_fingerprint=(
            digest("stage7c") if side.label == "right" else None
        ),
    )


def protocol_for(left: ComparisonSide, right: ComparisonSide):
    """A frozen protocol that matches the world the two sides describe."""
    from fpbench.cross_algorithm.align import build_fair_measurement_protocol

    return build_fair_measurement_protocol(
        schema_version="1",
        protocol_id="test_protocol_v1",
        sourceafis_run_id="run_left",
        sourceafis_result_set_id="resultset_left",
        sourceafis_decision_set_id="decisionset_left",
        sourceafis_eligibility_set_id="eligibilityset_left",
        sourceafis_metric_set_id="metricset_left",
        nbis_run_id="run_right",
        nbis_result_set_id="resultset_right",
        stage_7c_finalization_fingerprint=digest("stage7c"),
        alignment_fingerprint=digest("alignment"),
        preparation_set_id="prepset_test",
        preparation_set_fingerprint=digest("prepset"),
        sourceafis_decision_profile_fingerprint=digest("profile:left"),
        nbis_decision_profile_fingerprint=digest("profile:right"),
        eligibility_policy_id=left.eligibility_manifest.policy_id,
        eligibility_policy_version=left.eligibility_manifest.policy_version,
        metric_policy_id="plain_roll_biometric_metrics_v1",
        metric_policy_fingerprint=left.metric_manifest.metric_policy_fingerprint,
        comparison_policy_fingerprint=digest("comparison-policy"),
        operating_point_relation="independently_documented_not_equated",
        raw_score_comparison=False,
        calibration_performed=False,
        test_cohort_used=False,
    )


def build_world(
    *,
    left_outcomes: Mapping[tuple[str, int], str] | None = None,
    right_outcomes: Mapping[tuple[str, int], str] | None = None,
    **side_overrides,
):
    """Both sides, the pairs and a matching protocol, ready to compare."""
    left = build_side(
        WorldSide(
            label="left",
            outcomes=dict(left_outcomes or {}),
            **{
                key[len("left_") :]: value
                for key, value in side_overrides.items()
                if key.startswith("left_")
            },
        )
    )
    right = build_side(
        WorldSide(
            label="right",
            outcomes=dict(right_outcomes or {}),
            **{
                key[len("right_") :]: value
                for key, value in side_overrides.items()
                if key.startswith("right_")
            },
        )
    )
    return left, right, build_pairs(), protocol_for(left, right)


def clean_audit(left, right, protocol, **overrides):
    """A fairness audit over a world that is, by construction, fair."""
    from fpbench.cross_algorithm import build_fair_comparability_audit

    total_units = len(RELEASES) * UNITS_PER_RELEASE
    arguments = {
        "protocol": protocol,
        "left": left,
        "right": right,
        "alignment_fingerprint": protocol.alignment_fingerprint,
        "alignment_is_clean": True,
        "alignment_equal_pair_ids": total_units * len(_STAGES),
        "alignment_equal_pair_semantics": total_units * len(_STAGES),
        "alignment_equal_prepared_entries": total_units * 2,
        "expected_pairs": total_units * len(_STAGES),
        "expected_prepared_entries": total_units * 2,
    }
    arguments.update(overrides)
    return build_fair_comparability_audit(**arguments)


def unit_index(release: str, index: int) -> int:
    """The flat unit ordinal a ``(stage, index)`` outcome key refers to."""
    return _unit_keys().index((release, index))


def outcome_key(stage: ProtocolStage, release: str, index: int) -> tuple[str, int]:
    return (stage.value, unit_index(release, index))


def total_pairs() -> int:
    return len(RELEASES) * UNITS_PER_RELEASE * len(_STAGES)


def total_units() -> int:
    return len(RELEASES) * UNITS_PER_RELEASE


def stages() -> Sequence[ProtocolStage]:
    return _STAGES
