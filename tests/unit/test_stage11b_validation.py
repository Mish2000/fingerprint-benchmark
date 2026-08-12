"""Every stored VeriFinger result has to prove it came from the run it claims.

The stand-in adapter here declares the route's real identity and writes its real
result metadata, then lets each test corrupt exactly one field. No SDK, no
licence and no JVM are involved: what is under test is the validator, and a real
run would make it slower without making it stricter.

Three claims are specific to this route and every one is checked over every
stored row rather than once:

* the stored score is integer-valued, because VeriFinger returns a Java ``int``
  and fpbench transforms nothing (spec section 11);
* every comparison recorded two independent extractions, SELF included
  (spec section 14);
* every row names the same runtime closure, so a run whose DLLs changed halfway
  is a finding rather than a footnote (spec sections 16 and 31).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.verifinger_java.config import (
    BRIDGE_JAR_ROLE,
    RUNTIME_MANIFEST_ROLE,
    RUNTIME_POLICY_ROLE,
)
from fpbench.core.enums import (
    EnvironmentStatus,
    FailureCode,
    FailureStage,
    IntegrityIssueCode,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ArtifactReference,
    EnvironmentReport,
    FailureInfo,
    RawMatchResult,
)
from fpbench.experiments.verifinger_validation import (
    ALGORITHMIC_FAILURE_CODES,
    BLOCKING_FAILURE_CODES,
    validate_verifinger_result_set,
)
from fpbench.adapters.verifinger_java import identity
from runworld import build_world, write_fake_asset

pytestmark = pytest.mark.stage11b_contract

_PREFIX = identity.METADATA_PREFIX
_MANIFEST_FINGERPRINT = "a" * 64
_DEFAULT_SCORE = 137


def _result_metadata() -> dict[str, str]:
    return {
        f"{_PREFIX}algorithm_id": identity.ALGORITHM_ID,
        f"{_PREFIX}adapter_id": identity.ADAPTER_ID,
        f"{_PREFIX}adapter_version": identity.ADAPTER_VERSION,
        f"{_PREFIX}implementation_version": identity.IMPLEMENTATION_VERSION,
        f"{_PREFIX}vendor": identity.VENDOR,
        f"{_PREFIX}bridge_protocol": identity.BRIDGE_PROTOCOL,
        f"{_PREFIX}bridge_version": identity.BRIDGE_VERSION,
        f"{_PREFIX}integration_mode": identity.INTEGRATION_MODE,
        f"{_PREFIX}input_mode": "canonical_gray8_500ppi",
        f"{_PREFIX}left_ppi": "500",
        f"{_PREFIX}right_ppi": "500",
        f"{_PREFIX}probe_side": "left",
        f"{_PREFIX}extraction_policy": "independent_both_sides",
        f"{_PREFIX}template_cache": "disabled",
        f"{_PREFIX}score_cache": "disabled",
        f"{_PREFIX}matching_speed": identity.MATCHING_SPEED,
        f"{_PREFIX}native_score_type": identity.NATIVE_SCORE_TYPE,
        f"{_PREFIX}score_scale": identity.SCORE_SCALE,
        f"{_PREFIX}score_transformation_by_fpbench": (
            identity.SCORE_TRANSFORMATION_BY_FPBENCH
        ),
        f"{_PREFIX}runtime_manifest_fingerprint": _MANIFEST_FINGERPRINT,
        f"{_PREFIX}engine_status": "OK",
        f"{_PREFIX}extraction_count": "2",
    }


class StubVeriFinger(FingerprintAlgorithmAdapter):
    """The route's identity and metadata shape, with a constant integer score."""

    def __init__(self) -> None:
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=identity.ALGORITHM_ID,
            display_name=identity.DISPLAY_NAME,
            adapter_id=identity.ADAPTER_ID,
            adapter_version=identity.ADAPTER_VERSION,
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=identity.IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            metadata=dict(identity.PIPELINE_METADATA),
        )
        self.calls = 0
        self.overrides: dict[int, dict[str, str]] = {}
        self.removals: dict[int, tuple[str, ...]] = {}
        self.failures: dict[int, FailureInfo] = {}
        self.artifacts: dict[int, tuple[ArtifactReference, ...]] = {}
        self.scores: dict[int, float] = {}
        self.direction = ScoreDirection.HIGHER_IS_BETTER

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=identity.IMPLEMENTATION_VERSION,
            runtime={"java.version": "17.0.18"},
            dependencies={"verifinger.version": identity.IMPLEMENTATION_VERSION},
        )

    def compare(self, left, right, context) -> RawMatchResult:
        self.calls += 1
        metadata = _result_metadata()
        metadata.update(self.overrides.get(self.calls, {}))
        for key in self.removals.get(self.calls, ()):
            metadata.pop(key, None)
        artifacts = self.artifacts.get(self.calls, ())
        failure = self.failures.get(self.calls)
        if failure is not None:
            metadata[f"{_PREFIX}engine_status"] = "BAD_OBJECT"
            metadata.pop(f"{_PREFIX}extraction_count", None)
            metadata.update(self.overrides.get(self.calls, {}))
            return RawMatchResult.failed(
                failure=failure,
                score_direction=self.direction,
                artifacts=artifacts,
                metadata=metadata,
            )
        return RawMatchResult.success(
            raw_score=float(self.scores.get(self.calls, _DEFAULT_SCORE)),
            score_direction=self.direction,
            artifacts=artifacts,
            metadata=metadata,
        )


