"""One suite every adapter must pass, forever.

This is the file that keeps the abstraction honest. The contract in
docs/adr/0002 is only worth something if adding SourceAFIS or NBIS means
satisfying the same checks the dummy matcher satisfies, without the runner
learning anything new about either of them.

It is parametrised over :func:`registered_adapters`, so a new adapter joins
this suite by being registered — there is nothing to remember to add here.
"""

from __future__ import annotations

import hashlib
import os
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
from fakes import StrayWriteAdapter, registry_configuration, sha256_of
from synthetic_ridges import whorl_png

ADAPTER_IDS = registered_adapters()

#: Adapters that need external tooling carry their own markers, so the ordinary CI
#: run can exclude them while they still take part in exactly this suite, and an
#: environment variable that turns a skip into a failure where the tooling is
#: supposed to be present. An adapter joins the suite by being registered; it opts
#: into markers by appearing here.
_EXTERNAL_TOOLING = {
    "sourceafis_java_subprocess": (
        (pytest.mark.sourceafis,),
        "FPBENCH_REQUIRE_SOURCEAFIS",
    ),
    "nbis_mindtct_bozorth3_subprocess": (
        (pytest.mark.nbis_upstream, pytest.mark.upstream),
        "FPBENCH_REQUIRE_NBIS",
    ),
    # 4.7 GB of licence-restricted vendor SDK, a 30-day trial bound to one
    # machine and a Java 17 toolchain. CI has none of the three and must never
    # acquire them, so this row is what lets the fourth algorithm take part in
    # exactly this suite while the ordinary run skips it (spec section 37).
    "verifinger_java_subprocess": (
        (pytest.mark.verifinger_artifact,),
        "FPBENCH_REQUIRE_VERIFINGER",
    ),
    # The package is 4,492 bytes, but the runtime it needs is not: a pinned
    # interpreter with a pinned numpy and a pinned OpenCV, in an environment
    # outside the repository, because OpenCV's exact version is part of this
    # algorithm's identity (docs/adr/0125). CI has none of it.
    "fingerprints_matching_subprocess": (
        (pytest.mark.fingerprints_matching_artifact,),
        "FPBENCH_REQUIRE_FINGERPRINTS_MATCHING",
    ),
    # Algorithm 5 needs everything the NBIS route needs *and* a compiled OpenAFIS
    # bridge, which is built from a pinned upstream checkout on the machine that
    # runs it. CI has neither, so this row is what lets the composition take part
    # in exactly this suite while the ordinary run skips it.
    "nbis_mindtct_openafis_subprocess": (
        (pytest.mark.nbis_upstream, pytest.mark.upstream, pytest.mark.openafis_artifact),
        "FPBENCH_REQUIRE_OPENAFIS",
    ),
    # The Stage 19B variant, which needs a *separately built* bridge — the same
    # source against a patched OpenAFIS tree. It takes part in this suite on the
    # machine that has that build, and skips everywhere else.
    "nbis_mindtct_openafis_capacity_extended_subprocess": (
        (pytest.mark.nbis_upstream, pytest.mark.upstream, pytest.mark.openafis_artifact),
        "FPBENCH_REQUIRE_OPENAFIS_19B",
    ),
    # Stage 20B needs everything the NBIS route needs, plus a licence-restricted
    # vendor assembly that may not be redistributed and a .NET Framework host to
    # load it on. CI has neither, so this row is what lets the route take part in
    # exactly this suite while the ordinary run skips it.
    "nbis_mindtct_mcc_sdk_v2_subprocess": (
        (pytest.mark.nbis_upstream, pytest.mark.upstream, pytest.mark.mcc_sdk_v2_artifact),
        "FPBENCH_REQUIRE_MCC_SDK",
    ),
}

ADAPTER_PARAMS = [
    pytest.param(
        adapter_id,
        id=adapter_id,
        marks=list(_EXTERNAL_TOOLING.get(adapter_id, ((),))[0]),
    )
    for adapter_id in ADAPTER_IDS
]


@pytest.fixture(params=ADAPTER_PARAMS)
def adapter(request) -> FingerprintAlgorithmAdapter:
    """A registered adapter whose environment is usable.

    An adapter that reports UNAVAILABLE is skipped rather than failed — a machine
    without a JDK, or without a certified NBIS build, should still be able to run
    the suite — unless the adapter's own ``FPBENCH_REQUIRE_…=1`` is set, which CI
    does so that a broken build turns the run red instead of quietly green.

    Configuration comes from :func:`registry_configuration`, because an adapter
    with no defaults cannot be built from nothing and that is deliberate: a bare
    tool name means whatever a machine's PATH happens to say (docs/adr/0048).
    """
    instance = create_adapter(request.param, registry_configuration(request.param))
    if request.param in _EXTERNAL_TOOLING:
        _markers, require = _EXTERNAL_TOOLING[request.param]
        report = instance.validate_environment()
        if report.status is not EnvironmentStatus.READY:
            reason = f"{request.param} is unavailable: {report.message}"
            if os.environ.get(require) == "1":
                pytest.fail(reason)
            pytest.skip(reason)
    return instance


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    working = tmp_path / "workspace" / "work" / "run_x" / "job_y"
    artifacts = tmp_path / "workspace" / "artifacts" / "run_x" / "job_y"
    working.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    return working, artifacts


#: Stable seeds so the two sides are different images rather than the same one.
_SEEDS = {"left": 1, "right": 6}


def prepared(name: str, tmp_path: Path) -> PreparedImage:
    """A prepared image over a real, decodable PNG.

    A placeholder byte string would be enough for an adapter that ignores its input,
    but it would reduce every image-reading adapter to its decode-failure path — so
    the whole suite would pass while never once exercising a successful comparison.
    The synthetic ridges are not fingerprints; see tests/fixtures/sourceafis/README.md.
    """
    path = tmp_path / "dataset" / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = whorl_png(500, _SEEDS.get(name, 1))
    path.write_bytes(payload)
    return PreparedImage(
        image_id=f"sd300a_00001000_plain_{name}",
        local_path=path.resolve(),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
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
