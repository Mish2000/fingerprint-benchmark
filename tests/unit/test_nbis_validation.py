"""Every stored NBIS result has to prove it came from the run it claims.

The stand-in adapter here declares the route's real identity and writes its real
result metadata, then lets each test corrupt exactly one field. No NBIS is
involved: what is under test is the validator, and a real build would make it
slower without making it stricter.

The distinction the whole module turns on is three-valued rather than two:

* MINDTCT declining a print, or a comparison outrunning its budget, is **data**;
* MINDTCT exiting zero and writing an unreadable XYT is a **defect**, even though
  it carries the same failure code as the first case;
* everything else that stopped a comparison is a defect too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.nbis.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    IMPLEMENTATION_VERSION,
    PIPELINE_METADATA,
    RESULT_METADATA,
)
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
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
from fpbench.experiments.nbis_validation import (
    ALGORITHMIC_FAILURE_CODES,
    BLOCKING_FAILURE_CODES,
    SD300_CANONICAL500_INPUT_SET,
    ExpectedInputSet,
    validate_nbis_result_set,
)
from runworld import build_world, write_fake_asset

pytestmark = pytest.mark.nbis_contract


class StubNbis(FingerprintAlgorithmAdapter):
    """The route's identity and metadata shape, with a constant score.

    It exists so a test can produce a handful of well-formed results and then
    break exactly one field. The descriptor is the real one, because the
    validator checks it and a differently named fake would fail for the wrong
    reason.
    """

    def __init__(self) -> None:
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="NBIS MINDTCT + BOZORTH3",
            adapter_id=ADAPTER_ID,
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            metadata=PIPELINE_METADATA,
        )
        self.calls = 0
        self.overrides: dict[int, dict[str, str]] = {}
        self.removals: dict[int, tuple[str, ...]] = {}
        self.failures: dict[int, FailureInfo] = {}
        self.artifacts: dict[int, tuple[ArtifactReference, ...]] = {}
        self.scores: dict[int, float] = {}
        self.environment_overrides: dict[str, str | None] = {}

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        dependencies = {
            "nbis.version": IMPLEMENTATION_VERSION,
            "nbis.build_manifest_fingerprint": "f" * 64,
            "nbis.png_ppi_policy": "metadata_ignored_default_500",
        }
        for key, value in self.environment_overrides.items():
            if value is None:
                dependencies.pop(key, None)
            else:
                dependencies[key] = value
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=IMPLEMENTATION_VERSION,
            runtime={"nbis.target_os": "linux"},
            dependencies=dependencies,
        )

    def compare(self, left, right, context) -> RawMatchResult:
        self.calls += 1
        metadata = {
            **RESULT_METADATA,
            "extraction_count": "2",
            "left_minutiae_count": "34",
            "right_minutiae_count": "31",
        }
        metadata.update(self.overrides.get(self.calls, {}))
        for key in self.removals.get(self.calls, ()):
            metadata.pop(key, None)

        artifacts = self.artifacts.get(self.calls, ())
        failure = self.failures.get(self.calls)
        if failure is not None:
            metadata.pop("extraction_count", None)
            metadata.update(self.overrides.get(self.calls, {}))
            return RawMatchResult.failed(
                failure=failure,
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                artifacts=artifacts,
                metadata=metadata,
            )
        return RawMatchResult.success(
            raw_score=self.scores.get(self.calls, 42.0),
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=artifacts,
            metadata=metadata,
        )


@pytest.fixture
def stub() -> StubNbis:
    return StubNbis()


@pytest.fixture
def world(tmp_path: Path, stub: StubNbis):
    """A run pinned to all three of this route's runtime roles."""
    build = tmp_path / "build"
    assets = {
        MINDTCT_ROLE: write_fake_asset(build, b"not really mindtct", name="mindtct"),
        BOZORTH3_ROLE: write_fake_asset(build, b"not really bozorth3", name="bozorth3"),
        BUILD_MANIFEST_ROLE: write_fake_asset(
            build, b"{}", name="nbis-build-manifest.json"
        ),
    }
    built = build_world(tmp_path, adapter=stub, research=True, assets=assets)
    assert built.runtime_reference is not None
    return built


