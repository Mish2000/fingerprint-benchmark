"""The committed Stage 8D evidence, verified with nothing the stage needed.

No dataset, no runtime, no checkpoint, no workspace and no prior result set —
which for this stage is not much of a claim, because it never needed any of them.
What is under test is the publication: that it holds exactly the expected files,
that the marker fingerprints to what it carries, that the registry and the
qualification re-derive from source, that the marker's denials are all true, and
that the exact bytes have not moved since finalization.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously. The one test that never
skips is the one that keeps that honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.calibration_errors import Stage8DFinalizationError
from fpbench.experiments import stage8d_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage8d_calibration_infrastructure import (
    RegistryCoverage,
    build_registry,
    require_stage8c_is_the_stage_this_follows,
    run_synthetic_qualification,
)
from fpbench.experiments.stage8d_finalization import (
    Stage8DFinalization,
    calibration_model_fingerprint,
    file_sha256,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    selection_engine_fingerprint,
    stage_8d_finalization_fingerprint,
)

pytestmark = pytest.mark.stage8d

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _published() -> bool:
    return (EVIDENCE / frozen.STAGE_8D_FINALIZATION_NAME).is_file()


requires_publication = pytest.mark.skipif(
    not _published(),
    reason="Stage 8D evidence has not been published yet",
)


def read_marker() -> Stage8DFinalization:
    document = json.loads(
        (EVIDENCE / frozen.STAGE_8D_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    return Stage8DFinalization(**document)


# ------------------------------------------------------------ never skipped


def test_the_skip_condition_is_the_only_reason_anything_here_skips() -> None:
    """Keeps the gate honest.

    A suite that skipped for any other reason — a missing dependency, an import
    error, a marker typo — would look identical to a suite waiting for the
    publication. This test always executes, so ``pytest -m stage8d`` always has
    something to run and the skip below always means exactly one thing.
    """
    marker_present = (EVIDENCE / frozen.STAGE_8D_FINALIZATION_NAME).is_file()
    assert marker_present == _published()
    if not EVIDENCE.is_dir():
        assert not marker_present
    assert frozen.STAGE_8D_FINALIZATION_NAME == "stage-8d-finalization.json"
    assert frozen.STAGE_8D_OUTCOME == "CALIBRATION_INFRASTRUCTURE_READY"
    assert len(frozen.REQUIRED_EVIDENCE_FILES) == 5


def test_the_stage_this_follows_is_the_one_it_was_frozen_against() -> None:
    """Needs no Stage 8D evidence at all: it reads Stage 8C's, and only reads."""
    require_stage8c_is_the_stage_this_follows(REPOSITORY_ROOT)


def test_the_frozen_identities_are_all_present_in_the_published_evidence() -> None:
    registry = build_registry(REPOSITORY_ROOT)
    RegistryCoverage.of(registry).require_every_executed_algorithm_is_registered(3)


# ------------------------------------------------------ the published chain


@requires_publication
def test_the_publication_holds_exactly_the_expected_files() -> None:
    names = published_evidence_names(REPOSITORY_ROOT)
    require_expected_evidence_files(names)
    assert len(names) == len(frozen.REQUIRED_EVIDENCE_FILES)


@requires_publication
def test_the_marker_fingerprints_to_what_it_carries() -> None:
    marker = read_marker()
    assert marker.stage_8d_finalization_fingerprint == (
        stage_8d_finalization_fingerprint(marker)
    )
    assert marker.outcome == frozen.STAGE_8D_OUTCOME


@requires_publication
def test_the_marker_denies_everything_stage_8d_did_not_do() -> None:
    """docs/adr/0078: the denials are fields, not prose."""
    marker = read_marker()
    assert marker.real_calibration_performed is False
    assert marker.real_development_dataset_selected is False
    assert marker.production_threshold_count == 0
    assert marker.production_decision_profile_count == 0
    assert marker.evaluation_score_rows_read is False
    assert marker.sd300_score_statistics_read is False
    assert marker.historical_decision_profiles_changed is False
    assert marker.stage8c_evidence_changed is False
    assert marker.opens_algorithm_expansion is True


