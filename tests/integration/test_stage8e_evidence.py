"""The committed Stage 8E evidence, verified with nothing the stage needed.

No dataset, no runtime, no checkpoint, no workspace and no prior result set —
which for this stage is not much of a claim, because it never needed any of them.
What is under test is the publication: that it holds exactly the expected files,
that the marker fingerprints to what it carries, that the purpose, the policy, the
legacy audit and the repository audit all re-derive from source, that the marker's
denials are true, and that the exact bytes have not moved since finalization.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously. The tests that never
skip are the ones that keep that honest — and the ones that check the *documents*,
which are published one commit before the marker is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.serialization import to_plain
from fpbench.core.third_party_errors import Stage8EFinalizationError
from fpbench.core.third_party_models import (
    read_project_purpose_declaration,
    read_third_party_policy,
    strict_json_document,
)
from fpbench.experiments import stage8e_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage8e_finalization import (
    Stage8EFinalization,
    file_sha256,
    policy_engine_fingerprint,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    stage_8e_finalization_fingerprint,
    third_party_model_fingerprint,
)
from fpbench.experiments.stage8e_research_only_policy import (
    build_legacy_audit,
    build_repository_audit,
    require_stage8d_is_the_stage_this_follows,
    run_policy_qualification,
)
from fpbench.third_party.policy import third_party_policy
from fpbench.third_party.purpose import project_purpose

pytestmark = pytest.mark.stage8e

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _published() -> bool:
    return (EVIDENCE / frozen.STAGE_8E_FINALIZATION_NAME).is_file()


def _documents_published() -> bool:
    return all(
        (EVIDENCE / name).is_file()
        for name in frozen.REQUIRED_EVIDENCE_FILES
        if name != frozen.STAGE_8E_FINALIZATION_NAME
    )


requires_publication = pytest.mark.skipif(
    not _published(), reason="the Stage 8E marker has not been published yet"
)
requires_documents = pytest.mark.skipif(
    not _documents_published(),
    reason="the Stage 8E evidence documents have not been published yet",
)


def read_marker() -> Stage8EFinalization:
    document = json.loads(
        (EVIDENCE / frozen.STAGE_8E_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    return Stage8EFinalization(**document)


def read_document(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------ never skipped


def test_the_skip_condition_is_the_only_reason_anything_here_skips() -> None:
    """Keeps the gate honest.

    A suite that skipped for any other reason — a missing dependency, an import
    error, a marker typo — would look identical to a suite waiting for the
    publication. This test always executes, so ``pytest -m stage8e`` always has
    something to run and the skips below always mean exactly one thing.
    """
    marker_present = (EVIDENCE / frozen.STAGE_8E_FINALIZATION_NAME).is_file()
    assert marker_present == _published()
    if not EVIDENCE.is_dir():
        assert not marker_present
        assert not _documents_published()
    assert frozen.STAGE_8E_FINALIZATION_NAME == "stage-8e-finalization.json"
    assert frozen.STAGE_8E_OUTCOME == "RESEARCH_ONLY_THIRD_PARTY_POLICY_READY"
    assert len(frozen.REQUIRED_EVIDENCE_FILES) == 7


def test_the_stage_this_follows_is_the_one_it_was_frozen_against() -> None:
    """Needs no Stage 8E evidence at all: it reads Stage 8D's, and only reads."""
    require_stage8d_is_the_stage_this_follows(REPOSITORY_ROOT)


def test_stage_8d_current_evidence_is_the_recognized_successor() -> None:
    """A later security re-finalization does not rewrite Stage 8E's marker."""
    marker = REPOSITORY_ROOT / (
        "evidence/stage8d-calibration-infrastructure/stage-8d-finalization.json"
    )
    document = json.loads(marker.read_text(encoding="utf-8"))
    assert document["stage_8d_finalization_fingerprint"] == (
        frozen.STAGE8D_CURRENT_FINALIZATION_FINGERPRINT
    )
    for name, digest in document["evidence_content_hashes"].items():
        assert file_sha256(marker.parent / name) == digest, name


# ------------------------------------------------------- the five documents


@requires_documents
def test_the_published_purpose_is_the_one_the_code_derives() -> None:
    """The committed JSON is checked, not trusted."""
    stored = read_project_purpose_declaration(
        strict_json_document(
            (EVIDENCE / frozen.PROJECT_PURPOSE_NAME).read_text(encoding="utf-8")
        )
    )
    assert stored == project_purpose()
    assert stored.purpose.value == "PERSONAL_EDUCATIONAL_RESEARCH"


