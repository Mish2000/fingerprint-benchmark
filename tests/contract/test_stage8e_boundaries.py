"""Structural Stage 8E: the package's shape, its boundaries, and the public repository.

Everything here reads the checkout and nothing else. No dataset, no runtime, no
checkpoint, no network — which for this stage is the whole point, since it is the
stage that says none of those may be in the repository in the first place.

The guard tests run against the *real* tracked file list rather than a fixture.
A guard qualified only on a temporary directory would be a guard nobody had
pointed at the thing it exists to protect.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpbench.core.third_party_errors import RepositoryArtifactError
from fpbench.core.third_party_models import (
    LicenseObservationStatus,
    ResearchUseDecision,
    ThirdPartyComponentKind,
)
from fpbench.experiments import stage8e_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage8e_finalization import (
    STAGE_8E_BASELINE_COMMIT,
    policy_engine_fingerprint,
    third_party_model_fingerprint,
)
from fpbench.experiments.stage8e_research_only_policy import (
    FORBIDDEN_WORKFLOW_TOKENS,
    audit_workflows,
    build_legacy_audit,
    build_repository_audit,
    require_stage8d_is_the_stage_this_follows,
    run_policy_qualification,
)
from fpbench.third_party.repository_guard import (
    ALLOWED_SYNTHETIC_FIXTURES,
    GUARD_RULES,
    MAX_TRACKED_FILE_BYTES,
    audit_repository_artifacts,
    require_no_third_party_bytes_in_git,
    tracked_files,
)

pytestmark = pytest.mark.stage8e_contract


# ------------------------------------------------------------- the structure


def test_the_third_party_package_holds_exactly_the_named_modules() -> None:
    package = REPOSITORY_ROOT / "src" / "fpbench" / "third_party"
    present = {path.name for path in package.glob("*.py")}
    assert present == set(frozen.THIRD_PARTY_PACKAGE_MODULES)


def test_every_stage_8e_source_file_exists() -> None:
    for relative in frozen.STAGE_8E_SOURCE_FILES:
        assert (REPOSITORY_ROOT / relative).is_file(), relative


def test_the_policy_documents_and_the_adrs_exist() -> None:
    for relative in (*frozen.POLICY_DOCUMENTS, *frozen.STAGE_8E_ADRS):
        assert (REPOSITORY_ROOT / relative).is_file(), relative


def test_the_repository_still_carries_no_license_file() -> None:
    """docs/adr/0081: a purpose policy and a copyright licence are different objects."""
    assert not (REPOSITORY_ROOT / "LICENSE").exists()
    assert not (REPOSITORY_ROOT / "LICENSE.md").exists()
    assert not (REPOSITORY_ROOT / "LICENSE.txt").exists()


def test_the_baseline_commit_is_a_full_sha() -> None:
    assert len(STAGE_8E_BASELINE_COMMIT) == 40
    assert set(STAGE_8E_BASELINE_COMMIT) <= set("0123456789abcdef")


def test_the_frozen_identifiers_are_all_well_formed() -> None:
    assert len(frozen.all_frozen_identifiers()) == len(
        set(frozen.all_frozen_identifiers())
    )


def test_no_forbidden_key_collides_with_a_published_vocabulary_value() -> None:
    """The guard checks key *names*, and enum values are legitimate key names.

    Stage 8E's own documents count components into maps keyed by enum value —
    ``by_component_kind: {"SOURCE_CODE": 4}``. A forbidden key named
    ``source_code`` would refuse a count of source-code components rather than a
    body of source code, which is how this test came to exist.
    """
    from fpbench.core.third_party_models import (
        NonBlockingRestriction,
        RedistributionDecision,
        ResearchUseBlocker,
    )

    vocabulary = {
        member.value.lower()
        for enum in (
            ThirdPartyComponentKind,
            LicenseObservationStatus,
            ResearchUseDecision,
            ResearchUseBlocker,
            NonBlockingRestriction,
            RedistributionDecision,
        )
        for member in enum
    }
    collisions = sorted(vocabulary & frozen.FORBIDDEN_PUBLISHED_KEYS)
    assert not collisions, collisions


# ------------------------------------------------------------- the boundaries


#: The layers a policy module may never reach into. A policy whose answers could
#: depend on what had been run would not be a policy.
_FORBIDDEN_ROOTS = (
    "torch",
    "yaml",
    "pyarrow",
    "fpbench.adapters",
    "fpbench.calibration",
    "fpbench.cross_algorithm",
    "fpbench.datasets",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.execution",
    "fpbench.imaging",
    "fpbench.metrics",
    "fpbench.modern_matchers",
    "fpbench.paired",
    "fpbench.protocols",
    "fpbench.storage",
)


@pytest.mark.parametrize("relative", frozen.STAGE_8E_SOURCE_FILES)
def test_no_stage_8e_module_imports_an_algorithm_or_a_derivation_layer(
    relative: str,
) -> None:
    tree = ast.parse(
        (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"), filename=relative
    )
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    blocked = sorted(
        name
        for name in imported
        if any(name == root or name.startswith(root + ".") for root in _FORBIDDEN_ROOTS)
    )
    assert not blocked, f"{relative} imports {blocked}"


def test_the_third_party_package_imports_only_core_and_itself() -> None:
    """The same layering rule ``fpbench.calibration`` follows."""
    package = REPOSITORY_ROOT / "src" / "fpbench" / "third_party"
    for name in frozen.THIRD_PARTY_PACKAGE_MODULES:
        tree = ast.parse((package / name).read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if not module.startswith("fpbench"):
                    continue
                assert module.startswith(
                    ("fpbench.core", "fpbench.third_party")
                ), f"{name} imports {module}"


def test_the_stage_this_follows_is_the_one_it_was_frozen_against() -> None:
    """Needs no Stage 8E evidence at all: it reads Stage 8D's, and only reads."""
    require_stage8d_is_the_stage_this_follows(REPOSITORY_ROOT)


