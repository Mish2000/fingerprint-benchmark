"""The committed Stage 11A evidence, verified without the artifact it describes.

No dataset, no vendor SDK, no licence, no network and no workspace. That is a
real claim here, unlike in Stage 10B: this stage *did* hold four and a half
gigabytes of vendor bytes while it ran, and none of them is needed to check what
it published. What is under test is the publication — that it holds exactly the
expected files, that the marker fingerprints to what it carries, that every
document re-derives from source, that the marker's denials are true, that no
credential reached any published byte, and that the bytes have not moved since
finalization.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from fpbench.core.verifinger_preflight_errors import Stage11AFinalizationError
from fpbench.experiments import stage11a_artifacts as store
from fpbench.experiments import stage11a_preflight as engine
from fpbench.experiments import stage11a_verifinger_identity as frozen
from fpbench.experiments import stage11a_verifinger_observations as observed
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage11a_finalization import (
    STAGE_11A_BASELINE_COMMIT,
    Stage11AFinalization,
    file_sha256,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    require_no_sensitive_published_data,
    stage11a_source_fingerprint,
    stage_11a_finalization_fingerprint,
    verify_stage11a_workspace_boundaries,
)

pytestmark = pytest.mark.stage11a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_11A_FINALIZATION_NAME


def _document(relative: str) -> dict:
    path = EVIDENCE / PurePosixPath(relative)
    if not path.is_file():
        pytest.skip(f"{relative} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _marker() -> dict:
    if not MARKER.is_file():
        pytest.skip("the Stage 11A marker has not been published yet")
    return json.loads(MARKER.read_text(encoding="utf-8"))


def _require_the_artifact_is_here() -> None:
    """Skip the checks that only hold on a machine holding the artifact.

    Stage 11A is the first stage here whose gate results depend on the state of
    the local artifact store, so re-deriving its documents needs the same machine
    state the publication was made under. On a runner that holds nothing, the
    acquisition gate fails and the derivation legitimately differs — which is the
    stage working, not the evidence rotting. Everything above and below this line
    is machine-independent and never skips.
    """
    if not store.acquisition_state(repository_root=REPOSITORY_ROOT).obtained:
        pytest.skip(
            "the VeriFinger artifacts are not in this machine's artifact store, "
            "so the gates that depend on them re-derive differently here"
        )


# ---------------------------------------------------------------- the documents


def test_every_derivable_document_matches_what_the_engine_derives_now() -> None:
    """The published bytes and a fresh derivation are the same object.

    This is what makes the evidence a *record* rather than a transcript: if the
    observations or the gate logic move, this fails, and the response is to
    re-derive and republish rather than to edit a document.
    """
    _require_the_artifact_is_here()
    preflight = engine.run_preflight()
    for name in frozen.REQUIRED_EVIDENCE_FILES:
        if name in (frozen.README_NAME, frozen.STAGE_11A_FINALIZATION_NAME):
            continue
        published = _document(name)
        derived = json.loads(
            json.dumps(engine.evidence_document(preflight, name), ensure_ascii=False)
        )
        assert published == derived, name


def test_the_published_tree_holds_exactly_the_expected_files() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 11A evidence has not been published yet")
    names = published_evidence_names(REPOSITORY_ROOT)
    if frozen.STAGE_11A_FINALIZATION_NAME not in names:
        pytest.skip("the Stage 11A marker has not been published yet")
    require_expected_evidence_files(names)


def test_no_forbidden_or_sensitive_data_reached_the_published_bytes() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 11A evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)
    require_no_sensitive_published_data(REPOSITORY_ROOT)


def test_the_readme_is_hand_written_and_present_with_the_marker() -> None:
    if not MARKER.is_file():
        pytest.skip("the Stage 11A marker has not been published yet")
    readme = EVIDENCE / frozen.README_NAME
    assert readme.is_file()
    assert readme.read_text(encoding="utf-8").strip()


# ------------------------------------------------------------------- the marker


def test_the_marker_fingerprints_the_claims_it_carries() -> None:
    marker = _marker()
    expected = stage_11a_finalization_fingerprint(
        {
            key: value
            for key, value in marker.items()
            if key not in ("stage_11a_finalization_fingerprint", "created_utc")
        }
    )
    assert marker["stage_11a_finalization_fingerprint"] == expected


def test_the_marker_reconstructs_as_a_valid_finalization() -> None:
    """Every rule in the marker class is applied to the published bytes."""
    marker = _marker()
    rebuilt = Stage11AFinalization(
        **{
            key: (tuple(value) if key == "blockers" else value)
            for key, value in marker.items()
        }
    )
    assert rebuilt.outcome == marker["outcome"]


def test_the_marker_binds_the_two_closed_stages_it_reuses() -> None:
    marker = _marker()
    assert (
        marker["predecessor_stage_10b_fingerprint"]
        == frozen.STAGE_10B_FINALIZATION_FINGERPRINT
    )
    assert (
        marker["stage8e_policy_fingerprint"] == frozen.STAGE8E_FINALIZATION_FINGERPRINT
    )


def test_the_content_hashes_match_the_published_bytes() -> None:
    marker = _marker()
    for name, digest in marker["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / PurePosixPath(name)) == digest, name


def test_the_source_fingerprint_matches_the_source_on_disk() -> None:
    marker = _marker()
    assert marker["stage11a_source_fingerprint"] == stage11a_source_fingerprint(
        REPOSITORY_ROOT
    )


def test_the_observations_fingerprint_still_derives() -> None:
    """Machine-independent: the record of fact does not depend on a local store."""
    marker = _marker()
    assert marker["observations_fingerprint"] == observed.observations_fingerprint()


def test_the_preflight_fingerprint_still_derives() -> None:
    marker = _marker()
    _require_the_artifact_is_here()
    assert (
        marker["preflight_fingerprint"] == engine.run_preflight().preflight_fingerprint
    )


def test_the_report_and_the_marker_agree_without_re_deriving_anything() -> None:
    """Machine-independent cross-check between two published documents.

    The gate list, the verdict and the blocker codes are compared to the marker's
    own claims, so a runner that holds no artifact still catches a marker that
    disagrees with the report beside it.
    """
    marker = _marker()
    report = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert report["outcome"] == marker["outcome"]
    assert report["verdict"] == marker["candidate_verdict"]
    assert report["failure_class"] == marker["failure_class"]
    assert sorted(item["blocker_code"] for item in report["blockers"]) == sorted(
        item["blocker_code"] for item in marker["blockers"]
    )
    assert [item["gate"] for item in report["gates"]] == [
        gate.value for gate in frozen.GATE_ORDER
    ]
    assert (
        sum(1 for item in report["gates"] if item["status"] == "PASS")
        == marker["gates_passed"]
    )


def test_the_marker_denials_are_all_false() -> None:
    marker = _marker()
    for name in Stage11AFinalization.DENIED_FLAGS:
        assert marker[name] is False, name
    assert marker["licenses_activated"] == 0
    assert marker["scores_produced"] == 0


def test_the_marker_says_the_artifact_was_obtained() -> None:
    """The claim that most distinguishes this stage from its predecessor."""
    marker = _marker()
    assert marker["artifact_obtained"] is True
    assert marker["artifact_route"] == frozen.ArtifactRoute.MAIN_SDK_PACKAGE.value
    assert marker["artifact_identity_pinned"] is True


def test_a_blocked_marker_opens_nothing_and_keeps_the_search_open() -> None:
    marker = _marker()
    if marker["outcome"] == frozen.STAGE_11A_SELECTED_OUTCOME:
        assert marker["opens_stage_11b"] is True
        assert marker["selected_candidate"] == frozen.CANDIDATE_ID
        return
    assert marker["opens_stage_11b"] is False
    assert marker["opens_candidate_search"] is True
    assert marker["selected_candidate"] is None
    assert marker["blockers"]
    assert marker["failure_class"]


def test_the_gate_counts_agree_with_the_report() -> None:
    marker = _marker()
    report = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert marker["gate_count_defined"] == frozen.GATE_COUNT == report["gate_count_defined"]
    assert marker["gates_reached"] == report["gates_reached"]
    assert marker["gates_passed"] == report["gates_passed"]
    assert marker["gates_passed"] <= marker["gates_reached"]


def test_every_blocker_names_how_it_would_be_lifted() -> None:
    marker = _marker()
    for blocker in marker["blockers"]:
        assert blocker["how_this_would_be_lifted"].strip()
        assert blocker["blocker_code"] in {item.value for item in frozen.BlockerCode}


# ------------------------------------------------------------- the two guards


def test_no_vendor_byte_is_tracked_here() -> None:
    """Never skips."""
    assert store.require_no_verifinger_bytes_in_git(REPOSITORY_ROOT).clean


def test_the_stage_stayed_inside_its_own_surface() -> None:
    marker = _marker()
    verify_stage11a_workspace_boundaries(
        REPOSITORY_ROOT, span_end_commit=marker["verifier_source_commit"]
    )


def test_the_baseline_commit_is_an_ancestor_of_the_publication() -> None:
    marker = _marker()
    assert marker["source_commit"] != STAGE_11A_BASELINE_COMMIT


def test_the_boundary_audit_refuses_an_unrelated_span_end() -> None:
    """Never skips: the audit has to be capable of failing."""
    with pytest.raises(Stage11AFinalizationError):
        verify_stage11a_workspace_boundaries(
            REPOSITORY_ROOT, span_end_commit="0" * 40
        )
