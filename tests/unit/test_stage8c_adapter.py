"""The flx adapter's contract, proved without torch and without a checkpoint.

Everything here runs against ``FakeFlxIntegration``, which presents exactly the
surface the real route presents and records what it returned. That is enough to
prove the claims that matter: two independent sides on every comparison, no
cache of any kind, a Decimal stored beside its double, a runtime that moved
being drift rather than a comparison outcome, and nothing derived from an image
surviving the call.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.experiments.flx_adapter import RAW_SCORE_DECIMAL_METADATA_KEY, FlxAdapter
from fpbench.experiments.flx_adapter import FlxConfig
from fpbench.core.enums import (
    EnvironmentStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.errors import RuntimeDriftError
from fpbench.core.execution_models import descriptor_fingerprint, environment_fingerprint
from fpbench.core.flx_errors import (
    FlxArtifactError,
    FlxCheckpointError,
    FlxOfflineViolation,
    FlxPreprocessingError,
    FlxRepresentationError,
    FlxRuntimeError,
    FlxScoreError,
    FlxWorkerError,
    FlxWorkerTimeout,
)
from fpbench.flx import identity
from fpbench.flx.score import canonical_decimal_text
from stage8cworld import (
    READY_RUNTIME_REPORT,
    FakeFlxIntegration,
    make_context,
    make_prepared_image,
    write_fixture_png,
)

pytestmark = pytest.mark.stage8c_contract


@pytest.fixture
def config(tmp_path: Path) -> FlxConfig:
    for name in ("worker.py", "lock.txt", "policy.yaml"):
        (tmp_path / name).write_text("pinned\n", encoding="utf-8")
    return FlxConfig(
        bundle_root=(tmp_path / "bundle").resolve(),
        worker_script=(tmp_path / "worker.py").resolve(),
        runtime_lock=(tmp_path / "lock.txt").resolve(),
        runtime_policy=(tmp_path / "policy.yaml").resolve(),
        research_mode=True,
    )


def _adapter(monkeypatch, config: FlxConfig, **integration_kwargs) -> tuple[FlxAdapter, list]:
    """An adapter whose worker is a fake, and the fakes it created."""
    created: list[FakeFlxIntegration] = []

    def build(bundle, *, lock_path=None, policy_path=None):
        fake = FakeFlxIntegration(
            bundle, lock_path=lock_path, policy_path=policy_path, **integration_kwargs
        )
        created.append(fake)
        return fake

    monkeypatch.setattr(
        "fpbench.experiments.flx_adapter.FlxLearnedFingerprintIntegration", build
    )
    return FlxAdapter(config), created


# --------------------------------------------------------------- the contract


def test_the_adapter_implements_the_contract(config: FlxConfig) -> None:
    assert isinstance(FlxAdapter(config), FingerprintAlgorithmAdapter)


def test_the_descriptor_is_stable_and_names_the_qualified_route(
    config: FlxConfig,
) -> None:
    adapter = FlxAdapter(config)
    first, second = adapter.descriptor, adapter.descriptor
    assert first == second
    assert descriptor_fingerprint(first) == descriptor_fingerprint(second)
    assert first.algorithm_id == identity.ALGORITHM_ID
    assert first.adapter_id == identity.ADAPTER_ID
    assert first.adapter_version == "1"
    assert first.adapter_contract_version == "1"
    assert first.implementation_version == identity.SOURCE_COMMIT
    assert first.deterministic is True


def test_the_score_direction_maps_higher_is_more_similar_onto_the_taxonomy(
    config: FlxConfig,
) -> None:
    assert identity.SCORE_DIRECTION == "higher_is_more_similar"
    assert FlxAdapter(config).descriptor.score_direction is ScoreDirection.HIGHER_IS_BETTER


def test_the_descriptor_fingerprint_covers_the_stage_8b_profiles(
    config: FlxConfig,
) -> None:
    # docs/adr/0077: a run is attributed to the transform, the representation
    # and the comparator it actually used.
    metadata = dict(FlxAdapter(config).descriptor.metadata)
    from fpbench.flx.preprocessing import build_preprocessing_profile
    from fpbench.flx.representation import build_representation_profile
    from fpbench.flx.score import build_score_profile

    assert metadata["preprocessing_profile_fingerprint"] == (
        build_preprocessing_profile().fingerprint
    )
    assert metadata["representation_profile_fingerprint"] == (
        build_representation_profile().fingerprint
    )
    assert metadata["score_profile_fingerprint"] == build_score_profile().fingerprint
    assert metadata["checkpoint_sha256"] == identity.CHECKPOINT_SHA256
    assert metadata["inference_batch_rule"] == identity.INFERENCE_BATCH_RULE


def test_the_pinned_roles_never_include_the_weights(config: FlxConfig) -> None:
    assert sorted(config.runtime_assets()) == [
        "flx_runtime_lock",
        "flx_runtime_policy",
        "flx_worker_script",
    ]


# ------------------------------------------------------------- environment


def test_a_healthy_runtime_is_ready_and_fingerprints_the_same_twice(
    monkeypatch, config: FlxConfig
) -> None:
    adapter, created = _adapter(monkeypatch, config)
    first = adapter.validate_environment()
    second = adapter.validate_environment()
    assert first.status is EnvironmentStatus.READY
    assert environment_fingerprint(first) == environment_fingerprint(second)
    # Preflight must not leave a second 1.2 GB worker behind.
    assert all(fake.closed == 1 for fake in created)


def test_the_environment_records_the_runtime_and_the_artifacts(
    monkeypatch, config: FlxConfig
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    report = adapter.validate_environment()
    assert report.runtime["flx.runtime_profile_id"] == identity.RUNTIME_PROFILE_ID
    assert report.runtime["flx.device"] == "cpu"
    assert report.runtime["flx.torch_num_threads"] == "1"
    assert report.runtime["flx.research_mode"] == "true"
    assert report.dependencies["flx.checkpoint_sha256"] == identity.CHECKPOINT_SHA256
    assert report.dependencies["flx.torch_version"] == "2.13.0+cpu"


@pytest.mark.parametrize(
    "broken",
    [
        {"checkpoint_loaded": False},
        {"model_in_eval_mode": False},
        {"gradients_disabled": False},
        {"missing_state_dict_keys": ("stem.weight",)},
        {"unexpected_state_dict_keys": ("loss.centre",)},
    ],
)
def test_a_checkpoint_that_did_not_load_is_unavailable_not_ready(
    monkeypatch, config: FlxConfig, broken: dict
) -> None:
    report = dict(READY_RUNTIME_REPORT)
    report.update(broken)
    adapter, _ = _adapter(monkeypatch, config, runtime_report=report)
    assert adapter.validate_environment().status is EnvironmentStatus.UNAVAILABLE


def test_a_missing_runtime_is_unavailable_and_does_not_raise(
    monkeypatch, config: FlxConfig
) -> None:
    adapter, _ = _adapter(
        monkeypatch, config, load_error=FlxRuntimeError("no bundle here")
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "no bundle here" in (report.message or "")


# ------------------------------------------------------------ the comparison


def test_a_comparison_performs_two_preprocesses_two_extractions_and_one_compare(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, created = _adapter(monkeypatch, config)
    left = make_prepared_image(write_fixture_png(tmp_path, "left"), image_id="img_left")
    right = make_prepared_image(
        write_fixture_png(tmp_path, "right"), image_id="img_right"
    )
    result = adapter.compare(left, right, make_context(tmp_path))
    fake = created[0]

    assert result.status is ExecutionStatus.SUCCESS
    assert fake.preprocess_calls == 2
    assert fake.extract_calls == 2
    assert fake.compare_calls == 1
    assert result.metadata["flx.preprocess_calls"] == "2"
    assert result.metadata["flx.logical_extraction_calls"] == "2"
    assert result.metadata["flx.comparison_calls"] == "1"


def test_a_self_comparison_performs_two_extractions_too(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    # spec section 9: both sides point at one PNG and it is still read twice,
    # preprocessed twice and extracted twice.
    adapter, created = _adapter(monkeypatch, config)
    path = write_fixture_png(tmp_path, "same")
    left = make_prepared_image(path, image_id="img_self")
    right = make_prepared_image(path, image_id="img_self")
    result = adapter.compare(left, right, make_context(tmp_path))
    fake = created[0]

    assert result.status is ExecutionStatus.SUCCESS
    assert fake.preprocess_calls == 2
    assert fake.extract_calls == 2
    assert result.metadata["flx.logical_extraction_calls"] == "2"


def test_the_two_sides_of_a_self_comparison_are_never_the_same_object(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, created = _adapter(monkeypatch, config)
    path = write_fixture_png(tmp_path, "same")
    prepared = make_prepared_image(path, image_id="img_self")
    adapter.compare(prepared, prepared, make_context(tmp_path))
    fake = created[0]

    first, second = fake.representations
    # Bitwise equal contents are allowed and expected; the same object is not.
    assert first.digest == second.digest
    assert first is not second
    assert first.serial != second.serial
    assert fake.compared == [(1, 2)]


def test_no_representation_is_reused_between_comparisons(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, created = _adapter(monkeypatch, config)
    path = write_fixture_png(tmp_path, "same")
    prepared = make_prepared_image(path, image_id="img_self")
    for index in range(3):
        adapter.compare(
            prepared, prepared, make_context(tmp_path, job_id=f"job_00000000000000{index}1")
        )
    fake = created[0]

    # Three comparisons of one image: six preprocesses, six extractions, no
    # cache by image id, by digest or by pair.
    assert fake.preprocess_calls == 6
    assert fake.extract_calls == 6
    assert len({representation.serial for representation in fake.representations}) == 6
    assert fake.compared == [(1, 2), (3, 4), (5, 6)]


def test_one_worker_serves_a_whole_execution_session(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    # spec section 10: the runtime, the modules and the weights may stay; only
    # what is derived from an image may not.
    adapter, created = _adapter(monkeypatch, config)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "one"))
    for index in range(3):
        adapter.compare(
            prepared, prepared, make_context(tmp_path, job_id=f"job_00000000000000{index}2")
        )
    assert len(created) == 1
    assert created[0].loaded is True


def test_the_score_is_stored_as_a_double_beside_its_canonical_decimal(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    path = write_fixture_png(tmp_path, "self")
    prepared = make_prepared_image(path)
    result = adapter.compare(prepared, prepared, make_context(tmp_path))

    text = result.metadata[RAW_SCORE_DECIMAL_METADATA_KEY]
    assert text == canonical_decimal_text(float(result.raw_score))
    # Seventeen significant digits recovers the double exactly, so the two
    # representations are the same number (docs/adr/0077).
    assert float(Decimal(text)) == result.raw_score


def test_a_self_score_slightly_above_two_is_a_success(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "self"))
    result = adapter.compare(prepared, prepared, make_context(tmp_path))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score > 2.0
    assert Decimal(result.metadata[RAW_SCORE_DECIMAL_METADATA_KEY]) == Decimal(
        "2.0000001192092896"
    )


@pytest.mark.parametrize("score", [Decimal("0"), Decimal("-1.5"), Decimal("-2")])
def test_zero_and_negative_scores_are_successes(
    monkeypatch, config: FlxConfig, tmp_path: Path, score: Decimal
) -> None:
    # docs/adr/0076: a score of 0 is a successful comparison, not a NON_MATCH.
    adapter, _ = _adapter(monkeypatch, config, score=lambda left, right: score)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "zero"))
    result = adapter.compare(prepared, prepared, make_context(tmp_path))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.failure is None
    assert float(result.raw_score) == float(score)


def test_every_result_records_the_operation_metadata(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "meta"))
    metadata = adapter.compare(prepared, prepared, make_context(tmp_path)).metadata
    assert metadata["flx.algorithm_id"] == identity.ALGORITHM_ID
    assert metadata["flx.score_profile_id"] == identity.SCORE_PROFILE_ID
    assert metadata["flx.inference_batch_rows"] == "2"
    assert metadata["flx.physical_forward_rows"] == "4"
    assert metadata["flx.side_independence"] == (
        "separate_preprocess_and_extract_per_side"
    )


def test_a_result_carries_a_timing_for_every_operation(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "timing"))
    timings = adapter.compare(prepared, prepared, make_context(tmp_path)).timing_components_ms
    assert sorted(timings) == [
        "compare_ms",
        "left_extract_ms",
        "left_preprocess_ms",
        "right_extract_ms",
        "right_preprocess_ms",
    ]


def test_no_result_carries_a_representation_or_a_tensor(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "clean"))
    metadata = adapter.compare(prepared, prepared, make_context(tmp_path)).metadata
    forbidden = {
        "embedding",
        "representation",
        "texture",
        "minutia_vector",
        "tensor",
        "model_input",
        "threshold",
        "decision",
    }
    for key in metadata:
        assert key.rsplit(".", 1)[-1] not in forbidden
    assert not any(artifact for artifact in adapter.compare(
        prepared, prepared, make_context(tmp_path, job_id="job_000000000000000b")
    ).artifacts)


# ------------------------------------------------------- recorded failures


@pytest.mark.parametrize(
    "operation, error, code, stage",
    [
        (
            "preprocess",
            FlxPreprocessingError("not a canonical gray8 PNG"),
            FailureCode.PREPARATION_FAILED,
            FailureStage.PREPARATION,
        ),
        (
            "extract",
            FlxRepresentationError("branch rows are not bitwise equal"),
            FailureCode.TEMPLATE_EXTRACTION_FAILED,
            FailureStage.EXTRACTION,
        ),
        (
            "compare",
            FlxScoreError("raw score is not the sum of its branches"),
            FailureCode.MATCHING_FAILED,
            FailureStage.MATCHING,
        ),
        (
            "extract",
            FlxWorkerTimeout("no response within 120s"),
            FailureCode.TIMEOUT,
            FailureStage.TIMEOUT,
        ),
        (
            "compare",
            FlxWorkerError("the worker exited without responding"),
            FailureCode.PROCESS_CRASHED,
            FailureStage.MATCHING,
        ),
    ],
)
def test_an_algorithmic_failure_is_recorded_with_no_score(
    monkeypatch,
    config: FlxConfig,
    tmp_path: Path,
    operation: str,
    error: Exception,
    code: FailureCode,
    stage: FailureStage,
) -> None:
    adapter, _ = _adapter(monkeypatch, config, fail_on={operation: error})
    prepared = make_prepared_image(write_fixture_png(tmp_path, "fail"))
    result = adapter.compare(prepared, prepared, make_context(tmp_path))

    assert result.status is ExecutionStatus.FAILURE
    assert result.raw_score is None
    assert result.failure is not None
    assert result.failure.code is code
    assert result.failure.stage is stage
    assert RAW_SCORE_DECIMAL_METADATA_KEY not in result.metadata
    assert result.metadata["flx.failed_at"]


def test_an_unreadable_prepared_file_is_a_recorded_decode_failure(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    path = write_fixture_png(tmp_path, "gone")
    prepared = make_prepared_image(path)
    path.unlink()
    result = adapter.compare(prepared, prepared, make_context(tmp_path))
    assert result.status is ExecutionStatus.FAILURE
    assert result.failure.code is FailureCode.IMAGE_DECODE_FAILED


# --------------------------------------------------------- blocking failures


@pytest.mark.parametrize(
    "error",
    [
        FlxArtifactError("checkpoint SHA-256 changed"),
        FlxCheckpointError("state dict does not fit the variant"),
        FlxRuntimeError("torch version is not the locked one"),
        FlxOfflineViolation("the worker attempted a connection"),
    ],
)
def test_a_runtime_that_moved_is_drift_and_is_never_stored(
    monkeypatch, config: FlxConfig, tmp_path: Path, error: Exception
) -> None:
    # docs/adr/0018: recording this as a comparison failure would imply the run
    # is otherwise sound.
    adapter, _ = _adapter(monkeypatch, config, fail_on={"extract": error})
    prepared = make_prepared_image(write_fixture_png(tmp_path, "drift"))
    with pytest.raises(RuntimeDriftError):
        adapter.compare(prepared, prepared, make_context(tmp_path))


def test_a_prepared_file_whose_bytes_changed_is_drift(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    path = write_fixture_png(tmp_path, "mutated")
    prepared = make_prepared_image(path)
    path.write_bytes(path.read_bytes() + b"\x00")
    with pytest.raises(RuntimeDriftError):
        adapter.compare(prepared, prepared, make_context(tmp_path))


def test_a_cache_that_returned_one_object_for_both_sides_is_drift(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    """The check that would catch a cache introduced inside the route itself."""
    from stage8cworld import FakeRepresentation

    shared = FakeRepresentation(digest="shared", serial=1)

    class CachingIntegration(FakeFlxIntegration):
        def extract(self, model_input):
            self.extract_calls += 1
            return shared

    def build(bundle, *, lock_path=None, policy_path=None):
        return CachingIntegration(bundle, lock_path=lock_path, policy_path=policy_path)

    monkeypatch.setattr(
        "fpbench.experiments.flx_adapter.FlxLearnedFingerprintIntegration", build
    )
    adapter = FlxAdapter(config)
    prepared = make_prepared_image(write_fixture_png(tmp_path, "cached"))
    with pytest.raises(RuntimeDriftError, match="cache"):
        adapter.compare(prepared, prepared, make_context(tmp_path))


def test_a_worker_that_will_not_shut_down_is_a_blocking_failure(
    monkeypatch, config: FlxConfig, tmp_path: Path
) -> None:
    # spec section 16.2: cleanup failure stops the stage.
    adapter, _ = _adapter(monkeypatch, config, close_error=OSError("pipe is stuck"))
    prepared = make_prepared_image(write_fixture_png(tmp_path, "stuck"))
    adapter.compare(prepared, prepared, make_context(tmp_path))
    with pytest.raises(RuntimeDriftError, match="shut down cleanly"):
        adapter.close()


def test_closing_twice_is_harmless(monkeypatch, config: FlxConfig) -> None:
    adapter, _ = _adapter(monkeypatch, config)
    adapter.validate_environment()
    adapter.close()
    adapter.close()
