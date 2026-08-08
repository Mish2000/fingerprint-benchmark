"""Stage 9A against artifacts that are actually on this machine.

Not part of the public CI, which fetches nothing and has no runtime. These skip
unless the local third-party store holds the artifact under test — and, for the
checkpoint inspections, unless a torch is installed that can open it
(spec section 54).

Everything here is still structural. Nothing measures recognition accuracy,
nothing reads a fingerprint, and the images these use are generated into a
temporary directory at test time rather than committed (spec sections 38 to 40).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.experiments import stage9a_flare_artifacts as artifacts
from fpbench.experiments import stage9a_flare_identity as frozen
from fpbench.experiments import stage9a_flare_qualification as qualification
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.flare_artifact


def _artifact(artifact_id: str) -> frozen.RequiredArtifact:
    return next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if item.artifact_id == artifact_id
    )


def _require_present(artifact: frozen.RequiredArtifact):
    if not artifact.identity_established:
        pytest.skip(
            f"{artifact.artifact_id} has no established identity; enroll it from "
            "its official locator first"
        )
    verification = artifacts.verify_artifact(
        artifact, repository_root=REPOSITORY_ROOT
    )
    if not verification.present:
        pytest.skip(
            f"{artifact.artifact_id} is not in this machine's third-party store"
        )
    return verification


def _require_torch() -> None:
    if not qualification.torch_is_available():
        pytest.skip("torch is not installed here; the runtime question is Stage 9B's")


@pytest.mark.parametrize(
    "artifact_id",
    [item.artifact_id for item in frozen.REQUIRED_ARTIFACTS],
)
def test_a_present_artifact_verifies_against_its_frozen_identity(
    artifact_id: str,
) -> None:
    artifact = _artifact(artifact_id)
    verification = _require_present(artifact)
    assert verification.size_matches, (
        f"{artifact_id}: {verification.observed_size_bytes} bytes on disk and "
        f"{artifact.expected_size_bytes} expected"
    )
    assert verification.digest_matches, f"{artifact_id}: the bytes are not the bytes"
    assert verification.verified


@pytest.mark.parametrize(
    "artifact_id",
    [item.artifact_id for item in frozen.REQUIRED_ARTIFACTS],
)
def test_a_present_artifact_is_structurally_what_the_locator_yields(
    artifact_id: str,
) -> None:
    artifact = _artifact(artifact_id)
    _require_present(artifact)
    store = artifacts.resolve_third_party_root(repository_root=REPOSITORY_ROOT)
    path = artifacts.resolve_store_path(artifact, root=store)
    report = artifacts.check_plausibility(artifact, path)
    assert report.plausible, report.findings
    assert report.detected_form != "html_document"


@pytest.mark.parametrize(
    "artifact_id", list(qualification.REQUIRED_CHECKPOINT_ARTIFACTS)
)
def test_a_present_checkpoint_has_the_structure_its_binding_declares(
    artifact_id: str,
) -> None:
    _require_torch()
    artifact = _artifact(artifact_id)
    _require_present(artifact)
    inspection = qualification.inspect_checkpoint(
        artifact_id, repository_root=REPOSITORY_ROOT
    )
    assert inspection.performed, inspection.reason
    assert inspection.findings == (), inspection.findings
    assert inspection.parameter_key_count > 0
    binding = qualification.binding_for(artifact_id)
    if binding.state_dict_path == 'checkpoint["state_dict"]':
        assert inspection.state_dict_path_taken == 'checkpoint["state_dict"]'
    else:
        assert inspection.state_dict_path_taken in (
            'checkpoint["model"]',
            "the checkpoint itself",
        )


def test_the_prior_artifact_routes_into_the_five_declared_sub_modules() -> None:
    """Every key it carries belongs to one of the five prefixes, or is dropped."""
    _require_torch()
    artifact = _artifact("flare_prior_codebook_checkpoint")
    _require_present(artifact)
    inspection = qualification.inspect_checkpoint(
        "flare_prior_codebook_checkpoint", repository_root=REPOSITORY_ROOT
    )
    assert inspection.performed, inspection.reason
    routed = {"encoder", "decoder", "quantize", "quant_conv", "post_quant_conv"}
    unrouted = {
        prefix: count
        for prefix, count in inspection.key_prefix_histogram.items()
        if prefix not in routed
    }
    assert not unrouted, (
        "save_dict_to_prior drops any key matching none of the five prefixes, "
        f"and these would be dropped: {sorted(unrouted)}"
    )


def test_the_compatibility_report_is_established_when_everything_is_here() -> None:
    _require_torch()
    for artifact_id in qualification.REQUIRED_CHECKPOINT_ARTIFACTS:
        _require_present(_artifact(artifact_id))
    report = qualification.build_compatibility_report(
        repository_root=REPOSITORY_ROOT
    )
    for entry in report.entries:
        assert entry.inspection_performed, entry.reason
        assert entry.unexplained_missing_parameters == 0
        assert entry.unexplained_shape_mismatches == 0
        assert entry.unexplained_skipped_inference_affecting_keys == 0


def test_the_synthetic_smoke_images_are_generated_outside_the_repository(
    tmp_path: Path,
) -> None:
    written = qualification.write_synthetic_images(tmp_path / "flare_smoke")
    assert len(written) == len(qualification.SYNTHETIC_IMAGE_NAMES)
    for path in written:
        assert REPOSITORY_ROOT not in path.resolve().parents
        assert path.stat().st_size > 0


def test_the_store_is_outside_the_working_tree() -> None:
    store = artifacts.resolve_third_party_root(repository_root=REPOSITORY_ROOT)
    resolved = store.expanduser().resolve()
    assert REPOSITORY_ROOT.resolve() != resolved
    assert REPOSITORY_ROOT.resolve() not in resolved.parents