# ------------------------------------------------------- the repository guard


def test_the_public_repository_holds_no_third_party_byte() -> None:
    audit = require_no_third_party_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.tracked_file_count > 0
    assert audit.hashed_file_count > 0
    assert audit.rules == GUARD_RULES


def test_the_only_tracked_images_are_the_named_synthetic_fixtures() -> None:
    """An eleventh file under tests/fixtures/imaging is a finding, not an exception."""
    images = {
        path
        for path in tracked_files(REPOSITORY_ROOT)
        if path.lower().endswith((".png", ".pgm", ".wsq", ".tif", ".tiff", ".bmp"))
    }
    assert images == set(ALLOWED_SYNTHETIC_FIXTURES)


def test_every_tracked_file_is_far_below_the_ceiling() -> None:
    largest = max(
        (REPOSITORY_ROOT / path).stat().st_size
        for path in tracked_files(REPOSITORY_ROOT)
        if (REPOSITORY_ROOT / path).is_file()
    )
    assert largest < MAX_TRACKED_FILE_BYTES


def test_a_committed_checkpoint_would_be_caught(tmp_path: Path) -> None:
    """The guard is load-bearing, and this proves it rather than assuming it."""
    import subprocess

    repository = tmp_path / "repo"
    repository.mkdir()
    for arguments in (
        ("init", "-q"),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "fixture"),
    ):
        subprocess.run(("git", "-C", str(repository), *arguments), check=True)
    (repository / "best_model.pyt").write_bytes(b"not really a checkpoint")
    subprocess.run(("git", "-C", str(repository), "add", "-A"), check=True)

    audit = audit_repository_artifacts(repository)
    assert not audit.clean
    rules = {finding.rule for finding in audit.findings}
    assert "known_checkpoint_filename" in rules
    assert "model_weight_extension" in rules
    with pytest.raises(RepositoryArtifactError, match="third-party bytes are tracked"):
        require_no_third_party_bytes_in_git(repository)


def test_a_vendored_directory_would_be_caught(tmp_path: Path) -> None:
    import subprocess

    repository = tmp_path / "repo"
    (repository / "integrations" / "somealgo" / "vendor").mkdir(parents=True)
    for arguments in (
        ("init", "-q"),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "fixture"),
    ):
        subprocess.run(("git", "-C", str(repository), *arguments), check=True)
    (repository / "integrations" / "somealgo" / "vendor" / "model.py").write_text(
        "# somebody else's code\n", encoding="utf-8"
    )
    subprocess.run(("git", "-C", str(repository), "add", "-A"), check=True)

    audit = audit_repository_artifacts(repository)
    assert {finding.rule for finding in audit.findings} == {
        "forbidden_third_party_path"
    }


