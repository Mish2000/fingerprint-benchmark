"""Every stored flx result has to prove it came from the run it claims.

The stand-in adapter here declares the route's real identity and writes its real
result metadata, then lets each test corrupt exactly one field. No torch and no
checkpoint are involved: what is under test is the validator, and a real
inference run would make it slower without making it stricter.

Two claims are specific to this route and both are checked over every stored
row rather than once:

* the canonical decimal text is re-derived from the stored double, so a row
  where something rounded is a finding (docs/adr/0077);
* every comparison recorded two preprocess calls and two logical extractions,
  so a SELF row that took a shortcut is a finding (spec section 9).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.experiments.flx_adapter import RAW_SCORE_DECIMAL_METADATA_KEY
from fpbench.experiments.flx_adapter import (
    RUNTIME_LOCK_ROLE,
    RUNTIME_POLICY_ROLE,
    WORKER_SCRIPT_ROLE,
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
from fpbench.experiments.flx_validation import (
    ALGORITHMIC_FAILURE_CODES,
    BLOCKING_FAILURE_CODES,
    SD300_CANONICAL500_INPUT_SET,
    ExpectedInputSet,
    validate_flx_result_set,
)
from fpbench.flx import identity
from fpbench.flx.integration import build_adapter_profile
from fpbench.flx.preprocessing import build_preprocessing_profile
from fpbench.flx.representation import build_representation_profile
from fpbench.flx.score import build_score_profile, canonical_decimal_text
from runworld import build_world, write_fake_asset

pytestmark = pytest.mark.stage8c_contract

_DEFAULT_SCORE = 0.42314159265358979


def _result_metadata() -> dict[str, str]:
    return {
        "flx.algorithm_id": identity.ALGORITHM_ID,
        "flx.adapter_id": identity.ADAPTER_ID,
        "flx.adapter_version": str(identity.ADAPTER_VERSION),
        "flx.runtime_profile_id": identity.RUNTIME_PROFILE_ID,
        "flx.preprocessing_profile_id": identity.PREPROCESSING_PROFILE_ID,
        "flx.preprocessing_profile_fingerprint": (
            build_preprocessing_profile().fingerprint
        ),
        "flx.representation_profile_id": identity.REPRESENTATION_PROFILE_ID,
        "flx.representation_profile_fingerprint": (
            build_representation_profile().fingerprint
        ),
        "flx.score_profile_id": identity.SCORE_PROFILE_ID,
        "flx.score_profile_fingerprint": build_score_profile().fingerprint,
        "flx.score_serialization_profile_id": identity.SCORE_SERIALIZATION_PROFILE_ID,
        "flx.inference_batch_rows": str(identity.INFERENCE_BATCH_ROWS),
        "flx.inference_batch_rule": identity.INFERENCE_BATCH_RULE,
        "flx.represented_row": str(identity.REPRESENTED_ROW),
        "flx.side_independence": "separate_preprocess_and_extract_per_side",
        "flx.preprocess_calls": "2",
        "flx.logical_extraction_calls": "2",
        "flx.physical_forward_rows": "4",
        "flx.comparison_calls": "1",
    }


class StubFlx(FingerprintAlgorithmAdapter):
    """The route's identity and metadata shape, with a constant score."""

    def __init__(self) -> None:
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=identity.ALGORITHM_ID,
            display_name="flx DeepPrint TexMinu 512 (without localization)",
            adapter_id=identity.ADAPTER_ID,
            adapter_version=str(identity.ADAPTER_VERSION),
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=identity.SOURCE_COMMIT,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            metadata={
                "adapter_profile_fingerprint": build_adapter_profile().fingerprint
            },
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
            implementation_version=identity.SOURCE_COMMIT,
            runtime={"flx.runtime_profile_id": identity.RUNTIME_PROFILE_ID},
            dependencies={"flx.checkpoint_sha256": identity.CHECKPOINT_SHA256},
        )

    def compare(self, left, right, context) -> RawMatchResult:
        self.calls += 1
        metadata = _result_metadata()
        score = self.scores.get(self.calls, _DEFAULT_SCORE)
        metadata[RAW_SCORE_DECIMAL_METADATA_KEY] = canonical_decimal_text(score)
        metadata.update(self.overrides.get(self.calls, {}))
        for key in self.removals.get(self.calls, ()):
            metadata.pop(key, None)

        artifacts = self.artifacts.get(self.calls, ())
        failure = self.failures.get(self.calls)
        if failure is not None:
            metadata.pop(RAW_SCORE_DECIMAL_METADATA_KEY, None)
            for key in (
                "flx.preprocess_calls",
                "flx.logical_extraction_calls",
                "flx.physical_forward_rows",
                "flx.comparison_calls",
            ):
                metadata.pop(key, None)
            metadata.update(self.overrides.get(self.calls, {}))
            return RawMatchResult.failed(
                failure=failure,
                score_direction=self.direction,
                artifacts=artifacts,
                metadata=metadata,
            )
        return RawMatchResult.success(
            raw_score=score,
            score_direction=self.direction,
            artifacts=artifacts,
            metadata=metadata,
        )


