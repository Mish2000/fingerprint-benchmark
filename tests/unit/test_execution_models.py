"""The invariants that keep a stored result from lying."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ArtifactReference,
    ComparisonContext,
    EnvironmentReport,
    ExecutionProfile,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
    TimingBreakdown,
    descriptor_fingerprint,
    environment_fingerprint,
    execution_profile_fingerprint,
)
from fpbench.core.identifiers import InvalidIdentifierError
from fakes import fake_descriptor, sha256_of

DIGEST = sha256_of("image")
OTHER_DIGEST = sha256_of("other")
ABS = Path.cwd().resolve()


def prepared(**overrides) -> PreparedImage:
    defaults = dict(
        image_id="sd300a_00001000_plain_f01",
        local_path=ABS / "a.png",
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=DIGEST,
        checksum_status=ChecksumStatus.NOT_VERIFIED,
        preparation_profile_id="identity_png_v1",
        preparation_hash=OTHER_DIGEST,
    )
    return PreparedImage(**{**defaults, **overrides})


def artifact(**overrides) -> ArtifactReference:
    defaults = dict(
        artifact_id="template_left",
        kind="template",
        relative_path="artifacts/run_x/job_y/left.tpl",
        sha256=DIGEST,
        size_bytes=128,
    )
    return ArtifactReference(**{**defaults, **overrides})


def failure(**overrides) -> FailureInfo:
    defaults = dict(
        code=FailureCode.MATCHING_FAILED,
        stage=FailureStage.MATCHING,
        message="matcher refused the pair",
    )
    return FailureInfo(**{**defaults, **overrides})


# ---------------------------------------------------------------- PreparedImage


def test_prepared_image_normalises_a_digest_to_lowercase():
    assert prepared(expected_sha256=DIGEST.upper()).expected_sha256 == DIGEST


def test_prepared_image_rejects_a_relative_local_path():
    with pytest.raises(ValueError, match="absolute"):
        prepared(local_path=Path("a.png"))


@pytest.mark.parametrize("ppi", [0, -500])
def test_prepared_image_rejects_a_non_positive_resolution(ppi):
    with pytest.raises(ValueError, match="effective_ppi"):
        prepared(effective_ppi=ppi)


@pytest.mark.parametrize("digest", ["", "abc", "z" * 64])
def test_prepared_image_rejects_a_malformed_digest(digest):
    with pytest.raises(ValueError, match="hexadecimal"):
        prepared(expected_sha256=digest)


def test_prepared_image_rejects_a_malformed_preparation_hash():
    with pytest.raises(ValueError, match="preparation_hash"):
        prepared(preparation_hash="not-a-hash")


def test_prepared_image_rejects_an_unusable_profile_id():
    with pytest.raises(InvalidIdentifierError):
        prepared(preparation_profile_id="Identity PNG")


def test_prepared_image_carries_nothing_that_identifies_the_comparison():
    forbidden = {
        "subject_id",
        "position",
        "impression",
        "pair_id",
        "ground_truth",
        "protocol_stage",
    }
    assert forbidden.isdisjoint(PreparedImage.__dataclass_fields__)


# ------------------------------------------------------------ ArtifactReference


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "C:\\Windows\\system32", "../outside.tpl", "a/../../b"]
)
def test_artifact_paths_must_stay_inside_the_workspace(path):
    with pytest.raises(ValueError):
        artifact(relative_path=path)


def test_artifact_rejects_a_negative_size():
    with pytest.raises(ValueError, match="size_bytes"):
        artifact(size_bytes=-1)


def test_artifact_metadata_is_detached_from_the_caller():
    supplied = {"k": "v"}
    reference = artifact(metadata=supplied)
    supplied["k"] = "tampered"
    assert reference.metadata["k"] == "v"
    with pytest.raises(TypeError):
        reference.metadata["k"] = "tampered"


# ------------------------------------------------------------------ FailureInfo


def test_failure_needs_a_message():
    with pytest.raises(ValueError, match="message"):
        failure(message="   ")


def test_failure_details_are_frozen():
    info = failure(details={"exception_type": "RuntimeError"})
    with pytest.raises(TypeError):
        info.details["exception_type"] = "other"


# --------------------------------------------------------------- RawMatchResult


def test_success_factory_produces_a_scored_result():
    result = RawMatchResult.success(
        raw_score=12.5, score_direction=ScoreDirection.HIGHER_IS_BETTER
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == 12.5
    assert result.failure is None


def test_failed_factory_produces_an_explained_result():
    result = RawMatchResult.failed(
        failure=failure(), score_direction=ScoreDirection.HIGHER_IS_BETTER
    )
    assert result.status is ExecutionStatus.FAILURE
    assert result.raw_score is None
    assert result.failure is not None


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf])
def test_a_success_must_carry_a_finite_score(score):
    with pytest.raises(ValueError, match="finite"):
        RawMatchResult.success(
            raw_score=score, score_direction=ScoreDirection.HIGHER_IS_BETTER
        )


def test_a_success_cannot_also_be_a_failure():
    with pytest.raises(ValueError, match="must not carry a failure"):
        RawMatchResult(
            status=ExecutionStatus.SUCCESS,
            raw_score=1.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            failure=failure(),
        )


def test_a_failure_cannot_carry_a_score():
    with pytest.raises(ValueError, match="must not carry a score"):
        RawMatchResult(
            status=ExecutionStatus.FAILURE,
            raw_score=1.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            failure=failure(),
        )


def test_a_failure_must_explain_itself():
    with pytest.raises(ValueError, match="explain itself"):
        RawMatchResult(
            status=ExecutionStatus.FAILURE,
            raw_score=None,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            failure=None,
        )


def test_a_success_must_carry_a_score():
    with pytest.raises(ValueError, match="must carry a score"):
        RawMatchResult(
            status=ExecutionStatus.SUCCESS,
            raw_score=None,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
        )


def test_artifact_ids_must_be_unique_within_a_result():
    with pytest.raises(ValueError, match="unique"):
        RawMatchResult.success(
            raw_score=1.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(artifact(), artifact(relative_path="artifacts/b.tpl")),
        )


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf])
def test_component_timings_must_be_finite_and_non_negative(value):
    with pytest.raises(ValueError, match="timing_components_ms"):
        RawMatchResult.success(
            raw_score=1.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            timing_components_ms={"extract": value},
        )


def test_result_carries_no_decision_field():
    forbidden = {"decision", "threshold", "is_match", "matched", "ground_truth"}
    assert forbidden.isdisjoint(RawMatchResult.__dataclass_fields__)


# ---------------------------------------------------------- AlgorithmDescriptor


def test_descriptor_sorts_and_deduplicates_capabilities():
    descriptor = AlgorithmDescriptor(
        algorithm_id="x",
        display_name="X",
        adapter_id="x",
        adapter_version="1",
        adapter_contract_version="1",
        implementation_version="1",
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        deterministic=True,
        capabilities=("b", "a", "b"),
    )
    assert descriptor.capabilities == ("a", "b")


def test_descriptor_rejects_an_unusable_algorithm_id():
    with pytest.raises(InvalidIdentifierError):
        fake_descriptor("Not An Id")


def test_descriptor_allows_a_dotted_implementation_version():
    """Versions are opaque strings; only the two ids follow the id charset."""
    descriptor = AlgorithmDescriptor(
        algorithm_id="x",
        display_name="X",
        adapter_id="x",
        adapter_version="1.4.2",
        adapter_contract_version="1",
        implementation_version="sha256:9f2c",
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        deterministic=True,
    )
    assert descriptor.implementation_version == "sha256:9f2c"


def test_descriptor_fingerprint_is_64_characters():
    assert len(descriptor_fingerprint(fake_descriptor("x"))) == 64


def test_descriptor_fingerprint_ignores_the_display_name():
    """Renaming a matcher in a report must not invalidate its results."""
    base = fake_descriptor("x")
    renamed = replace(base, display_name="A Completely Different Name")
    assert descriptor_fingerprint(renamed) == descriptor_fingerprint(base)


@pytest.mark.parametrize(
    "change",
    [
        {"implementation_version": "test-2"},
        {"adapter_version": "2"},
        {"adapter_contract_version": "2"},
        {"score_direction": ScoreDirection.LOWER_IS_BETTER},
        {"deterministic": False},
        {"capabilities": ("template_extraction",)},
    ],
)
def test_descriptor_fingerprint_tracks_everything_that_changes_results(change):
    base = fake_descriptor("x")
    assert descriptor_fingerprint(replace(base, **change)) != descriptor_fingerprint(
        base
    )


# ------------------------------------------------------------ EnvironmentReport


def environment(**overrides) -> EnvironmentReport:
    defaults = dict(
        status=EnvironmentStatus.READY,
        implementation_version="test-1",
        runtime={"python": "3.12.0"},
        dependencies={},
    )
    return EnvironmentReport(**{**defaults, **overrides})


def test_environment_fingerprint_is_64_characters():
    assert len(environment_fingerprint(environment())) == 64


def test_environment_fingerprint_ignores_the_message():
    assert environment_fingerprint(
        environment(message="warmed up")
    ) == environment_fingerprint(environment())


def test_environment_fingerprint_tracks_dependencies():
    assert environment_fingerprint(
        environment(dependencies={"nbis": "5.0.0"})
    ) != environment_fingerprint(environment())


# ------------------------------------------------------------- ExecutionProfile


def profile(**overrides) -> ExecutionProfile:
    defaults = dict(
        profile_id="identity_png_v1",
        preparer_id="identity",
        timeout_seconds=10.0,
        deterministic_seed=0,
    )
    return ExecutionProfile(**{**defaults, **overrides})


@pytest.mark.parametrize("timeout", [0, -1, math.inf, math.nan])
def test_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        profile(timeout_seconds=timeout)


def test_profile_fingerprint_tracks_the_seed():
    assert execution_profile_fingerprint(
        profile(deterministic_seed=1)
    ) != execution_profile_fingerprint(profile())


def test_profile_holds_no_threshold():
    forbidden = {"threshold", "decision_profile", "decision_profiles"}
    assert forbidden.isdisjoint(ExecutionProfile.__dataclass_fields__)


# ------------------------------------------------------------ ComparisonContext


def context(**overrides) -> ComparisonContext:
    defaults = dict(
        run_id="run_abc123",
        job_id="job_def456",
        attempt=1,
        working_directory=ABS / "work",
        artifact_directory=ABS / "artifacts",
        timeout_seconds=10.0,
        deterministic_seed=0,
    )
    return ComparisonContext(**{**defaults, **overrides})


def test_context_rejects_a_zero_attempt():
    with pytest.raises(ValueError, match="1-based"):
        context(attempt=0)


def test_context_directories_must_be_absolute():
    with pytest.raises(ValueError, match="working_directory"):
        context(working_directory=Path("work"))


def test_context_tells_an_adapter_nothing_about_the_pair():
    """docs/adr/0010 in executable form."""
    forbidden = {
        "pair_id",
        "protocol_stage",
        "ground_truth",
        "subject_id",
        "finger_position",
        "position",
        "threshold",
        "decision_profile",
    }
    assert forbidden.isdisjoint(ComparisonContext.__dataclass_fields__)


# -------------------------------------------------------------- TimingBreakdown


def test_a_total_must_cover_its_parts():
    with pytest.raises(ValueError, match="smaller than the sum"):
        TimingBreakdown(preparation_ms=10.0, adapter_ms=10.0, total_ms=1.0)


def test_measurement_noise_is_tolerated():
    TimingBreakdown(preparation_ms=1.0, adapter_ms=1.0, total_ms=1.9999)


@pytest.mark.parametrize("value", [-0.1, math.nan, math.inf])
def test_durations_must_be_finite_and_non_negative(value):
    with pytest.raises(ValueError):
        TimingBreakdown(preparation_ms=value, adapter_ms=0.0, total_ms=100.0)