def test_a_pinned_upstream_artifact_would_be_caught_by_its_digest(
    tmp_path: Path,
) -> None:
    """The backstop: every other rule evaded, and the bytes are still recognised."""
    import subprocess

    from fpbench.third_party.repository_guard import KNOWN_UPSTREAM_ARTIFACT_DIGESTS

    # The digest of a file whose name, extension, path and size say nothing.
    # Rather than reproduce 52 MB of NIST's archive, this adds its digest to the
    # scanned set for the duration of the check, which exercises the same branch.
    repository = tmp_path / "repo"
    repository.mkdir()
    for arguments in (
        ("init", "-q"),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "fixture"),
    ):
        subprocess.run(("git", "-C", str(repository), *arguments), check=True)
    payload = b"pretend these are upstream bytes"
    (repository / "notes.md").write_bytes(payload)
    subprocess.run(("git", "-C", str(repository), "add", "-A"), check=True)

    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    KNOWN_UPSTREAM_ARTIFACT_DIGESTS[digest] = "a fixture artifact"
    try:
        audit = audit_repository_artifacts(repository)
    finally:
        del KNOWN_UPSTREAM_ARTIFACT_DIGESTS[digest]
    assert {finding.rule for finding in audit.findings} == {
        "known_upstream_artifact_digest"
    }


# ------------------------------------------------------------- the workflows


def test_no_workflow_downloads_uploads_or_publishes_upstream_bytes() -> None:
    audit = audit_workflows(REPOSITORY_ROOT)
    assert audit.clean, [
        (finding.workflow, finding.token) for finding in audit.findings
    ]
    assert audit.workflow_count > 0
    assert audit.scanned_tokens == tuple(
        token for token, _field in FORBIDDEN_WORKFLOW_TOKENS
    )


