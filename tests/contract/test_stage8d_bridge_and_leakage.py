"""The join to the decision layer, and the boundary that keeps it honest.

Two halves that only look unrelated.

The **bridge** proves that an operating point can become a `DecisionProfile` with
origin `CALIBRATED_DEVELOPMENT` — the first artifact in this project entitled to
that origin — and that the profile carries the three links which make the claim
checkable rather than assertable.

The **leakage boundary** proves that no such operating point can be produced from
evaluation data in the first place. A bridge without it would be a very careful
route to a threshold chosen on the cohort it is reported on.

Everything here runs on synthetic fixtures. No production profile is created, and
nothing is written to a workspace (docs/adr/0078).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fpbench.calibration.models import LabeledResults, LabeledScore
from fpbench.calibration.profiles import (
    CALIBRATED_PROFILE_SCHEMA_VERSION,
    derive_calibrated_decision_profile,
)
from fpbench.calibration.protocol import (
    build_calibration_source_binding,
    impostor_ceiling_protocol,
)
from fpbench.calibration.selection import select_operating_point
from fpbench.calibration.validation import (
    require_unprotected_source,
    validate_calibration_inputs,
)
from fpbench.core.calibration_errors import (
    CalibrationBridgeError,
    CalibrationLeakageError,
)
from fpbench.core.decision_models import (
    DECISION_PROFILE_SCHEMA_VERSIONS,
    DecisionProfile,
    ThresholdOrigin,
    decision_profile_fingerprint,
)
from fpbench.core.enums import (
    CalibrationPairTruth,
    CohortRole,
    ExecutionStatus,
    ProtectedIdentityKind,
    ScoreDirection,
)
from fpbench.core.errors import DecisionProfileError
from fpbench.experiments import stage8d_identity as frozen
from fpbench.experiments.stage8d_calibration_infrastructure import (
    RegistryCoverage,
    build_registry,
)

pytestmark = pytest.mark.stage8d_contract

MATED = CalibrationPairTruth.MATED
IMPOSTOR = CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR
HIGHER = ScoreDirection.HIGHER_IS_BETTER
COMMIT = "0" * 40
WHEN = "2026-08-07T12:00:00Z"


def a_registry():
    """The real frozen registry, built without reading the published evidence."""
    return build_registry()


def synthetic_results() -> LabeledResults:
    rows = [
        LabeledScore(
            pair_id=f"m{index}",
            truth=MATED,
            execution_status=ExecutionStatus.SUCCESS,
            score=Decimal(score),
        )
        for index, score in enumerate(["5", "6", "7", "8"])
    ]
    rows += [
        LabeledScore(
            pair_id=f"i{index}",
            truth=IMPOSTOR,
            execution_status=ExecutionStatus.SUCCESS,
            score=Decimal(score),
        )
        for index, score in enumerate(["1", "2", "3", "4"])
    ]
    return LabeledResults(score_direction=HIGHER, rows=tuple(rows))


def synthetic_binding(**overrides):
    fields = dict(
        binding_id="synthetic_binding_v1",
        algorithm_id="synthetic_matcher",
        algorithm_fingerprint="a" * 64,
        integration_id="synthetic_integration",
        integration_fingerprint="b" * 64,
        run_id="run_synthetic01",
        run_fingerprint="c" * 64,
        result_set_id="resultset_syn01",
        result_set_fingerprint="d" * 64,
        dataset_id="synthetic_dataset",
        dataset_fingerprint="e" * 64,
        cohort_id="synthetic_dev_cohort",
        cohort_fingerprint="f" * 64,
        cohort_role=CohortRole.DEVELOPMENT,
        pair_manifest_id="synthetic_pairs",
        pair_manifest_fingerprint="1" * 64,
        score_direction=HIGHER,
    )
    fields.update(overrides)
    return build_calibration_source_binding(**fields)


def an_operating_point(**binding_overrides):
    protocol = impostor_ceiling_protocol(
        protocol_id="synthetic_quarter_v1", numerator=1, denominator=4
    )
    return protocol, select_operating_point(
        protocol,
        synthetic_binding(**binding_overrides),
        synthetic_results(),
        protected_registry=a_registry(),
        created_source_commit=COMMIT,
        created_source_tree_clean=True,
        created_utc=WHEN,
    )


# --------------------------------------------------------------- the bridge


def test_an_operating_point_becomes_a_calibrated_decision_profile() -> None:
    _protocol, point = an_operating_point()
    profile = derive_calibrated_decision_profile(
        point,
        implementation_version="synthetic-1.0",
        allowed_execution_profiles=("canonical_500",),
    )
    assert profile.origin is ThresholdOrigin.CALIBRATED_DEVELOPMENT
    assert profile.schema_version == CALIBRATED_PROFILE_SCHEMA_VERSION == "3"
    assert profile.calibration_performed is True
    assert profile.threshold == point.threshold
    assert profile.comparator is point.comparator
    assert profile.score_direction is point.score_direction
    assert profile.algorithm_fingerprint == point.algorithm_fingerprint


def test_the_profile_points_back_at_all_three_calibration_artifacts() -> None:
    """Spec section 21: operating point, protocol, and development source."""
    protocol, point = an_operating_point()
    profile = derive_calibrated_decision_profile(
        point,
        implementation_version="synthetic-1.0",
        allowed_execution_profiles=("canonical_500",),
    )
    assert profile.calibration_operating_point_fingerprint == (
        point.operating_point_fingerprint
    )
    assert profile.calibration_protocol_fingerprint == protocol.protocol_fingerprint
    assert profile.calibration_source_binding_fingerprint == (
        point.source_binding_fingerprint
    )
    assert profile.calibration_manifest_fingerprint == (
        point.operating_point_fingerprint
    )


def test_the_three_links_are_inside_the_profile_identity() -> None:
    """Repointing a profile at another operating point makes it another profile."""
    _protocol, point = an_operating_point()
    profile = derive_calibrated_decision_profile(
        point,
        implementation_version="synthetic-1.0",
        allowed_execution_profiles=("canonical_500",),
    )
    with pytest.raises(DecisionProfileError):
        DecisionProfile(
            **{
                **{
                    field: getattr(profile, field)
                    for field in profile.__slots__
                    if field != "calibration_protocol_fingerprint"
                },
                "calibration_protocol_fingerprint": "9" * 64,
            }
        )


def test_a_calibrated_profile_without_the_links_is_refused() -> None:
    _protocol, point = an_operating_point()
    profile = derive_calibrated_decision_profile(
        point,
        implementation_version="synthetic-1.0",
        allowed_execution_profiles=("canonical_500",),
    )
    fields = {field: getattr(profile, field) for field in profile.__slots__}
    fields["calibration_source_binding_fingerprint"] = None
    with pytest.raises(DecisionProfileError, match="must name"):
        DecisionProfile(**fields)


def test_a_schema_one_or_two_profile_may_not_carry_a_calibration_link() -> None:
    """docs/adr/0055: a claim outside the fingerprint is worse than no claim."""
    for version in ("1", "2"):
        with pytest.raises(DecisionProfileError, match="no place for"):
            DecisionProfile(
                profile_id="legacy_v1",
                profile_fingerprint="0" * 64,
                display_name="legacy",
                profile_version="1",
                algorithm_id="synthetic_matcher",
                implementation_version="1.0",
                algorithm_fingerprint="a" * 64,
                score_direction=HIGHER,
                comparator=__import__(
                    "fpbench.core.enums", fromlist=["ThresholdComparator"]
                ).ThresholdComparator.GREATER_THAN_OR_EQUAL,
                threshold="40",
                origin=ThresholdOrigin.DOCUMENTED_NATIVE,
                source_kind="documentation",
                source_reference="somewhere",
                source_version="1",
                allowed_execution_profiles=("canonical_500",),
                calibration_performed=False,
                schema_version=version,
                calibration_protocol_fingerprint="b" * 64,
            )


def test_the_bridge_requires_what_the_operating_point_cannot_know() -> None:
    _protocol, point = an_operating_point()
    with pytest.raises(CalibrationBridgeError, match="execution profiles"):
        derive_calibrated_decision_profile(
            point,
            implementation_version="synthetic-1.0",
            allowed_execution_profiles=(),
        )
    with pytest.raises(CalibrationBridgeError, match="implementation version"):
        derive_calibrated_decision_profile(
            point,
            implementation_version="  ",
            allowed_execution_profiles=("canonical_500",),
        )


def test_the_yaml_loader_still_refuses_a_calibrated_origin() -> None:
    """A config file can assert a calibration; only an artifact can evidence one."""
    from fpbench.decisions.profiles import ALLOWED_ORIGINS

    assert ALLOWED_ORIGINS == frozenset({ThresholdOrigin.DOCUMENTED_NATIVE})


def test_stage_8d_produces_no_production_decision_profile() -> None:
    """docs/adr/0078: the bridge is proven synthetically and used nowhere else."""
    from pathlib import Path

    import fpbench

    configs = Path(fpbench.__file__).resolve().parents[2] / "configs" / "decisions"
    for path in sorted(configs.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "calibrated_development" not in text
        assert "schema_version: \"3\"" not in text


# -------------------------------------------------------- the leakage boundary


def test_a_binding_that_resolves_to_a_protected_result_set_is_refused() -> None:
    """docs/adr/0079: the claim is checked against the identities, not believed."""
    protected = next(
        fingerprint
        for kind, _identity, fingerprint, _label in frozen.PROTECTED_IDENTITIES
        if kind is ProtectedIdentityKind.RESULT_SET
    )
    with pytest.raises(CalibrationLeakageError, match="protected evaluation"):
        require_unprotected_source(
            synthetic_binding(result_set_fingerprint=protected), a_registry()
        )


def test_a_binding_that_reuses_a_protected_identity_is_refused() -> None:
    """A re-declared run id under a fresh digest is what a mistake looks like."""
    protected_run = next(
        identity
        for kind, identity, _fingerprint, _label in frozen.PROTECTED_IDENTITIES
        if kind is ProtectedIdentityKind.RUN
    )
    with pytest.raises(CalibrationLeakageError, match="protected evaluation"):
        require_unprotected_source(
            synthetic_binding(run_id=protected_run), a_registry()
        )


def test_a_binding_that_claims_development_over_protected_data_is_still_refused():
    """The declared role does not rescue it, which is the whole point."""
    protected_cohort = next(
        fingerprint
        for kind, _identity, fingerprint, _label in frozen.PROTECTED_IDENTITIES
        if kind is ProtectedIdentityKind.COHORT
    )
    binding = synthetic_binding(
        cohort_role=CohortRole.DEVELOPMENT, cohort_fingerprint=protected_cohort
    )
    assert binding.cohort_role is CohortRole.DEVELOPMENT
    with pytest.raises(CalibrationLeakageError, match="identities say otherwise"):
        require_unprotected_source(binding, a_registry())


def test_running_without_the_registry_is_refused_rather_than_allowed() -> None:
    """A calibration that never loaded the registry looks exactly like a clean one."""
    protocol = impostor_ceiling_protocol(
        protocol_id="synthetic_quarter_v1", numerator=1, denominator=4
    )
    with pytest.raises(CalibrationLeakageError, match="needs the protected"):
        validate_calibration_inputs(
            protocol=protocol,
            source_binding=synthetic_binding(),
            labeled_results=synthetic_results(),
            protected_registry=None,
        )


def test_the_registry_registers_every_executed_algorithms_result_set() -> None:
    """Three algorithms have run the canonical 6,000; three result sets protected."""
    coverage = RegistryCoverage.of(a_registry())
    coverage.require_every_executed_algorithm_is_registered(3)
    assert coverage.by_kind[ProtectedIdentityKind.RUN.value] == 3
    assert coverage.by_kind[ProtectedIdentityKind.COHORT.value] == 1
    assert coverage.by_kind[ProtectedIdentityKind.PAIR_MANIFEST.value] == 1
    assert coverage.total == len(frozen.PROTECTED_IDENTITIES)


def test_the_registry_holds_no_score_and_no_count_of_scores() -> None:
    import json

    from fpbench.core.serialization import to_plain

    text = json.dumps(to_plain(a_registry())).lower()
    for token in ("score", "threshold", "histogram", "success_count", "planned"):
        assert token not in text


# ------------------------------------------------- backward compatibility


#: The identities four decision sets, four eligibility sets, four metric sets and
#: every receipt above them cite. Stage 8D adds a schema; it may not move one of
#: these by a single character (spec section 22).
PUBLISHED_PROFILE_FINGERPRINTS = {
    "sourceafis_java_3_18_1_documented_40_v1.yaml": (
        "02be9e07d28522b657f4fed3ee930b4c117573403926ad919b745274d6b6de4c"
    ),
    "sourceafis_java_3_18_1_documented_40_canonical500_v1.yaml": (
        "a9550e9dfd0ce54f6538d395a32c5e354db3bd4a9cbafff4cf0268e88fc78b75"
    ),
}


def test_the_two_published_schema_one_profiles_have_not_moved() -> None:
    from pathlib import Path

    import fpbench
    from fpbench.decisions import load_decision_profile

    configs = Path(fpbench.__file__).resolve().parents[2] / "configs" / "decisions"
    for filename, fingerprint in sorted(PUBLISHED_PROFILE_FINGERPRINTS.items()):
        profile = load_decision_profile(
            configs / filename,
            algorithm_fingerprint=(
                "5a1784faae1e82c12c374e050fcd6cfd41aa25b7a9ade3905d099df2e06a9531"
            ),
        )
        assert profile.schema_version == "1"
        assert profile.profile_fingerprint == fingerprint


def test_adding_schema_three_did_not_change_the_schema_one_or_two_mappings() -> None:
    """The direct check: the same profile, hashed under 1 and 2, is unmoved.

    The literals below were computed before schema 3 existed. If either mapping
    had grown a field — which is what "just add the calibration keys to the
    existing hash" would have done — both would move at once and every artefact
    citing them would stop verifying.
    """
    from fpbench.core.enums import ThresholdComparator

    def probe(schema_version: str) -> DecisionProfile:
        fields = dict(
            profile_id="regression_probe_v1",
            display_name="regression probe",
            profile_version="1",
            algorithm_id="probe_matcher",
            implementation_version="1.0",
            algorithm_fingerprint="a" * 64,
            score_direction=HIGHER,
            comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL,
            threshold="40",
            origin=ThresholdOrigin.DOCUMENTED_NATIVE,
            source_kind="documentation",
            source_reference="upstream",
            source_version="1",
            allowed_execution_profiles=("canonical_500",),
            calibration_performed=False,
            metadata={},
            schema_version=schema_version,
        )

        class Probe:
            def __init__(self) -> None:
                for name, value in fields.items():
                    setattr(self, name, value)
                self.calibration_manifest_fingerprint = None
                self.calibration_operating_point_fingerprint = None
                self.calibration_protocol_fingerprint = None
                self.calibration_source_binding_fingerprint = None

        fingerprint = decision_profile_fingerprint(Probe())
        return DecisionProfile(profile_fingerprint=fingerprint, **fields)

    assert probe("1").profile_fingerprint == (
        "25699d667ff5cb3ce7592f6f8d1a4d739da841dbb3c2902f56ccb97c0e422698"
    )
    assert probe("2").profile_fingerprint == (
        "d680435dd6599cb87c979616848e5f5c3a87f5929091f1d16c39d986bb824656"
    )


def test_the_three_schema_versions_produce_three_different_identities() -> None:
    """A schema-3 profile can never collide with a schema-1 or schema-2 one."""
    assert DECISION_PROFILE_SCHEMA_VERSIONS == ("1", "2", "3")
    _protocol, point = an_operating_point()
    profile = derive_calibrated_decision_profile(
        point,
        implementation_version="synthetic-1.0",
        allowed_execution_profiles=("canonical_500",),
    )
    assert profile.profile_fingerprint == decision_profile_fingerprint(profile)
    assert profile.profile_fingerprint not in PUBLISHED_PROFILE_FINGERPRINTS.values()