@pytest.fixture
def stub() -> StubFlx:
    return StubFlx()


@pytest.fixture
def world(tmp_path: Path, stub: StubFlx):
    """A run pinned to all three of this route's runtime roles."""
    pinned = tmp_path / "pinned"
    assets = {
        WORKER_SCRIPT_ROLE: write_fake_asset(
            pinned, b"# not really the worker\n", name="flx_worker.py"
        ),
        RUNTIME_LOCK_ROLE: write_fake_asset(
            pinned, b"# not really the lock\n", name="flx_runtime_lock_v1.txt"
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
    return validate_flx_result_set(
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


def test_the_operation_counts_are_measured_over_the_stored_results(world):
    report = validate(world)
    jobs = world.plan.total_jobs
    assert report.preprocess_calls == 2 * jobs
    assert report.logical_extraction_calls == 2 * jobs
    assert report.physical_forward_rows == 4 * jobs
    assert report.comparison_calls == jobs
    # docs/adr/0075: the two extraction counts are different numbers and the
    # relationship between them is Stage 8B's batch rule.
    assert report.physical_forward_rows == (
        report.logical_extraction_calls * identity.INFERENCE_BATCH_ROWS
    )


def test_the_fingerprint_is_stable_across_two_identical_passes(world):
    first = validate(world)
    second = validate_flx_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    assert first.validation_fingerprint == second.validation_fingerprint


@pytest.mark.parametrize("score", [0.0, -1.75, 2.0000001192092896, -2.0])
def test_zero_negative_and_slightly_over_two_are_ordinary_successes(
    world, stub, score: float
):
    """docs/adr/0076: none of these is a failure and none of them is a decision."""
    stub.scores = {index: score for index in range(1, world.plan.total_jobs + 1)}
    report = validate(world)
    assert report.is_clean, [issue.message for issue in report.issues]
    assert report.successful_results == world.plan.total_jobs


# ------------------------------------------------------------ the Decimal rule


def test_a_decimal_that_does_not_match_the_stored_double_is_a_finding(world, stub):
    stub.overrides = {1: {RAW_SCORE_DECIMAL_METADATA_KEY: "0.5"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_a_rounded_decimal_is_a_finding(world, stub):
    # The whole point of 17 significant digits: 0.42314159 is the same number to
    # eight digits and a different number to seventeen.
    stub.overrides = {1: {RAW_SCORE_DECIMAL_METADATA_KEY: "0.42314159"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_a_success_with_no_canonical_decimal_is_a_finding(world, stub):
    stub.removals = {1: (RAW_SCORE_DECIMAL_METADATA_KEY,)}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_a_non_numeric_decimal_is_a_finding(world, stub):
    stub.overrides = {1: {RAW_SCORE_DECIMAL_METADATA_KEY: "not a number"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_a_non_finite_decimal_is_a_finding(world, stub):
    stub.overrides = {1: {RAW_SCORE_DECIMAL_METADATA_KEY: "Infinity"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


@pytest.mark.parametrize("score", [2.5, -2.5, 3.0])
def test_a_score_outside_the_fingerprinted_range_is_a_finding(world, stub, score):
    stub.scores = {1: score}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


def test_the_range_allowance_is_the_fingerprinted_one_and_not_wider(world, stub):
    tolerance = Decimal(identity.SCORE_RANGE_VALIDATION_TOLERANCE)
    just_inside = float(Decimal("2") + tolerance)
    stub.scores = {1: just_inside}
    assert validate(world).is_clean


def test_a_failure_that_still_carries_a_decimal_is_a_finding(world, stub):
    stub.failures = {
        1: failure(FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureStage.EXTRACTION)
    }
    stub.overrides = {1: {RAW_SCORE_DECIMAL_METADATA_KEY: "0.5"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_SCORE_INVALID in codes(report)


# --------------------------------------------------------- side independence


@pytest.mark.parametrize(
    "key, wrong",
    [
        ("flx.preprocess_calls", "1"),
        ("flx.logical_extraction_calls", "1"),
        ("flx.physical_forward_rows", "2"),
        ("flx.comparison_calls", "2"),
    ],
)
def test_a_comparison_that_took_a_shortcut_is_a_finding(world, stub, key, wrong):
    stub.overrides = {1: {key: wrong}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


def test_a_result_that_forgot_to_say_the_sides_were_independent_is_a_finding(
    world, stub
):
    stub.removals = {1: ("flx.side_independence",)}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


# ------------------------------------------------------------------ identity


@pytest.mark.parametrize(
    "key",
    [
        "flx.algorithm_id",
        "flx.adapter_id",
        "flx.runtime_profile_id",
        "flx.preprocessing_profile_id",
        "flx.representation_profile_id",
        "flx.score_profile_id",
        "flx.inference_batch_rule",
    ],
)
def test_a_result_naming_another_route_is_a_finding(world, stub, key):
    stub.overrides = {1: {key: "something_else_v1"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


@pytest.mark.parametrize(
    "key",
    [
        "flx.preprocessing_profile_fingerprint",
        "flx.representation_profile_fingerprint",
        "flx.score_profile_fingerprint",
    ],
)
def test_a_profile_fingerprint_that_moved_is_a_finding(world, stub, key):
    stub.overrides = {1: {key: "0" * 64}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)


@pytest.mark.parametrize(
    "key",
    [
        "flx.embedding",
        "flx.representation",
        "flx.texture_vector",
        "flx.tensor",
        "flx.threshold",
        "flx.decision",
        "flx.sourceafis_score",
        "flx.nbis_score",
        "flx.ground_truth",
    ],
)
def test_a_result_carrying_forbidden_metadata_is_a_finding(world, stub, key):
    """spec section 15: no embedding, no threshold, no prior-algorithm field."""
    stub.overrides = {1: {key: "present"}}
    report = validate(world)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


def test_a_run_defined_for_another_algorithm_is_a_finding(world, stub, tmp_path):
    from fpbench.core.result_models import RunDefinition

    other = AlgorithmDescriptor(
        algorithm_id="some_other_matcher",
        display_name="other",
        adapter_id="some_other_adapter",
        adapter_version="1",
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        implementation_version="1",
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        deterministic=True,
    )
    world.executor().execute(finalize=False)
    hijacked = RunDefinition(
        run_id=world.run.run_id,
        run_fingerprint=world.run.run_fingerprint,
        protocol_id=world.run.protocol_id,
        cohort_id=world.run.cohort_id,
        pair_manifest_hash=world.run.pair_manifest_hash,
        algorithm=other,
        algorithm_fingerprint=world.run.algorithm_fingerprint,
        environment=world.run.environment,
        environment_fingerprint=world.run.environment_fingerprint,
        execution_profile=world.run.execution_profile,
        execution_profile_hash=world.run.execution_profile_hash,
        replicate_index=world.run.replicate_index,
        created_utc=world.run.created_utc,
    )
    report = validate_flx_result_set(
        run=hijacked,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.image_index,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    assert not report.is_clean
    assert IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH in codes(report)


# ------------------------------------------------------------------ failures


@pytest.mark.parametrize("code", sorted(ALGORITHMIC_FAILURE_CODES, key=lambda c: c.value))
def test_an_algorithmic_failure_is_data_and_keeps_the_run_clean(world, stub, code):
    stub.failures = {1: failure(code, FailureStage.EXTRACTION)}
    report = validate(world)
    assert report.is_clean, [issue.message for issue in report.issues]
    assert report.algorithmic_failures == 1
    assert report.blocking_failures == 0
    assert report.failure_counts == {code.value: 1}
    assert report.successful_results == world.plan.total_jobs - 1


@pytest.mark.parametrize("code", sorted(BLOCKING_FAILURE_CODES, key=lambda c: c.value))
def test_a_blocking_failure_stops_the_run_being_clean(world, stub, code):
    stub.failures = {1: failure(code, FailureStage.ADAPTER)}
    report = validate(world)
    assert not report.is_clean
    assert report.blocking_failures == 1
    assert IntegrityIssueCode.RESULT_BLOCKING_FAILURE in codes(report)


def test_success_plus_algorithmic_failure_accounts_for_every_planned_job(world, stub):
    """spec section 16.3: the receipt distinguishes outcomes from scores."""
    stub.failures = {
        1: failure(FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureStage.EXTRACTION),
        2: failure(FailureCode.TIMEOUT, FailureStage.TIMEOUT),
    }
    report = validate(world)
    assert report.is_clean
    assert report.total_results == world.plan.total_jobs
    assert report.successful_results + report.algorithmic_failures == report.total_results
    assert report.blocking_failures == 0


# ------------------------------------------------------------- the input set


def _expectations(world, **overrides):
    """What a set-backed run's results must claim about their inputs.

    Built over the world's own images so the entries actually resolve. This
    exists because the ``preparation is not None`` branch is the one finalize
    takes, and a validator tested only with ``preparation=None`` leaves it
    unexecuted — which is exactly how a missing keyword argument survived the
    whole contract suite and surfaced only when the real run finalised.
    """
    import hashlib

    from fpbench.core.imaging_models import (
        PreparedImageEntry,
        prepared_image_entry_hash,
    )
    from fpbench.experiments.prepared_input_validation import PreparedInputExpectations

    def digest(label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()

    class _Draft:
        def __init__(self, **fields: object) -> None:
            for name, value in fields.items():
                setattr(self, name, value)

    entries = {}
    for ordinal, image_id in enumerate(sorted(world.image_index)):
        fields = dict(
            ordinal=ordinal,
            image_id=image_id,
            source_record_fingerprint=digest(f"{image_id}-source-record"),
            source_expected_sha256=digest(f"{image_id}-source"),
            source_size_bytes=1024,
            source_effective_ppi=1000,
            source_declared_ppi="1000",
            source_width=800,
            source_height=800,
            source_pixel_sha256=digest(f"{image_id}-source-pixels"),
            transform_profile_id=SD300_CANONICAL500_INPUT_SET.transform_profile_id,
            transform_profile_fingerprint=digest("profile"),
            transform_runtime_fingerprint=digest("runtime"),
            transform_action="downsample_lanczos3",
            scale_numerator=500,
            scale_denominator=1000,
            output_width=400,
            output_height=400,
            output_effective_ppi=500,
            output_pixel_sha256=digest(f"{image_id}-out-pixels"),
            output_encoded_sha256=digest(f"{image_id}-out-encoded"),
            output_size_bytes=512,
            output_media_type="image/png",
            relative_path=f"prepared-images/set/{image_id}.png",
        )
        entries[image_id] = PreparedImageEntry(
            **fields, entry_hash=prepared_image_entry_hash(_Draft(**fields))
        )
    settings: dict[str, object] = {
        "execution_profile_id": world.run.execution_profile.profile_id,
        "preparer_id": "canonical_500_png",
        "preparer_version": "1",
        "runner_metadata_schema": "canonical_prepared_v1",
        "preparation_set_id": SD300_CANONICAL500_INPUT_SET.preparation_set_id,
        "preparation_set_fingerprint": digest("set"),
        "transform_profile_id": SD300_CANONICAL500_INPUT_SET.transform_profile_id,
        "transform_profile_fingerprint": digest("profile"),
        "transform_runtime_fingerprint": digest("runtime"),
        "target_ppi": 500,
        "entries": entries,
    }
    settings.update(overrides)
    return PreparedInputExpectations(**settings)  # type: ignore[arg-type]


def test_the_set_backed_branch_runs_at_all(world):
    """The branch finalize takes, executed rather than assumed.

    It does not matter here whether the synthetic world's releases satisfy the
    resolution rule — what matters is that the code path executes end to end
    and returns a report instead of raising.
    """
    report = validate(world, preparation=_expectations(world))
    assert report.total_results == world.plan.total_jobs
    assert isinstance(report.validation_fingerprint, str)


def test_a_run_from_another_input_set_is_a_finding(world):
    report = validate(
        world,
        preparation=_expectations(world),
        expected_input_set=ExpectedInputSet(
            preparation_set_id="prepset_somewhere_else",
            transform_profile_id="another_transform_v1",
            target_ppi=1000,
            entry_count=17,
        ),
    )
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(report)


def test_the_declared_input_set_is_accepted(world):
    report = validate(
        world,
        preparation=_expectations(world),
        expected_input_set=ExpectedInputSet(
            preparation_set_id=SD300_CANONICAL500_INPUT_SET.preparation_set_id,
            transform_profile_id=SD300_CANONICAL500_INPUT_SET.transform_profile_id,
            target_ppi=500,
            entry_count=len(world.image_index),
        ),
    )
    assert not any(
        issue.code is IntegrityIssueCode.RESULT_PIPELINE_MISMATCH
        and "input set" in issue.message
        for issue in report.issues
    )


def test_expected_source_ppi_is_checked_when_the_run_declares_one(world):
    """The exact call that was missing a keyword argument."""
    report = validate(
        world,
        preparation=_expectations(
            world, expected_source_ppi={"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
        ),
    )
    assert isinstance(report.validation_fingerprint, str)


def test_the_canonical_input_set_is_the_one_stage_6a_materialised():
    assert SD300_CANONICAL500_INPUT_SET.preparation_set_id == "prepset_be560e047991"
    assert SD300_CANONICAL500_INPUT_SET.entry_count == 3000
    assert SD300_CANONICAL500_INPUT_SET.target_ppi == 500


# ------------------------------------------------------------------ runtime


def test_a_run_missing_a_runtime_role_is_a_finding(tmp_path, stub):
    pinned = tmp_path / "pinned"
    assets = {
        WORKER_SCRIPT_ROLE: write_fake_asset(pinned, b"worker", name="flx_worker.py"),
        RUNTIME_LOCK_ROLE: write_fake_asset(pinned, b"lock", name="lock.txt"),
    }
    built = build_world(tmp_path, adapter=stub, research=True, assets=assets)
    report = validate(built)
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_RUNTIME_MISMATCH in codes(report)


def test_a_lower_is_better_run_is_a_finding(tmp_path, stub):
    stub.direction = ScoreDirection.LOWER_IS_BETTER
    stub._descriptor = AlgorithmDescriptor(
        algorithm_id=identity.ALGORITHM_ID,
        display_name="flx",
        adapter_id=identity.ADAPTER_ID,
        adapter_version=str(identity.ADAPTER_VERSION),
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        implementation_version=identity.SOURCE_COMMIT,
        score_direction=ScoreDirection.LOWER_IS_BETTER,
        deterministic=True,
    )
    pinned = tmp_path / "pinned"
    assets = {
        WORKER_SCRIPT_ROLE: write_fake_asset(pinned, b"worker", name="flx_worker.py"),
        RUNTIME_LOCK_ROLE: write_fake_asset(pinned, b"lock", name="lock.txt"),
        RUNTIME_POLICY_ROLE: write_fake_asset(pinned, b"policy", name="policy.yaml"),
    }
    built = build_world(tmp_path, adapter=stub, research=True, assets=assets)
    report = validate(built)
    assert not report.is_clean
    assert IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH in codes(report)