def test_the_repository_audit_is_clean_end_to_end() -> None:
    audit = build_repository_audit(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.missing_ignore_patterns == ()


def test_the_audit_identity_does_not_move_when_the_repository_grows() -> None:
    """The invariant the two-commit publication depends on.

    The tracked population grows with every commit — including the commit that
    publishes this very audit — so an identity covering the file count could
    never be re-derived from a later tree, and the evidence gate would go red the
    moment the marker was added. The identity covers what the audit *concluded*;
    the count at a named commit lives in the marker.
    """
    from fpbench.third_party.repository_guard import RepositoryArtifactAudit

    audit = audit_repository_artifacts(REPOSITORY_ROOT)
    grown = RepositoryArtifactAudit(
        tracked_file_count=audit.tracked_file_count + 40,
        hashed_file_count=audit.hashed_file_count + 40,
        rules=audit.rules,
        allowed_exceptions=audit.allowed_exceptions,
        findings=audit.findings,
    )
    assert grown.audit_fingerprint == audit.audit_fingerprint
    assert grown.every_tracked_file_was_hashed is True


def test_the_repository_audit_is_deterministic() -> None:
    first = build_repository_audit(REPOSITORY_ROOT)
    second = build_repository_audit(REPOSITORY_ROOT)
    assert first.repository_audit_fingerprint == second.repository_audit_fingerprint


def test_every_published_evidence_file_uses_lf_line_endings() -> None:
    r"""``.gitattributes`` pins this directory to LF, and the marker hashes bytes.

    A document written through ``write_text`` on Windows is CRLF, is committed as
    LF, and is then checked out as CRLF here and as LF on a Linux runner — so the
    marker's content hashes would agree with exactly one of the two machines.
    Stage 8E writes evidence with :func:`write_evidence_json`, which emits bytes.
    """
    directory = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
    if not directory.is_dir():
        pytest.skip("the Stage 8E evidence has not been written yet")
    for path in sorted(directory.iterdir()):
        assert b"\r\n" not in path.read_bytes(), path.name


# ------------------------------------------------------------ the legacy audit


def test_every_already_integrated_component_is_mapped_and_none_is_blocked() -> None:
    audit = build_legacy_audit(REPOSITORY_ROOT)
    assert len(audit.mappings) == len(frozen.LEGACY_COMPONENTS)
    assert audit.blocked_count == 0
    assert {mapping.route for mapping in audit.mappings} == set(frozen.LEGACY_ROUTES)


def test_the_unresolved_components_are_risk_accepted_and_stay_unresolved() -> None:
    """docs/adr/0084: the owner accepted a risk; nobody established a right."""
    audit = build_legacy_audit(REPOSITORY_ROOT)
    unresolved = [
        mapping
        for mapping in audit.mappings
        if mapping.observation.status
        in (
            LicenseObservationStatus.NO_LICENSE_FOUND,
            LicenseObservationStatus.UNKNOWN,
        )
    ]
    assert unresolved, "this repository does hold components with no established terms"
    for mapping in unresolved:
        assert mapping.assessment.decision is ResearchUseDecision.OWNER_RISK_ACCEPTED
        assert mapping.assessment.intended_use_permission_status.value == "UNRESOLVED"
        assert mapping.record.owner_risk_acceptance is True
    assert audit.risk_accepted_count == len(unresolved)


def test_the_checkpoint_mapping_does_not_resolve_what_stage_8b_left_open() -> None:
    audit = build_legacy_audit(REPOSITORY_ROOT)
    checkpoint = audit.mapping("flx_checkpoint")
    assert checkpoint.observation.status is LicenseObservationStatus.NO_LICENSE_FOUND
    assert checkpoint.observation.declared_license_names == ()
    assert checkpoint.record.component_kind is ThirdPartyComponentKind.MODEL_WEIGHTS
    assert checkpoint.record.redistribution.decision.value == "NOT_ESTABLISHED"
    assert checkpoint.record.stored_in_git is False


def test_the_dataset_mapping_rests_on_its_own_access_terms() -> None:
    """spec section 11: Stage 8E changed nothing about dataset rights."""
    audit = build_legacy_audit(REPOSITORY_ROOT)
    dataset = audit.mapping("nist_sd300")
    assert dataset.record.component_kind is ThirdPartyComponentKind.DATASET
    assert dataset.assessment.dataset_access_terms_satisfied is True
    assert dataset.assessment.decision is not ResearchUseDecision.OWNER_RISK_ACCEPTED
    assert dataset.record.redistribution.decision.value == "NOT_ALLOWED"


def test_no_legacy_manifest_leaves_a_component_unexecutable() -> None:
    audit = build_legacy_audit(REPOSITORY_ROOT)
    assert len(audit.manifests) == len(frozen.LEGACY_ROUTES)
    for manifest in audit.manifests:
        assert manifest.opens_execution, manifest.manifest_id


def test_the_legacy_audit_is_deterministic() -> None:
    first = build_legacy_audit(REPOSITORY_ROOT)
    second = build_legacy_audit(REPOSITORY_ROOT)
    assert first.audit_fingerprint == second.audit_fingerprint


def test_the_frozen_digests_are_all_present_in_the_documents_they_came_from() -> None:
    from fpbench.experiments.stage8e_research_only_policy import (
        require_frozen_legacy_facts_match_published_evidence,
    )

    published = require_frozen_legacy_facts_match_published_evidence(REPOSITORY_ROOT)
    assert published


# ------------------------------------------------------ the policy qualification


def test_the_policy_qualification_passes_and_is_deterministic() -> None:
    first = run_policy_qualification()
    second = run_policy_qualification()
    assert first.qualification_fingerprint == second.qualification_fingerprint
    assert first.refusal_cases > 0
    assert first.decision_cases > 0
    assert (
        first.decision_cases + first.refusal_cases + first.identity_cases
        == len(first.cases)
    )


def test_the_engine_source_fingerprints_are_stable_across_two_reads() -> None:
    assert third_party_model_fingerprint(REPOSITORY_ROOT) == (
        third_party_model_fingerprint(REPOSITORY_ROOT)
    )
    assert policy_engine_fingerprint(REPOSITORY_ROOT) == (
        policy_engine_fingerprint(REPOSITORY_ROOT)
    )
