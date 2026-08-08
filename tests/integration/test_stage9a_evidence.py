"""The committed Stage 9A evidence, verified with nothing the stage needed.

No dataset, no torch, no checkpoint, no workspace and no prior result set —
which for this stage is not much of a claim, because it never needed any of them.
What is under test is the publication: that it holds exactly the expected files,
that the marker fingerprints to what it carries, that the manifests, the route
resolution and the qualification all re-derive from source, that the marker's
denials are true, and that the exact bytes have not moved since finalization.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously. The tests that never
skip are the ones that keep that honest — and the ones that check the
*documents*, which are published one commit before the marker is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.flare_errors import Stage9AFinalizationError
from fpbench.experiments import stage9a_flare_artifacts as artifacts
from fpbench.experiments import stage9a_flare_identity as frozen
from fpbench.experiments import stage9a_flare_qualification as qualification
from fpbench.experiments import stage9a_flare_route as route
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage9a_flare_finalization import (
    Stage9AFinalization,
    file_sha256,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    stage9a_source_fingerprint,
    stage_9a_finalization_fingerprint,
    verify_stage9a_workspace_boundaries,
)

pytestmark = pytest.mark.stage9a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_9A_FINALIZATION_NAME


def _document(name: str) -> dict:
    path = EVIDENCE / name
    if not path.is_file():
        pytest.skip(f"{name} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _marker() -> dict:
    if not MARKER.is_file():
        pytest.skip("the Stage 9A marker has not been published yet")
    return json.loads(MARKER.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the documents


def test_the_evidence_directory_holds_exactly_the_expected_files() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 9A evidence has not been published yet")
    names = published_evidence_names(REPOSITORY_ROOT)
    if frozen.STAGE_9A_FINALIZATION_NAME not in names:
        # The documents commit precedes the marker commit by design.
        expected = set(frozen.REQUIRED_EVIDENCE_FILES) - {
            frozen.STAGE_9A_FINALIZATION_NAME
        }
        assert set(names) == expected
        return
    require_expected_evidence_files(names)


def test_no_forbidden_data_reached_the_published_evidence() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 9A evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)


def test_the_upstream_source_manifest_pins_two_commits_and_no_branch() -> None:
    document = _document(frozen.UPSTREAM_SOURCE_MANIFEST_NAME)
    assert document["required_source_repositories"] == 2
    assert len(document["repositories"]) == 2
    assert document["branch_names_are_not_identities"] is True
    for entry in document["repositories"]:
        assert len(entry["upstream_commit"]) == 40
        assert entry["upstream_commit"] in entry["source_archive_locator"]
        assert entry["source_archive_size_bytes"] > 0


def test_the_artifact_manifest_re_derives_and_holds_no_absolute_path() -> None:
    document = _document(frozen.ARTIFACT_MANIFEST_NAME)
    inventory = artifacts.build_artifact_inventory(repository_root=REPOSITORY_ROOT)
    assert document["required_artifact_count"] == inventory.required_count
    assert document["manifests_hold_no_absolute_path"] is True
    for entry in document["artifacts"]:
        location = entry["store_relative_location"]
        assert not location.startswith("/")
        assert ":" not in location
        assert ".." not in location.split("/")


def test_the_usage_manifest_re_derives_from_the_stage8e_engine() -> None:
    document = _document(frozen.THIRD_PARTY_USAGE_MANIFEST_NAME)
    audit = artifacts.build_flare_usage_audit()
    assert document["manifest_fingerprint"] == audit.manifest.manifest_fingerprint
    assert document["audit_fingerprint"] == audit.audit_fingerprint
    assert document["purpose_fingerprint"] == frozen.STAGE8E_PURPOSE_FINGERPRINT
    assert document["policy_fingerprint"] == frozen.STAGE8E_POLICY_FINGERPRINT
    for record in document["records"]:
        assert record["stored_in_git"] is False
        assert record["stored_in_ci_artifacts"] is False
        assert record["redistributed_by_fpbench"] is False


def test_the_transform_graph_re_derives_from_source() -> None:
    document = _document(frozen.TRANSFORM_GRAPH_RESOLUTION_NAME)
    resolution = route.resolve_transform_graph()
    assert document["graph_fingerprint"] == resolution.graph_fingerprint
    assert document["operation_count"] == resolution.operation_count
    assert set(document["unresolved_operations"]) == set(
        resolution.unresolved_operations
    )
    for operation in document["operations"]:
        assert operation["authority"] in {
            item.value for item in frozen.OperationAuthority
        }


def test_the_route_audit_re_derives_from_source() -> None:
    document = _document(frozen.PUBLIC_CODE_ROUTE_AUDIT_NAME)
    audit = route.public_code_route_audit()
    assert document["audit_fingerprint"] == audit.audit_fingerprint
    assert document["row_count"] == audit.row_count
    for row in document["rows"]:
        assert row["resolution"] in {item.value for item in frozen.RouteResolution}
        assert row["paper_statement"].strip()
        assert row["official_code_location"].strip()


def test_the_paper_route_contract_states_four_branches_and_no_binary_route() -> None:
    document = _document(frozen.PAPER_ROUTE_CONTRACT_NAME)
    assert document["branch_count"] == 4
    assert len(document["branches"]) == 4
    assert document["binary_representation"] is False
    assert document["descriptor_feature_dimension"] == 6
    assert document["descriptor_scalar_count"] == 3072
    assert document["mask_scalar_count"] == 256
    assert document["score_direction"] == "HIGHER_IS_MORE_SIMILAR"


def test_the_training_provenance_does_not_claim_proof_of_absence() -> None:
    document = _document(frozen.TRAINING_PROVENANCE_NAME)
    assert document["sd300_training_overlap_status"] == "NO_EVIDENCE_FOUND"
    assert document["sd300_training_overlap_found"] is False
    assert document["sd300_data_read_by_this_stage"] is False


def test_the_checkpoint_compatibility_document_re_derives() -> None:
    document = _document(frozen.CHECKPOINT_COMPATIBILITY_NAME)
    report = qualification.build_compatibility_report(
        repository_root=REPOSITORY_ROOT
    )
    assert document["report_fingerprint"] == report.report_fingerprint
    assert document["fpbench_relaxes_strictness"] is False
    assert document["fpbench_filters_keys"] is False
    assert document["fpbench_substitutes_its_own_loader"] is False
    assert len(document["bindings"]) == len(qualification.CHECKPOINT_BINDINGS)


def test_the_qualification_report_re_derives_and_names_its_blockers() -> None:
    document = _document(frozen.QUALIFICATION_REPORT_NAME)
    outcome = qualification.build_qualification_report(
        repository_root=REPOSITORY_ROOT
    )
    assert document["outcome"] == outcome.outcome
    assert document["qualification_fingerprint"] == outcome.qualification_fingerprint
    assert document["algorithm_candidate"] == frozen.ALGORITHM_CANDIDATE_ID
    assert len(document["blockers"]) == len(outcome.blockers)
    for blocker in document["blockers"]:
        assert blocker["blocker_code"] in {item.value for item in frozen.BlockerCode}
        assert blocker["why_score_fidelity_cannot_be_established"].strip()
    assert all(document["what_this_stage_did_not_do"].values()) is False


# ------------------------------------------------------------------ the marker


def test_the_marker_reconstructs_and_fingerprints_to_what_it_carries() -> None:
    document = _marker()
    claims = {key: value for key, value in document.items() if key not in
              ("stage_9a_finalization_fingerprint", "created_utc")}
    claims["blockers"] = tuple(claims["blockers"])
    assert stage_9a_finalization_fingerprint(claims) == (
        document["stage_9a_finalization_fingerprint"]
    )
    marker = Stage9AFinalization(
        **claims,
        stage_9a_finalization_fingerprint=document[
            "stage_9a_finalization_fingerprint"
        ],
        created_utc=document["created_utc"],
    )
    assert marker.outcome in frozen.STAGE_9A_OUTCOMES


def test_the_marker_binds_the_stage8e_policy_it_reused() -> None:
    document = _marker()
    assert document["stage8e_policy_fingerprint"] == (
        frozen.STAGE8E_FINALIZATION_FINGERPRINT
    )
    artifacts.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


def test_the_marker_pins_the_source_that_decided_this_qualification() -> None:
    document = _marker()
    assert document["stage9a_source_fingerprint"] == stage9a_source_fingerprint(
        REPOSITORY_ROOT
    )


def test_the_marker_states_the_route_shape_that_makes_it_this_algorithm() -> None:
    document = _marker()
    assert document["algorithm_candidate"] == frozen.ALGORITHM_CANDIDATE_ID
    assert document["required_source_repositories"] == 2
    assert document["required_pose_estimators"] == 2
    assert document["required_enhancers"] == 2
    assert document["required_descriptor_branches"] == 4
    assert document["binary_route_enabled"] is False


def test_the_marker_denies_everything_this_stage_did_not_do() -> None:
    document = _marker()
    for name in Stage9AFinalization.DENIED_FLAGS:
        assert document[name] is False, name


def test_a_blocked_marker_names_its_blockers_and_opens_nothing() -> None:
    document = _marker()
    if document["outcome"] == frozen.STAGE_9A_READY_OUTCOME:
        assert document["blockers"] == []
        assert document["opens_stage_9b"] is True
        return
    assert document["outcome"] == frozen.STAGE_9A_BLOCKED_OUTCOME
    assert document["blockers"]
    assert document["opens_stage_9b"] is False
    for blocker in document["blockers"]:
        assert blocker["blocker_code"] in {item.value for item in frozen.BlockerCode}
        assert blocker["affected_component"].strip()
        assert blocker["evidence"].strip()
        assert blocker["why_score_fidelity_cannot_be_established"].strip()


def test_the_published_bytes_have_not_moved_since_finalization() -> None:
    document = _marker()
    for name, digest in document["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / name) == digest, name
    hashed = set(document["evidence_content_hashes"])
    expected = set(frozen.REQUIRED_EVIDENCE_FILES) - {
        frozen.STAGE_9A_FINALIZATION_NAME
    }
    assert hashed == expected


def test_stage9a_stayed_inside_its_own_span() -> None:
    document = _marker()
    verify_stage9a_workspace_boundaries(
        REPOSITORY_ROOT, span_end_commit=document["verifier_source_commit"]
    )


def test_no_flare_byte_and_no_third_party_byte_is_tracked() -> None:
    from fpbench.third_party import require_no_third_party_bytes_in_git

    assert qualification.require_no_flare_bytes_in_git(REPOSITORY_ROOT).clean
    assert require_no_third_party_bytes_in_git(REPOSITORY_ROOT).clean


def test_the_stage8e_evidence_is_byte_for_byte_what_stage8e_published() -> None:
    """Stage 9A reads Stage 8E and never writes to it (spec section 3).

    Measured across Stage 9A's own span rather than from an arbitrary point, for
    the reason docs/adr/0067 gives: a comparison against something outside the
    span attributes somebody else's commits to this stage.
    """
    import subprocess

    from fpbench.experiments.stage9a_flare_finalization import (
        STAGE_9A_BASELINE_COMMIT,
    )

    completed = subprocess.run(
        (
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "diff",
            "--name-only",
            STAGE_9A_BASELINE_COMMIT,
            "HEAD",
            "--",
            "evidence/stage8e-research-only-policy",
            "src/fpbench/third_party",
            "src/fpbench/core/third_party_models.py",
            "src/fpbench/core/third_party_errors.py",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    changed = [line for line in completed.stdout.splitlines() if line]
    assert changed == [], changed


def test_the_evidence_gate_refuses_an_unexpected_published_file() -> None:
    """Never skips: the refusal is what makes the file list a contract."""
    with pytest.raises(Stage9AFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("notes.json",)
        )


def test_the_evidence_gate_refuses_a_missing_document() -> None:
    with pytest.raises(Stage9AFinalizationError, match="missing"):
        require_expected_evidence_files(("README.md",))