@pytest.fixture
def stub() -> StubVeriFinger:
    return StubVeriFinger()


@pytest.fixture
def world(tmp_path: Path, stub: StubVeriFinger):
    """A run pinned to all three of this route's runtime roles."""
    pinned = tmp_path / "pinned"
    assets = {
        BRIDGE_JAR_ROLE: write_fake_asset(
            pinned, b"PK\x03\x04not really the bridge\n", name="bridge.jar"
        ),
        RUNTIME_MANIFEST_ROLE: write_fake_asset(
            pinned, b"{}\n", name="verifinger_runtime_manifest_v1.json"
        ),
        RUNTIME_POLICY_ROLE: write_fake_asset(
            pinned, b"# not really the policy\n", name="policy.yaml"
        ),
    }
    built = build_world(tmp_path, adapter=stub, research=True, assets=assets)
    assert built.runtime_reference is not None
    return built


def validate(world, **extra):
    world.executor().execute(finalize=False)
    return validate_verifinger_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
        **extra,
    )


def codes(report) -> set[IntegrityIssueCode]:
    return {issue.code for issue in report.issues}


def failure(code: FailureCode, stage: FailureStage, **details: str) -> FailureInfo:
    return FailureInfo(code=code, stage=stage, message="synthetic", details=details)


# ------------------------------------------------------------------- clean


def test_a_well_formed_run_validates_cleanly(world):
    report = validate(world)
    assert report.is_clean, [issue.message for issue in report.issues]
    assert report.total_results == world.plan.total_jobs
    assert report.successful_results == world.plan.total_jobs
    assert report.algorithmic_failures == 0
    assert report.blocking_failures == 0
    assert report.failure_counts == {}
    assert report.logical_extraction_calls == world.plan.total_jobs * 2
    assert report.verify_invocations == world.plan.total_jobs
    assert report.engine_status_counts == {"OK": world.plan.total_jobs}


def test_the_validation_fingerprint_is_stable(world):
    first = validate(world)
    second = validate(world)
    assert first.validation_fingerprint == second.validation_fingerprint


# --------------------------------------------------------------- the score


def test_a_fractional_score_is_a_finding(world, stub):
    """VeriFinger returns a Java int; a fraction means something transformed it."""
    stub.scores[1] = 137.5
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_a_score_of_zero_is_a_perfectly_good_success(world, stub):
    stub.scores[1] = 0
    report = validate(world)
    assert report.is_clean
    assert report.successful_results == world.plan.total_jobs


def test_a_score_under_a_non_score_bearing_status_is_a_finding(world, stub):
    stub.overrides[2] = {f"{_PREFIX}engine_status": "BAD_OBJECT"}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


def test_a_score_under_match_not_found_is_accepted(world, stub):
    stub.overrides[3] = {f"{_PREFIX}engine_status": "MATCH_NOT_FOUND"}
    report = validate(world)
    assert report.is_clean


# ------------------------------------------------------------- extractions


def test_a_row_that_extracted_once_is_a_finding(world, stub):
    stub.overrides[1] = {f"{_PREFIX}extraction_count": "1"}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


def test_a_row_with_no_extraction_count_is_a_finding(world, stub):
    stub.removals[2] = (f"{_PREFIX}extraction_count",)
    report = validate(world)
    assert not report.is_clean


# ------------------------------------------------------------ the identity


@pytest.mark.parametrize(
    "key,value",
    [
        (f"{_PREFIX}algorithm_id", "something_else"),
        (f"{_PREFIX}adapter_id", "another_adapter"),
        (f"{_PREFIX}implementation_version", "2025.1"),
        (f"{_PREFIX}probe_side", "right"),
        (f"{_PREFIX}template_cache", "enabled"),
        (f"{_PREFIX}score_cache", "enabled"),
        (f"{_PREFIX}matching_speed", "HIGH"),
        (f"{_PREFIX}score_transformation_by_fpbench", "normalized"),
        (f"{_PREFIX}left_ppi", "1000"),
    ],
)
def test_a_row_that_misdescribes_the_route_is_a_finding(world, stub, key, value):
    stub.overrides[1] = {key: value}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