@requires_documents
def test_the_published_policy_is_the_one_the_code_derives() -> None:
    stored = read_third_party_policy(
        strict_json_document(
            (EVIDENCE / frozen.THIRD_PARTY_POLICY_NAME).read_text(encoding="utf-8")
        )
    )
    assert stored == third_party_policy()
    assert stored.vendoring_default == "DO_NOT_VENDOR"


@requires_documents
def test_the_legacy_audit_re_derives_from_source() -> None:
    document = read_document(frozen.LEGACY_COMPONENT_AUDIT_NAME)
    audit = build_legacy_audit(REPOSITORY_ROOT)
    assert document["audit_fingerprint"] == audit.audit_fingerprint
    assert document["component_count"] == len(audit.mappings)
    assert document["owner_risk_accepted_count"] == audit.risk_accepted_count
    assert document["blocked_count"] == 0
    assert document["by_research_use_decision"] == dict(audit.by_decision())


@requires_documents
def test_every_published_mapping_matches_the_engine_that_produced_it() -> None:
    document = read_document(frozen.LEGACY_COMPONENT_AUDIT_NAME)
    audit = build_legacy_audit(REPOSITORY_ROOT)
    published = {
        entry["usage_record"]["record_id"]: entry for entry in document["components"]
    }
    assert set(published) == {mapping.record_id for mapping in audit.mappings}
    for mapping in audit.mappings:
        entry = published[mapping.record_id]
        assert entry["observation"] == to_plain(mapping.observation)
        assert entry["assessment"] == to_plain(mapping.assessment)
        assert entry["usage_record"] == to_plain(mapping.record)


@requires_documents
def test_the_repository_audit_re_derives_and_is_clean() -> None:
    document = read_document(frozen.REPOSITORY_ARTIFACT_AUDIT_NAME)
    audit = build_repository_audit(REPOSITORY_ROOT)
    assert document["repository_audit_fingerprint"] == (
        audit.repository_audit_fingerprint
    )
    assert document["tracked_files"]["findings"] == []
    assert document["workflows"]["findings"] == []
    assert document["ignore_coverage"]["missing_patterns"] == []
    assert document["clean"] is True


@requires_documents
def test_the_contract_report_re_derives_from_source() -> None:
    """Every digest in it, not only the two the marker happens to pin."""
    from fpbench.experiments.stage8e_finalization import source_file_sha256

    report = read_document(frozen.POLICY_CONTRACT_REPORT_NAME)
    assert report["third_party_model_fingerprint"] == (
        third_party_model_fingerprint(REPOSITORY_ROOT)
    )
    assert report["policy_engine_fingerprint"] == (
        policy_engine_fingerprint(REPOSITORY_ROOT)
    )
    package = REPOSITORY_ROOT / "src" / "fpbench" / "third_party"
    published = report["third_party_package"]["module_sha256"]
    assert set(published) == set(frozen.THIRD_PARTY_PACKAGE_MODULES)
    for name, digest in published.items():
        assert digest == source_file_sha256(package / name), name

    qualification = run_policy_qualification()
    assert report["policy_qualification"]["qualification_fingerprint"] == (
        qualification.qualification_fingerprint
    )
    assert report["policy_qualification"]["case_count"] == len(qualification.cases)
    assert report["enforced_absences"]["repository_holds_no_license_file"] is True


@requires_documents
def test_the_evidence_holds_no_licence_text_no_upstream_byte_and_no_path() -> None:
    require_no_forbidden_published_data(REPOSITORY_ROOT)


@requires_documents
def test_no_published_document_holds_an_absolute_path() -> None:
    """A path is a machine, and the evidence describes no machine (docs/adr/0083)."""
    import re

    pattern = re.compile(r"(^|[\"\s])(/[A-Za-z]|[A-Za-z]:[\\/]|~/)")
    for name in frozen.REQUIRED_EVIDENCE_FILES:
        path = EVIDENCE / name
        if path.suffix != ".json" or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not pattern.search(line), f"{name}: {line.strip()}"


# ---------------------------------------------------------- the published chain


@requires_publication
def test_the_publication_holds_exactly_the_expected_files() -> None:
    names = published_evidence_names(REPOSITORY_ROOT)
    require_expected_evidence_files(names)
    assert len(names) == len(frozen.REQUIRED_EVIDENCE_FILES)


