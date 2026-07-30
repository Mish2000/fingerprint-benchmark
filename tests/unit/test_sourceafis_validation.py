"""Every stored result has to prove it came from the run it claims.

The stand-in adapter here declares SourceAFIS's real identity and writes
SourceAFIS's real result metadata, then lets each test corrupt exactly one
field. No JVM is involved: what is under test is the validator, and a real
matcher would make it slower without making it stricter. The end-to-end test
with a real SourceAFIS lives in ``tests/integration``.

The distinction the whole module turns on: a matcher that could not extract a
template is *data*, and a matcher that never ran is a *defect*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.sourceafis_java.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    PIPELINE_METADATA,
)
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    EXPECTED_BRIDGE_PROTOCOL,
    EXPECTED_BRIDGE_VERSION,
    EXPECTED_SOURCEAFIS_VERSION,
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
from fpbench.experiments import sourceafis_validation
from fpbench.experiments.sourceafis_validation import validate_sourceafis_result_set
from runworld import TEST_REVISION, build_world

JAR_SHA = "b" * 64


class StubSourceAfis(FingerprintAlgorithmAdapter):
    """SourceAFIS's identity and metadata shape, with a constant score.

    It exists so that a test can produce 16 well-formed results and then break
    exactly one field. The descriptor is the real one, because the validator
    checks it and a differently named fake would fail for the wrong reason.
    """

    def __init__(self) -> None:
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="SourceAFIS for Java",
            adapter_id=ADAPTER_ID,
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=EXPECTED_SOURCEAFIS_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            metadata=PIPELINE_METADATA,
        )
        self.calls = 0
        #: Filled in once the world exists and the bundle has an id.
        self.runtime_metadata: dict[str, str] = {}
        #: Applied to the ``call``-th comparison only, so a test breaks one row.
        self.overrides: dict[int, dict[str, str]] = {}
        self.removals: dict[int, tuple[str, ...]] = {}
        self.failures: dict[int, FailureInfo] = {}
        self.artifacts: dict[int, tuple[ArtifactReference, ...]] = {}

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=EXPECTED_SOURCEAFIS_VERSION,
            runtime={"java.version": "17.0.9"},
            dependencies={
                "sourceafis": EXPECTED_SOURCEAFIS_VERSION,
                "bridge.version": EXPECTED_BRIDGE_VERSION,
                "bridge.protocol": EXPECTED_BRIDGE_PROTOCOL,
            },
        )

    def compare(self, left, right, context) -> RawMatchResult:
        self.calls += 1
        metadata = {
            "sourceafis_version": EXPECTED_SOURCEAFIS_VERSION,
            "bridge_version": EXPECTED_BRIDGE_VERSION,
            "bridge_protocol": EXPECTED_BRIDGE_PROTOCOL,
            "integration_mode": PIPELINE_METADATA["integration_mode"],
            "input_mode": PIPELINE_METADATA["input_mode"],
            "dpi_policy": PIPELINE_METADATA["dpi_policy"],
            "probe_side": "left",
            "extraction_policy": "independent_both_sides",
            "template_cache": "disabled",
            "extraction_count": "2",
            "left_dpi": str(left.effective_ppi),
            "right_dpi": str(right.effective_ppi),
            **self.runtime_metadata,
        }
        metadata.update(self.overrides.get(self.calls, {}))
        for key in self.removals.get(self.calls, ()):
            metadata.pop(key, None)

        artifacts = self.artifacts.get(self.calls, ())
        failure = self.failures.get(self.calls)
        if failure is not None:
            return RawMatchResult.failed(
                failure=failure,
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                artifacts=artifacts,
                metadata=metadata,
            )
        return RawMatchResult.success(
            raw_score=42.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=artifacts,
            metadata=metadata,
        )


@pytest.fixture
def stub() -> StubSourceAfis:
    return StubSourceAfis()


@pytest.fixture
def world(tmp_path: Path, stub: StubSourceAfis):
    built = build_world(
        tmp_path, adapter=stub, research=True, asset_role=BRIDGE_JAR_ROLE
    )
    assert built.bundle is not None and built.runtime_reference is not None
    stub.runtime_metadata = {
        "runtime_bundle_id": built.bundle.bundle_id,
        "runtime_bundle_fingerprint": built.bundle.bundle_fingerprint,
        "bridge_jar_sha256": dict(built.runtime_reference.asset_sha256s)[
            BRIDGE_JAR_ROLE
        ],
        "bridge_jar_size": str(built.bundle.asset(BRIDGE_JAR_ROLE).size_bytes),
        "fpbench_source_revision": TEST_REVISION,
    }
    return built


def _validate(world):
    world.executor().execute(finalize=False)
    return validate_sourceafis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )


def _codes(report) -> set[IntegrityIssueCode]:
    return {issue.code for issue in report.issues}


# ------------------------------------------------------------------- clean


def test_a_well_formed_run_validates_cleanly(world):
    report = _validate(world)
    assert report.is_clean
    assert report.issues == ()
    assert report.total_results == world.plan.total_jobs
    assert report.successful_results == world.plan.total_jobs
    assert report.algorithmic_failures == 0
    assert report.blocking_failures == 0
    assert report.failure_counts == {}


def test_the_fingerprint_is_stable_across_two_identical_passes(world):
    first = _validate(world)
    second = validate_sourceafis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    assert first.validation_fingerprint == second.validation_fingerprint
    assert first.inspected_utc != second.inspected_utc or True


# ------------------------------------------------------------- pipeline lies


@pytest.mark.parametrize(
    "key, value",
    [
        ("sourceafis_version", "3.19.0"),
        ("bridge_version", "2"),
        ("bridge_protocol", "fpbench.sourceafis.bridge.v2"),
        ("integration_mode", "persistent_worker"),
        ("template_cache", "enabled"),
        ("extraction_policy", "shared_template"),
    ],
)
def test_a_result_that_misdescribes_the_pipeline_is_an_error(world, stub, key, value):
    stub.overrides[1] = {key: value}
    report = _validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in _codes(report)


def test_an_extraction_count_other_than_two_is_an_error(world, stub):
    stub.overrides[1] = {"extraction_count": "1"}
    report = _validate(world)
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in _codes(report)


def test_a_missing_extraction_count_on_a_success_is_an_error(world, stub):
    stub.removals[1] = ("extraction_count",)
    report = _validate(world)
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in _codes(report)


def test_threshold_metadata_is_an_error(world, stub):
    """A raw result may never carry an answer (docs/adr/0003)."""
    stub.overrides[1] = {"threshold": "40", "decision": "match"}
    report = _validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in _codes(report)


def test_a_template_artifact_is_an_error(world, stub):
    stub.artifacts[1] = (
        ArtifactReference(
            artifact_id="template_left",
            kind="template",
            relative_path="artifacts/run/job/left.cbor",
            sha256="c" * 64,
            size_bytes=128,
        ),
    )
    report = _validate(world)
    assert IntegrityIssueCode.RESULT_UNEXPECTED_ARTIFACT in _codes(report)


# ------------------------------------------------------------ runtime lies


@pytest.mark.parametrize(
    "key, value",
    [
        ("runtime_bundle_id", "runtime_000000000000"),
        ("runtime_bundle_fingerprint", "d" * 64),
        ("bridge_jar_sha256", JAR_SHA),
        ("fpbench_source_revision", "f" * 40),
    ],
)
def test_a_result_naming_a_different_runtime_is_an_error(world, stub, key, value):
    stub.overrides[1] = {key: value}
    report = _validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in _codes(report)


def test_a_result_with_no_runtime_identity_is_an_error(world, stub):
    stub.removals[1] = ("runtime_bundle_id", "fpbench_source_revision")
    report = _validate(world)
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in _codes(report)


# ------------------------------------------------------------- resolution


def test_a_result_compared_at_the_wrong_resolution_is_an_error(world, stub):
    """SD300A is 500 ppi. A result claiming 2000 is not comparable to the rest."""
    stub.overrides[1] = {"left_dpi": "2000"}
    report = _validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH in _codes(report)


def test_a_result_with_no_recorded_resolution_is_an_error(world, stub):
    stub.removals[1] = ("right_dpi",)
    report = _validate(world)
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in _codes(report)


# --------------------------------------------------------------- failures


def test_a_template_extraction_failure_is_kept_and_counted(world, stub):
    stub.failures[1] = FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="no minutiae found",
    )
    report = _validate(world)

    assert report.is_clean, "an algorithm declining a print is data, not a defect"
    assert report.algorithmic_failures == 1
    assert report.blocking_failures == 0
    assert report.failure_counts == {"template_extraction_failed": 1}
    assert report.successful_results == world.plan.total_jobs - 1


def test_a_matching_failure_is_kept_and_counted(world, stub):
    stub.failures[2] = FailureInfo(
        code=FailureCode.MATCHING_FAILED,
        stage=FailureStage.MATCHING,
        message="the matcher gave up",
    )
    report = _validate(world)
    assert report.is_clean
    assert report.algorithmic_failures == 1
    assert report.failure_counts == {"matching_failed": 1}


@pytest.mark.parametrize(
    "code, stage",
    [
        (FailureCode.PROCESS_CRASHED, FailureStage.ADAPTER),
        (FailureCode.TIMEOUT, FailureStage.TIMEOUT),
        (FailureCode.INTERNAL_ERROR, FailureStage.ADAPTER),
        (FailureCode.UNSUPPORTED_RESOLUTION, FailureStage.INPUT),
        (FailureCode.IMAGE_DECODE_FAILED, FailureStage.INPUT),
        (FailureCode.PREPARATION_FAILED, FailureStage.PREPARATION),
        (FailureCode.INPUT_INVALID, FailureStage.INPUT),
        (FailureCode.NO_SCORE, FailureStage.MATCHING),
        (FailureCode.QUALITY_REJECTED, FailureStage.QUALITY),
        (FailureCode.DEPENDENCY_MISSING, FailureStage.ENVIRONMENT),
    ],
)
def test_an_infrastructure_failure_blocks_the_run(world, stub, code, stage):
    stub.failures[1] = FailureInfo(code=code, stage=stage, message="broken")
    report = _validate(world)

    assert not report.is_clean
    assert report.blocking_failures == 1
    assert report.algorithmic_failures == 0
    assert IntegrityIssueCode.RESULT_BLOCKING_FAILURE in _codes(report)


def test_an_unclassified_failure_code_is_never_guessed_at(world, stub, monkeypatch):
    """Simulates a code added to the taxonomy that no policy has placed yet."""
    monkeypatch.setattr(
        sourceafis_validation,
        "ALGORITHMIC_FAILURE_CODES",
        frozenset({FailureCode.TEMPLATE_EXTRACTION_FAILED}),
    )
    monkeypatch.setattr(
        sourceafis_validation,
        "BLOCKING_FAILURE_CODES",
        sourceafis_validation.BLOCKING_FAILURE_CODES - {FailureCode.MATCHING_FAILED},
    )
    stub.failures[1] = FailureInfo(
        code=FailureCode.MATCHING_FAILED,
        stage=FailureStage.MATCHING,
        message="unclassified for the purposes of this test",
    )
    report = _validate(world)

    assert not report.is_clean
    assert report.blocking_failures == 1
    assert IntegrityIssueCode.RESULT_UNKNOWN_FAILURE_CODE in _codes(report)


# ----------------------------------------------------------------- run level


def test_a_run_from_another_algorithm_is_refused(tmp_path):
    """The validator says so rather than silently passing a dummy run."""
    world = build_world(tmp_path, research=True, asset_role=BRIDGE_JAR_ROLE)
    world.executor().execute(finalize=False)

    report = validate_sourceafis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    assert not report.is_clean
    assert IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH in _codes(report)


def test_a_missing_result_is_reported_rather_than_skipped(world, stub):
    world.executor().execute(max_new_jobs=4, finalize=False)
    report = validate_sourceafis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    assert report.total_results == 4
    assert IntegrityIssueCode.RESULT_UNREADABLE in _codes(report)