@pytest.mark.parametrize(
    "key",
    [
        "threshold",
        "decision",
        "is_match",
        "ground_truth",
        f"{_PREFIX}threshold",
        f"{_PREFIX}decision",
        f"{_PREFIX}sourceafis_score",
        f"{_PREFIX}nbis_score",
        f"{_PREFIX}flx_score",
    ],
)
def test_a_row_carrying_an_answer_is_a_finding(world, stub, key):
    stub.overrides[1] = {key: "yes"}
    report = validate(world)
    assert not report.is_clean


# --------------------------------------------------------- the runtime closure


def test_two_runtime_closures_in_one_run_is_a_finding(world, stub):
    stub.overrides[2] = {f"{_PREFIX}runtime_manifest_fingerprint": "b" * 64}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in codes(report)


def test_a_run_under_a_different_closure_than_the_experiment_pins(world):
    report = validate(world, expected_runtime_manifest_fingerprint="c" * 64)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in codes(report)


def test_the_expected_closure_matching_is_clean(world):
    report = validate(world, expected_runtime_manifest_fingerprint=_MANIFEST_FINGERPRINT)
    assert report.is_clean


# ------------------------------------------------------------- the failures


def test_a_declined_print_is_data_and_the_run_stays_clean(world, stub):
    stub.failures[2] = failure(
        FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureStage.EXTRACTION
    )
    report = validate(world)
    assert report.is_clean
    assert report.algorithmic_failures == 1
    assert report.blocking_failures == 0
    assert report.successful_results == world.plan.total_jobs - 1
    assert report.total_results == world.plan.total_jobs
    # A declined print still consumed the route: both sides were extracted.
    assert report.logical_extraction_calls == world.plan.total_jobs * 2
    assert report.verify_invocations == world.plan.total_jobs


@pytest.mark.parametrize(
    "code,stage",
    [
        (FailureCode.DEPENDENCY_MISSING, FailureStage.ADAPTER),
        (FailureCode.PROCESS_CRASHED, FailureStage.ADAPTER),
        (FailureCode.INTERNAL_ERROR, FailureStage.ADAPTER),
        (FailureCode.TIMEOUT, FailureStage.TIMEOUT),
        (FailureCode.INPUT_INVALID, FailureStage.INPUT),
        (FailureCode.UNSUPPORTED_RESOLUTION, FailureStage.INPUT),
        (FailureCode.NO_SCORE, FailureStage.MATCHING),
    ],
)
def test_an_infrastructure_failure_blocks_the_run(world, stub, code, stage):
    stub.failures[2] = failure(code, stage)
    report = validate(world)
    assert not report.is_clean
    assert report.blocking_failures == 1
    assert IntegrityIssueCode.RESULT_BLOCKING_FAILURE in codes(report)


def test_an_unclassified_failure_code_is_never_guessed_at(world, stub):
    stub.failures[2] = failure(FailureCode.PREPARATION_FAILED, FailureStage.PREPARATION)
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_UNKNOWN_FAILURE_CODE in codes(report)


def test_the_two_failure_sets_do_not_overlap():
    assert not (ALGORITHMIC_FAILURE_CODES & BLOCKING_FAILURE_CODES)


# ------------------------------------------------------------- the run itself


def test_a_run_defined_for_another_algorithm_is_a_finding(world, stub, tmp_path):
    stub._descriptor = AlgorithmDescriptor(
        algorithm_id="some_other_algorithm",
        display_name="x",
        adapter_id=identity.ADAPTER_ID,
        adapter_version=identity.ADAPTER_VERSION,
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        implementation_version=identity.IMPLEMENTATION_VERSION,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        deterministic=True,
    )
    rebuilt = build_world(
        tmp_path / "second",
        adapter=stub,
        research=True,
        assets={
            BRIDGE_JAR_ROLE: write_fake_asset(
                tmp_path / "second-pinned", b"jar\n", name="bridge.jar"
            ),
            RUNTIME_MANIFEST_ROLE: write_fake_asset(
                tmp_path / "second-pinned", b"{}\n", name="manifest.json"
            ),
            RUNTIME_POLICY_ROLE: write_fake_asset(
                tmp_path / "second-pinned", b"policy\n", name="policy.yaml"
            ),
        },
    )
    report = validate(rebuilt)
    assert not report.is_clean
    assert IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH in codes(report)
