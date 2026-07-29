"""One suite every adapter must pass, forever.

This is the file that keeps the abstraction honest. The contract in
docs/adr/0002 is only worth something if adding SourceAFIS or NBIS means
satisfying the same checks the dummy matcher satisfies, without the runner
learning anything new about either of them.

It is parametrised over :func:`registered_adapters`, so a new adapter joins
this suite by being registered — there is nothing to remember to add here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.registry import create_adapter, registered_adapters
from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    ExecutionStatus,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    ComparisonContext,
    PreparedImage,
    RawMatchResult,
    descriptor_fingerprint,
)
from fpbench.core.identifiers import validate_id
from fakes import StrayWriteAdapter, sha256_of

ADAPTER_IDS = registered_adapters()


@pytest.fixture(params=ADAPTER_IDS)
def adapter(request) -> FingerprintAlgorithmAdapter:
    return create_adapter(request.param)


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    working = tmp_path / "workspace" / "work" / "run_x" / "job_y"
    artifacts = tmp_path / "workspace" / "artifacts" / "run_x" / "job_y"
    working.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    return working, artifacts


def prepared(name: str, tmp_path: Path) -> PreparedImage:
    path = tmp_path / "dataset" / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    return PreparedImage(
        image_id=f"sd300a_00001000_plain_{name}",
        local_path=path.resolve(),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=sha256_of(name),
        checksum_status=ChecksumStatus.NOT_VERIFIED,
        preparation_profile_id="identity_png_v1",
        preparation_hash=sha256_of(f"prep-{name}"),
    )


def make_context(working: Path, artifacts: Path, seed: int = 0) -> ComparisonContext:
    return ComparisonContext(
        run_id="run_abc123def456",
        job_id="job_0123456789abcdef",
        attempt=1,
        working_directory=working,
        artifact_directory=artifacts,
        timeout_seconds=10.0,
        deterministic_seed=seed,
    )


def files_under(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()}


def test_at_least_one_adapter_is_registered():
    assert ADAPTER_IDS, "the contract suite would silently pass with no adapters"


# ----------------------------------------------------------------- descriptor


def test_descriptor_identifiers_are_usable_as_paths_and_keys(adapter):
    descriptor = adapter.descriptor
    validate_id(descriptor.algorithm_id)
    validate_id(descriptor.adapter_id)


def test_descriptor_declares_versions(adapter):
    descriptor = adapter.descriptor
    assert descriptor.adapter_version
    assert descriptor.implementation_version
    assert descriptor.display_name


def test_descriptor_implements_a_supported_contract_version(adapter):
    assert adapter.descriptor.adapter_contract_version == ADAPTER_CONTRACT_VERSION


def test_descriptor_is_stable_within_an_instance(adapter):
    assert adapter.descriptor == adapter.descriptor
    assert descriptor_fingerprint(adapter.descriptor) == descriptor_fingerprint(
        adapter.descriptor
    )


def test_descriptor_declares_a_score_direction(adapter):
    assert isinstance(adapter.descriptor.score_direction, ScoreDirection)


# ---------------------------------------------------------------- environment


def test_environment_report_is_well_formed(adapter):
    report = adapter.validate_environment()
    assert isinstance(report.status, EnvironmentStatus)
    assert report.implementation_version


def test_a_ready_environment_names_its_implementation_version(adapter):
    report = adapter.validate_environment()
    if report.status is EnvironmentStatus.READY:
        assert report.implementation_version == adapter.descriptor.implementation_version


def test_validating_the_environment_has_no_side_effects(adapter):
    first = adapter.validate_environment()
    assert adapter.validate_environment() == first


# -------------------------------------------------------------------- compare


def test_compare_returns_a_raw_match_result(adapter, tmp_path, workspace):
    result = adapter.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(*workspace)
    )
    assert isinstance(result, RawMatchResult)


def test_the_result_honours_the_declared_score_direction(adapter, tmp_path, workspace):
    result = adapter.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(*workspace)
    )
    assert result.score_direction is adapter.descriptor.score_direction


def test_a_success_carries_a_finite_score_and_no_failure(adapter, tmp_path, workspace):
    result = adapter.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(*workspace)
    )
    if result.status is ExecutionStatus.SUCCESS:
        assert result.raw_score is not None
        assert result.raw_score == result.raw_score  # not NaN
        assert result.failure is None
    else:
        assert result.raw_score is None
        assert result.failure is not None


def test_a_result_never_carries_both_a_score_and_a_failure(
    adapter, tmp_path, workspace
):
    result = adapter.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(*workspace)
    )
    assert (result.raw_score is None) != (result.failure is None)


def test_a_deterministic_adapter_repeats_itself(adapter, tmp_path, workspace):
    if not adapter.descriptor.deterministic:
        pytest.skip("adapter does not claim determinism")
    left, right = prepared("left", tmp_path), prepared("right", tmp_path)
    first = adapter.compare(left, right, make_context(*workspace))
    second = adapter.compare(left, right, make_context(*workspace))
    assert first.status is second.status
    assert first.raw_score == second.raw_score


def test_compare_does_not_modify_its_inputs(adapter, tmp_path, workspace):
    left, right = prepared("left", tmp_path), prepared("right", tmp_path)
    before = (left, right)
    adapter.compare(left, right, make_context(*workspace))
    assert (left, right) == before


def test_result_metadata_and_artifacts_are_frozen(adapter, tmp_path, workspace):
    result = adapter.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(*workspace)
    )
    assert isinstance(result.artifacts, tuple)
    with pytest.raises(TypeError):
        result.metadata["injected"] = "value"


def test_artifact_references_stay_inside_the_workspace(adapter, tmp_path, workspace):
    result = adapter.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(*workspace)
    )
    for reference in result.artifacts:
        assert not Path(reference.relative_path).is_absolute()
        assert ".." not in Path(reference.relative_path).parts


# ------------------------------------------------------------------ isolation


def test_compare_writes_nothing_outside_its_context_directories(
    adapter, tmp_path, workspace
):
    working, artifacts = workspace
    left, right = prepared("left", tmp_path), prepared("right", tmp_path)
    before = files_under(tmp_path)
    adapter.compare(left, right, make_context(working, artifacts))
    created = files_under(tmp_path) - before
    for path in created:
        assert path.is_relative_to(working) or path.is_relative_to(artifacts), (
            f"{adapter.descriptor.adapter_id} wrote outside its context: {path}"
        )


def test_the_containment_check_can_actually_fail(tmp_path, workspace):
    """A check that never fires proves nothing, so fire it deliberately."""
    working, artifacts = workspace
    stray = tmp_path / "elsewhere" / "leak.txt"
    rogue = StrayWriteAdapter(stray)
    before = files_under(tmp_path)
    rogue.compare(
        prepared("left", tmp_path), prepared("right", tmp_path), make_context(working, artifacts)
    )
    created = files_under(tmp_path) - before
    assert stray in created
    assert not stray.is_relative_to(working)
    assert not stray.is_relative_to(artifacts)


def test_compare_asks_for_nothing_but_two_images_and_a_context(adapter):
    """An adapter that cannot see the protocol cannot be biased by it."""
    import inspect

    parameters = list(
        inspect.signature(type(adapter).compare).parameters
    )
    assert parameters == ["self", "left", "right", "context"]


def test_the_context_type_exposes_no_protocol_information():
    forbidden = {"pair_id", "protocol_stage", "ground_truth", "threshold", "subject_id"}
    assert forbidden.isdisjoint(ComparisonContext.__dataclass_fields__)


# ------------------------------------------------------------------- registry


def test_every_registered_adapter_can_be_created(adapter):
    assert isinstance(adapter, FingerprintAlgorithmAdapter)


def test_the_registry_id_matches_the_descriptor(adapter):
    assert adapter.descriptor.adapter_id in ADAPTER_IDS