@requires_publication
def test_the_marker_fingerprints_to_what_it_carries() -> None:
    marker = read_marker()
    assert marker.stage_8e_finalization_fingerprint == (
        stage_8e_finalization_fingerprint(marker)
    )
    assert marker.outcome == frozen.STAGE_8E_OUTCOME
    assert marker.project_purpose == "PERSONAL_EDUCATIONAL_RESEARCH"


@requires_publication
def test_the_marker_denies_what_stage_8e_did_not_do() -> None:
    marker = read_marker()
    assert marker.commercial_use_by_project is False
    assert marker.third_party_redistribution_by_project is False
    assert marker.third_party_bytes_permitted_in_git is False
    assert marker.historical_evidence_changed is False
    assert marker.upstream_license_question_resolved is False
    assert marker.fpbench_license_added is False


@requires_publication
def test_the_marker_asserts_what_the_policy_says() -> None:
    marker = read_marker()
    assert marker.license_observation_separate_from_execution_decision is True
    assert marker.restricted_research_licenses_may_execute_locally is True
    assert marker.unresolved_license_may_require_owner_risk_acceptance is True
    assert marker.no_access_control_circumvention is True
    assert marker.dataset_rights_unchanged is True
    assert marker.opens_stage_9a is True


@requires_publication
def test_the_marker_binds_the_stage_it_follows() -> None:
    marker = read_marker()
    assert marker.stage8d_finalization_fingerprint == (
        frozen.STAGE8D_FINALIZATION_FINGERPRINT
    )
    assert marker.stage8d_outcome == frozen.STAGE8D_OUTCOME


@requires_publication
def test_the_marker_binds_everything_it_was_derived_from() -> None:
    marker = read_marker()
    assert marker.purpose_fingerprint == project_purpose().purpose_fingerprint
    assert marker.policy_fingerprint == third_party_policy().policy_fingerprint
    assert marker.third_party_model_fingerprint == (
        third_party_model_fingerprint(REPOSITORY_ROOT)
    )
    assert marker.policy_engine_fingerprint == (
        policy_engine_fingerprint(REPOSITORY_ROOT)
    )

    legacy = build_legacy_audit(REPOSITORY_ROOT)
    assert marker.legacy_component_audit_fingerprint == legacy.audit_fingerprint
    assert marker.legacy_component_count == len(legacy.mappings)
    assert marker.legacy_manifest_count == len(legacy.manifests)
    assert marker.owner_risk_accepted_count == legacy.risk_accepted_count
    assert marker.blocked_component_count == 0

    repository = build_repository_audit(REPOSITORY_ROOT)
    assert marker.repository_audit_fingerprint == (
        repository.repository_audit_fingerprint
    )
    assert marker.third_party_bytes_in_git == 0
    assert marker.workflow_findings == 0

    qualification = run_policy_qualification()
    assert marker.policy_qualification_fingerprint == (
        qualification.qualification_fingerprint
    )
    assert marker.policy_case_count == len(qualification.cases)


@requires_publication
def test_the_published_bytes_have_not_moved_since_finalization() -> None:
    marker = read_marker()
    for name, digest in marker.evidence_content_hashes.items():
        assert file_sha256(EVIDENCE / name) == digest, name
    # Every file except the marker itself, which cannot hash itself.
    assert set(marker.evidence_content_hashes) == set(
        frozen.REQUIRED_EVIDENCE_FILES
    ) - {frozen.STAGE_8E_FINALIZATION_NAME}


@requires_publication
def test_a_tampered_evidence_byte_is_caught(tmp_path: Path) -> None:
    """The content hashes are load-bearing, and this proves it."""
    import shutil

    mirror = tmp_path / "repo"
    shutil.copytree(EVIDENCE, mirror / frozen.EVIDENCE_DIRECTORY)
    target = mirror / frozen.EVIDENCE_DIRECTORY / frozen.THIRD_PARTY_POLICY_NAME
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    marker = read_marker()
    assert (
        file_sha256(target)
        != marker.evidence_content_hashes[frozen.THIRD_PARTY_POLICY_NAME]
    )


@requires_publication
def test_an_unexpected_published_file_is_a_finding() -> None:
    with pytest.raises(Stage8EFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            published_evidence_names(REPOSITORY_ROOT) + ("stray.json",)
        )


@requires_publication
def test_the_stage_stayed_inside_its_own_span() -> None:
    """docs/adr/0067: the span ends at the commit the marker names as its verifier."""
    from fpbench.experiments.stage8e_finalization import (
        verify_stage8e_workspace_boundaries,
    )

    verify_stage8e_workspace_boundaries(
        REPOSITORY_ROOT, span_end_commit=read_marker().verifier_source_commit
    )