def validate(world, **extra):
    world.executor().execute(finalize=False)
    return validate_nbis_result_set(
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
    return FailureInfo(
        code=code, stage=stage, message="synthetic", details=details
    )


# ------------------------------------------------------------------- clean


def test_a_well_formed_run_validates_cleanly(world):
    report = validate(world)
    assert report.is_clean, [issue.message for issue in report.issues]
    assert report.total_results == world.plan.total_jobs
    assert report.successful_results == world.plan.total_jobs
    assert report.algorithmic_failures == 0
    assert report.blocking_failures == 0
    assert report.failure_counts == {}


def test_the_fingerprint_is_stable_across_two_identical_passes(world):
    first = validate(world)
    second = validate_nbis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    assert first.validation_fingerprint == second.validation_fingerprint


def test_a_zero_score_is_an_ordinary_success(world, stub):
    """Section 43: not a failure, not undecidable, not filtered out."""
    stub.scores = {1: 0.0, 2: 0.0}
    report = validate(world)
    assert report.is_clean
    assert report.successful_results == world.plan.total_jobs


# ------------------------------------------------------------ classification


def test_a_declined_print_is_data_rather_than_a_defect(world, stub):
    stub.failures[1] = failure(
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
        output_kind="nonzero_exit",
    )
    report = validate(world)
    assert report.is_clean
    assert report.algorithmic_failures == 1
    assert report.blocking_failures == 0
    assert report.failure_counts == {"template_extraction_failed": 1}


def test_a_timeout_is_data_rather_than_a_defect(world, stub):
    """Section 36: MINDTCT's work is unbounded in the input."""
    stub.failures[1] = failure(
        FailureCode.TIMEOUT, FailureStage.TIMEOUT, output_kind="timed_out"
    )
    report = validate(world)
    assert report.is_clean
    assert report.algorithmic_failures == 1


def test_an_unreadable_xyt_is_a_defect_despite_sharing_a_code(world, stub):
    """The subtle case: same failure code, opposite meaning (section 30)."""
    stub.failures[1] = failure(
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
        output_kind="invalid_extractor_output",
    )
    report = validate(world)
    assert not report.is_clean
    assert report.blocking_failures == 1
    assert report.algorithmic_failures == 0
    assert IntegrityIssueCode.RESULT_BLOCKING_FAILURE in codes(report)


@pytest.mark.parametrize(
    "code,stage",
    [
        (FailureCode.INPUT_INVALID, FailureStage.INPUT),
        (FailureCode.PREPARATION_FAILED, FailureStage.PREPARATION),
        (FailureCode.MATCHING_FAILED, FailureStage.MATCHING),
        (FailureCode.NO_SCORE, FailureStage.MATCHING),
        (FailureCode.PROCESS_CRASHED, FailureStage.EXTRACTION),
        (FailureCode.INTERNAL_ERROR, FailureStage.ADAPTER),
    ],
)
def test_every_infrastructure_failure_blocks_a_receipt(world, stub, code, stage):
    stub.failures[1] = failure(code, stage)
    report = validate(world)
    assert not report.is_clean
    assert report.blocking_failures == 1
    assert IntegrityIssueCode.RESULT_BLOCKING_FAILURE in codes(report)


def test_the_two_classifications_do_not_overlap():
    assert not (ALGORITHMIC_FAILURE_CODES & BLOCKING_FAILURE_CODES)


def test_every_failure_code_is_classified_deliberately():
    """An unclassified code is blocked and named, never guessed at."""
    covered = ALGORITHMIC_FAILURE_CODES | BLOCKING_FAILURE_CODES
    missing = sorted(code.value for code in FailureCode if code not in covered)
    assert missing == [], missing


# ---------------------------------------------------------- pipeline lies


@pytest.mark.parametrize(
    "key,value",
    [
        ("nbis_version", "5.0.1"),
        ("ppi_policy", "declared_by_metadata"),
        ("effective_ppi", "1000"),
        ("input_transport", "converted_to_pgm"),
        ("mindtct_contrast_boost", "enabled"),
        ("mindtct_m1", "enabled"),
        ("bozorth3_threshold", "40"),
        ("bozorth3_max_minutiae", "100"),
        ("bozorth3_min_minutiae", "20"),
        ("template_cache", "enabled"),
        ("template_persistence", "enabled"),
        ("extraction_policy", "shared_template"),
        ("probe_side", "right"),
    ],
)
def test_a_result_that_misdescribes_the_route_is_an_error(world, stub, key, value):
    stub.overrides[1] = {key: value}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


@pytest.mark.parametrize("key", sorted(RESULT_METADATA))
def test_every_required_metadata_key_is_actually_required(world, stub, key):
    stub.removals[1] = (key,)
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


def test_an_extraction_count_other_than_two_is_an_error(world, stub):
    stub.overrides[1] = {"extraction_count": "1"}
    report = validate(world)
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


def test_a_missing_extraction_count_on_a_success_is_an_error(world, stub):
    stub.removals[1] = ("extraction_count",)
    report = validate(world)
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


def test_a_missing_minutiae_count_on_a_success_is_an_error(world, stub):
    stub.removals[1] = ("left_minutiae_count",)
    report = validate(world)
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


def test_a_minutiae_count_that_is_not_a_count_is_an_error(world, stub):
    stub.overrides[1] = {"right_minutiae_count": "several"}
    report = validate(world)
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


def test_threshold_metadata_is_an_error(world, stub):
    """A raw result may never carry an answer (docs/adr/0003)."""
    stub.overrides[1] = {"threshold": "40", "decision": "match"}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


@pytest.mark.parametrize("key", ["template", "minutiae", "xyt", "score"])
def test_publishing_an_intermediate_in_metadata_is_an_error(world, stub, key):
    stub.overrides[1] = {key: "..."}
    report = validate(world)
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


def test_an_xyt_artifact_is_an_error(world, stub):
    """Section 32: no template is published, ever."""
    stub.artifacts[1] = (
        ArtifactReference(
            artifact_id="left_template",
            kind="template",
            relative_path="artifacts/run/job/left-nbis.xyt",
            sha256="c" * 64,
            size_bytes=128,
        ),
    )
    report = validate(world)
    assert IntegrityIssueCode.RESULT_UNEXPECTED_ARTIFACT in codes(report)


# ------------------------------------------------------------- runtime lies


@pytest.mark.parametrize(
    "key,value",
    [("nbis.version", "5.0.1"), ("nbis.png_ppi_policy", "declared_by_metadata")],
)
def test_a_run_whose_environment_names_another_build_is_an_error(
    tmp_path, stub, key, value
):
    stub.environment_overrides = {key: value}
    world = build_world(
        tmp_path,
        adapter=stub,
        research=True,
        assets={
            MINDTCT_ROLE: write_fake_asset(tmp_path / "b", b"m", name="mindtct"),
            BOZORTH3_ROLE: write_fake_asset(tmp_path / "b", b"b", name="bozorth3"),
            BUILD_MANIFEST_ROLE: write_fake_asset(
                tmp_path / "b", b"{}", name="nbis-build-manifest.json"
            ),
        },
    )
    report = validate(world)
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


def test_a_run_with_no_build_manifest_fingerprint_is_an_error(tmp_path, stub):
    stub.environment_overrides = {"nbis.build_manifest_fingerprint": None}
    world = build_world(
        tmp_path,
        adapter=stub,
        research=True,
        assets={
            MINDTCT_ROLE: write_fake_asset(tmp_path / "b", b"m", name="mindtct"),
            BOZORTH3_ROLE: write_fake_asset(tmp_path / "b", b"b", name="bozorth3"),
            BUILD_MANIFEST_ROLE: write_fake_asset(
                tmp_path / "b", b"{}", name="nbis-build-manifest.json"
            ),
        },
    )
    report = validate(world)
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in codes(report)


def test_a_runtime_missing_one_of_the_three_roles_is_an_error(tmp_path, stub):
    """Section 11: the identity of this route is the whole bundle."""
    world = build_world(
        tmp_path,
        adapter=stub,
        research=True,
        assets={
            MINDTCT_ROLE: write_fake_asset(tmp_path / "b", b"m", name="mindtct"),
            BOZORTH3_ROLE: write_fake_asset(tmp_path / "b", b"b", name="bozorth3"),
        },
    )
    report = validate(world)
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in codes(report)
    assert "nbis_build_manifest" in " ".join(i.message for i in report.issues)


# -------------------------------------------------------------- the score


def test_a_negative_score_is_an_error(world, stub):
    stub.scores = {1: -1.0}
    report = validate(world)
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_a_fractional_score_is_an_error(world, stub):
    """BOZORTH3 prints integers; a fraction means something else wrote it."""
    stub.scores = {1: 42.5}
    report = validate(world)
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


# ---------------------------------------------------------- the input set


def test_the_sd300_canonical_input_set_is_named_before_it_is_used():
    """Section 37: the check exists before stage 7C's run does."""
    assert SD300_CANONICAL500_INPUT_SET == ExpectedInputSet(
        preparation_set_id="prepset_be560e047991",
        transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
        target_ppi=500,
        entry_count=3000,
    )


def test_a_run_over_delivered_bytes_needs_no_input_set(world):
    """``preparation=None`` is the identity preparer's honest answer."""
    report = validate(world, preparation=None)
    assert report.is_clean