@requires_publication
def test_the_marker_binds_the_stage_it_follows() -> None:
    marker = read_marker()
    assert marker.stage8c_finalization_fingerprint == (
        frozen.STAGE8C_FINALIZATION_FINGERPRINT
    )
    assert marker.stage8c_outcome == frozen.STAGE8C_OUTCOME


@requires_publication
def test_the_registry_and_the_qualification_re_derive_from_source() -> None:
    """The marker is not evidence of itself: both are recomputed and compared."""
    marker = read_marker()
    registry = build_registry(REPOSITORY_ROOT)
    assert marker.protected_evaluation_registry_fingerprint == (
        registry.registry_fingerprint
    )
    assert marker.protected_identity_count == len(registry.entries)

    qualification = run_synthetic_qualification(registry)
    assert marker.synthetic_qualification_fingerprint == (
        qualification.qualification_fingerprint
    )
    assert marker.synthetic_case_count == len(qualification.cases)
    assert marker.synthetic_selection_cases == qualification.selection_cases
    assert marker.synthetic_refusal_cases == qualification.refusal_cases
    assert marker.synthetic_identity_cases == qualification.identity_cases


@requires_publication
def test_the_marker_pins_the_engine_source_it_was_produced_by() -> None:
    marker = read_marker()
    assert marker.calibration_model_fingerprint == (
        calibration_model_fingerprint(REPOSITORY_ROOT)
    )
    assert marker.selection_engine_fingerprint == (
        selection_engine_fingerprint(REPOSITORY_ROOT)
    )


@requires_publication
def test_the_contract_report_re_derives_from_source_too() -> None:
    """Every digest in it, not only the two the marker happens to pin.

    The module digests were published from a raw byte hash, which names the
    *checkout* rather than the code: ``core.autocrlf`` is on for this repository,
    so the same committed blob is LF in one working tree and CRLF in another.
    Nothing compared them, so nothing noticed. This is that comparison.
    """
    from fpbench.experiments.stage8d_finalization import source_file_sha256

    report = json.loads(
        (EVIDENCE / frozen.CONTRACT_REPORT_NAME).read_text(encoding="utf-8")
    )
    assert report["calibration_model_fingerprint"] == (
        calibration_model_fingerprint(REPOSITORY_ROOT)
    )
    assert report["selection_engine_fingerprint"] == (
        selection_engine_fingerprint(REPOSITORY_ROOT)
    )

    package = REPOSITORY_ROOT / "src" / "fpbench" / "calibration"
    published = report["calibration_package"]["module_sha256"]
    assert set(published) == set(frozen.CALIBRATION_PACKAGE_MODULES)
    for name, digest in published.items():
        assert digest == source_file_sha256(package / name), name


@requires_publication
def test_the_published_bytes_have_not_moved_since_finalization() -> None:
    marker = read_marker()
    for name, digest in marker.evidence_content_hashes.items():
        assert file_sha256(EVIDENCE / name) == digest, name
    # Every file except the marker itself, which cannot hash itself.
    assert set(marker.evidence_content_hashes) == set(
        frozen.REQUIRED_EVIDENCE_FILES
    ) - {frozen.STAGE_8D_FINALIZATION_NAME}


@requires_publication
def test_a_tampered_evidence_byte_is_caught(tmp_path: Path) -> None:
    """The content hashes are load-bearing, and this proves it."""
    import shutil

    mirror = tmp_path / "repo"
    shutil.copytree(EVIDENCE, mirror / frozen.EVIDENCE_DIRECTORY)
    target = mirror / frozen.EVIDENCE_DIRECTORY / frozen.PROTECTED_REGISTRY_NAME
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    marker = read_marker()
    assert (
        file_sha256(target)
        != marker.evidence_content_hashes[frozen.PROTECTED_REGISTRY_NAME]
    )


@requires_publication
def test_the_evidence_holds_no_score_no_threshold_and_no_identifier() -> None:
    require_no_forbidden_published_data(REPOSITORY_ROOT)


@requires_publication
def test_an_unexpected_published_file_is_a_finding() -> None:
    with pytest.raises(Stage8DFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            published_evidence_names(REPOSITORY_ROOT) + ("stray.json",)
        )
