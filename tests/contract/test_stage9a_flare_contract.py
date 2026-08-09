"""The frozen Stage 9A qualification: identities, boundaries, the route, the gate.

Pure Python over two pinned source trees this repository does not hold and one
published paper it does not quote at length. No dataset, no torch, no
checkpoint, no network and no workspace — which for this stage is the point
twice over, since it is the stage that says a score-affecting operation must
come from an authority rather than from whatever ran.

The guard tests run against the *real* tracked file list rather than a fixture.
A guard qualified only on a temporary directory would be a guard nobody had
pointed at the thing it exists to protect.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpbench.core.flare_errors import (
    FlareArtifactError,
    FlareIdentityError,
    FlareQualificationError,
    FlareRouteError,
    Stage9AFinalizationError,
)
from fpbench.core.identifiers import validate_id
from fpbench.core.third_party_models import (
    LicenseObservationStatus,
    ResearchUseDecision,
    ThirdPartyComponentKind,
)
from fpbench.experiments import stage9a_flare_artifacts as artifacts
from fpbench.experiments import stage9a_flare_identity as frozen
from fpbench.experiments import stage9a_flare_qualification as qualification
from fpbench.experiments import stage9a_flare_route as route
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage9a_flare_finalization import (
    STAGE_9A_BASELINE_COMMIT,
    Stage9AFinalization,
    stage9a_source_fingerprint,
    stage_9a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage9a_contract


# ------------------------------------------------------------- the identity


def test_every_frozen_identifier_is_a_safe_path_component() -> None:
    for identifier in frozen.all_frozen_identifiers():
        assert validate_id(identifier) == identifier


def test_the_algorithm_candidate_names_what_it_claims() -> None:
    assert frozen.ALGORITHM_CANDIDATE_ID == "flare_fdd_d6_dualpose_dualenh_maxcosine"
    assert "d6" in frozen.ALGORITHM_CANDIDATE_ID
    assert frozen.BINARY_REPRESENTATION_ENABLED is False


def test_the_route_has_exactly_four_branches_over_two_poses_and_two_enhancers() -> None:
    assert len(frozen.BRANCHES) == frozen.BRANCH_COUNT == 4
    poses = {branch.pose_estimator for branch in frozen.BRANCHES}
    enhancers = {branch.enhancer for branch in frozen.BRANCHES}
    assert poses == {"VotingPose", "RegressionPose"}
    assert enhancers == {"UNetEnh", "PriorEnh"}
    assert len(poses) == frozen.REQUIRED_POSE_ESTIMATORS
    assert len(enhancers) == frozen.REQUIRED_ENHANCERS
    # Every combination appears exactly once, which is what makes it a product.
    pairs = {(branch.pose_estimator, branch.enhancer) for branch in frozen.BRANCHES}
    assert len(pairs) == 4


def test_descriptor_and_mask_shapes_follow_from_d_equals_six() -> None:
    assert frozen.DESCRIPTOR_FEATURE_DIMENSION == 6
    assert frozen.DESCRIPTOR_SHAPE == (12, 16, 16)
    assert frozen.DESCRIPTOR_SCALAR_COUNT == 3072
    assert frozen.MASK_SHAPE == (1, 16, 16)
    assert frozen.MASK_SCALAR_COUNT == 256


def test_the_geometries_are_the_paper_s_and_the_configuration_s() -> None:
    assert frozen.ALIGNED_GEOMETRY == (512, 512)
    assert frozen.FDRN_GEOMETRY == (256, 256)
    assert frozen.INPUT_PPI == 500
    assert frozen.INPUT_PROFILE == "canonical_500"
    assert frozen.INPUT_PIXEL_FORMAT == "gray8"


def test_a_repository_pinned_by_a_branch_name_is_refused() -> None:
    with pytest.raises(FlareIdentityError, match="full 40-character"):
        frozen.UpstreamRepository(
            repository_id="not_pinned",
            upstream_name="Yu-Yy/FLARE",
            html_locator="https://github.com/Yu-Yy/FLARE",
            default_branch_observed="master",
            commit="master",
            archive_locator="https://codeload.github.com/Yu-Yy/FLARE/tar.gz/master",
            archive_filename="FLARE.tar.gz",
            archive_sha256="0" * 64,
            archive_size_bytes=1,
            license_document_sha256="0" * 64,
            readme_document_sha256="0" * 64,
            acquisition_timestamp_utc="2026-08-08T00:00:00Z",
            role="whatever master happens to be",
        )


def test_both_repositories_are_pinned_to_full_commits() -> None:
    assert len(frozen.UPSTREAM_REPOSITORIES) == frozen.REQUIRED_SOURCE_REPOSITORIES
    for repository in frozen.UPSTREAM_REPOSITORIES:
        assert len(repository.commit) == 40
        assert repository.commit in repository.archive_locator
        assert repository.default_branch_observed not in {
            repository.commit,
        }


def test_an_artifact_with_a_digest_and_no_size_is_refused() -> None:
    with pytest.raises(FlareIdentityError, match="together or not at all"):
        frozen.RequiredArtifact(
            artifact_id="half_pinned",
            component_role="a checkpoint",
            component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
            subject="a checkpoint pinned by a digest and nothing else",
            upstream_name="somewhere",
            locator="google-drive-file:abc",
            locator_kind="google_drive_file",
            upstream_relative_path="model.pth",
            store_relative_location="flare/x/model.pth",
            repository_id="flare_main",
            required_by=("descriptor",),
            expected_sha256="0" * 64,
        )


def test_the_transitive_prior_artifact_was_discovered_and_is_required() -> None:
    prior = next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if item.artifact_id == "flare_prior_codebook_checkpoint"
    )
    assert prior.discovered_from == "flare_priorenh_vq_config"
    assert prior.upstream_relative_path.endswith("Prior.ckpt")
    assert ("flare_priorenh_vq_config", "ckpt_path", prior.artifact_id) in (
        frozen.TRANSITIVE_ARTIFACT_SOURCES
    )


def test_the_paper_route_is_stated_in_order_and_every_stage_cites_the_paper() -> None:
    orders = [stage.order for stage in frozen.PAPER_ROUTE]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)
    for stage in frozen.PAPER_ROUTE:
        assert frozen.PAPER_ARXIV_LOCATOR in stage.paper_locator
        assert stage.statement.strip()


# --------------------------------------------------------- Stage 8E is reused


def test_stage9a_binds_the_exact_stage8e_policy_it_was_written_against() -> None:
    artifacts.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


def test_stage9a_source_does_not_write_anywhere_near_stage8e() -> None:
    """Stage 8E is read from and never written to (spec section 3)."""
    forbidden_writes = ("open(", "write_text", "write_bytes", "unlink", "replace(")
    for relative in frozen.STAGE_9A_SOURCE_FILES:
        text = (REPOSITORY_ROOT / Path(relative)).read_text(encoding="utf-8")
        for marker in ("src/fpbench/third_party", "stage8e-research-only-policy"):
            for line in text.splitlines():
                if marker in line and any(call in line for call in forbidden_writes):
                    raise AssertionError(f"{relative} writes to {marker}: {line!r}")


def test_stage9a_does_not_fork_the_stage8e_decision_engine() -> None:
    """Every research-use decision comes from Stage 8E's one engine.

    A second engine would be a second policy, and the failure mode it invites is
    the one Stage 8E was written to remove: two answers to the same question
    (docs/adr/0082).
    """
    source = (
        REPOSITORY_ROOT / Path("src/fpbench/experiments/stage9a_flare_artifacts.py")
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "assess_research_use" not in defined
    assert "decide" not in defined
    assert "from fpbench.third_party import" in source


def test_no_flare_digest_was_added_to_the_stage8e_registry() -> None:
    from fpbench.third_party.repository_guard import KNOWN_UPSTREAM_ARTIFACT_DIGESTS

    flare = set(qualification.flare_artifact_digests())
    assert flare
    assert not (flare & set(KNOWN_UPSTREAM_ARTIFACT_DIGESTS))


# ------------------------------------------------- observation and decision


def test_the_two_repositories_carry_conflicting_notices() -> None:
    for artifact_id in ("flare_source_archive", "flare_enh_source_archive"):
        artifact = next(
            item
            for item in frozen.REQUIRED_ARTIFACTS
            if item.artifact_id == artifact_id
        )
        observation = artifacts.observation_for(artifact)
        assert observation.status is LicenseObservationStatus.CONFLICTING_NOTICES
        assert len(observation.evidence) == 2


def test_a_separately_hosted_checkpoint_is_unknown_rather_than_unlicensed() -> None:
    """``UNKNOWN`` says nobody has looked; ``NO_LICENSE_FOUND`` claims an inspection."""
    artifact = next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if item.artifact_id == "flare_fdd_checkpoint"
    )
    observation = artifacts.observation_for(artifact)
    assert observation.status is LicenseObservationStatus.UNKNOWN
    assert observation.evidence == ()


def test_an_unenrolled_checkpoint_is_blocked_by_the_policy_not_by_this_stage() -> None:
    audit = artifacts.build_flare_usage_audit()
    blocked = {mapping.artifact_id for mapping in audit.blocked}
    assert blocked == set(qualification.REQUIRED_CHECKPOINT_ARTIFACTS)
    for mapping in audit.blocked:
        assert mapping.assessment.decision is ResearchUseDecision.BLOCKED
        assert mapping.assessment.blockers
    assert audit.opens_execution is False


def test_the_source_components_pass_the_intersection_rule() -> None:
    audit = artifacts.build_flare_usage_audit()
    for artifact_id in (
        "flare_source_archive",
        "flare_enh_source_archive",
        "flare_desc_configs",
        "flare_priorenh_vq_config",
    ):
        mapping = audit.mapping(artifact_id)
        assert mapping.assessment.decision is (
            ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION
        )
        assert mapping.assessment.intersection_permits_intended_use is True


def test_every_record_is_bound_to_the_one_frozen_purpose_and_policy() -> None:
    audit = artifacts.build_flare_usage_audit()
    assert audit.manifest.purpose_fingerprint == frozen.STAGE8E_PURPOSE_FINGERPRINT
    assert audit.manifest.policy_fingerprint == frozen.STAGE8E_POLICY_FINGERPRINT
    assert len(audit.mappings) == len(frozen.REQUIRED_ARTIFACTS)


def test_no_record_claims_this_project_publishes_anything() -> None:
    audit = artifacts.build_flare_usage_audit()
    for mapping in audit.mappings:
        assert mapping.record.stored_in_git is False
        assert mapping.record.stored_in_ci_artifacts is False
        assert mapping.record.redistribution.redistributed_by_fpbench is False


# ------------------------------------------------------------- the placements


def test_a_placement_needs_an_established_identity() -> None:
    artifact = next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if not item.identity_established
    )
    with pytest.raises(FlareArtifactError, match="no identity"):
        artifacts.placement_for(artifact)


def test_a_placement_never_names_a_machine() -> None:
    for placement in artifacts.placements():
        assert not placement.relative_location.startswith("/")
        assert ".." not in placement.relative_location.split("/")
        assert ":" not in placement.relative_location
        assert placement.expected_size_bytes > 0


def test_plausibility_refuses_an_html_page_served_instead_of_a_file(
    tmp_path: Path,
) -> None:
    artifact = next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if item.artifact_id == "flare_fdd_checkpoint"
    )
    path = tmp_path / "desc_model.pth.tar"
    path.write_bytes(b"<!DOCTYPE html><html><body>Google Drive</body></html>" * 40)
    report = artifacts.check_plausibility(artifact, path)
    assert report.plausible is False
    assert report.detected_form == "html_document"
    assert any("HTML" in finding for finding in report.findings)


def test_plausibility_refuses_an_empty_file(tmp_path: Path) -> None:
    artifact = next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if item.artifact_id == "flare_fdd_checkpoint"
    )
    path = tmp_path / "desc_model.pth.tar"
    path.write_bytes(b"")
    report = artifacts.check_plausibility(artifact, path)
    assert report.plausible is False
    assert "empty" in " ".join(report.findings)


def test_enrollment_refuses_bytes_that_are_not_the_artifact(tmp_path: Path) -> None:
    artifact = next(
        item
        for item in frozen.REQUIRED_ARTIFACTS
        if item.artifact_id == "flare_source_archive"
    )
    path = tmp_path / Path(artifact.store_relative_location)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"<html>not an archive</html>" * 100)
    with pytest.raises(FlareArtifactError, match="refusing to enroll"):
        artifacts.enroll_artifact(artifact, root=tmp_path)


def test_the_inventory_reports_absence_rather_than_raising(tmp_path: Path) -> None:
    inventory = artifacts.build_artifact_inventory(root=tmp_path)
    assert inventory.required_count == len(frozen.REQUIRED_ARTIFACTS)
    assert inventory.locally_verified_count == 0
    assert set(inventory.missing) == {
        item.artifact_id for item in frozen.REQUIRED_ARTIFACTS
    }


# --------------------------------------------------------------- the route


def test_the_transform_graph_runs_from_the_input_bytes_to_the_tensor() -> None:
    operations = route.transform_graph()
    stages = [operation.stage for operation in operations]
    assert stages[0] == "decoder"
    assert "512x512 aligned image" in stages
    assert "enhancement" in stages
    assert "256x256 FDRN input" in stages
    assert "FDRN normalization" in stages
    assert stages[-1] == "fusion"


def test_every_authoritative_operation_cites_where_the_authority_is() -> None:
    for operation in route.transform_graph():
        if operation.authority.is_authoritative:
            assert operation.authority_locator.strip()


def test_an_authoritative_operation_with_no_locator_is_refused() -> None:
    with pytest.raises(FlareRouteError, match="names where"):
        route.TransformOperation(
            operation_id="unsourced",
            stage="decoder",
            description="something that claims an authority it cannot cite",
            authority=frozen.OperationAuthority.PAPER_EXPLICIT,
            authority_locator="   ",
            score_affecting=True,
        )


def test_operation_order_is_explicit_while_two_pixel_implementations_are_not() -> None:
    resolution = route.resolve_transform_graph()
    assert resolution.authoritative_count == resolution.operation_count == 17
    assert resolution.unresolved_operations == ()
    assert set(resolution.implementation_incomplete_operations) == {
        "aligned_crop_512",
        "downsample_512_to_256",
    }
    assert set(resolution.unresolved_parameters) == {
        "aligned_crop_512.border_fill",
        "downsample_512_to_256.interpolation",
    }
    assert resolution.resolved is False
    operations = {item.operation_id: item for item in route.transform_graph()}
    for operation_id in resolution.implementation_incomplete_operations:
        operation = operations[operation_id]
        assert operation.authority is frozen.OperationAuthority.PAPER_EXPLICIT
        assert (
            operation.implementation_completeness
            is frozen.ImplementationCompleteness.UNRESOLVED
        )
        assert operation.unresolved_parameters


def test_every_operation_and_its_order_has_an_authority() -> None:
    for operation in route.transform_graph():
        assert operation.authority.is_authoritative
        assert operation.blocks is False


def test_the_audit_resolves_every_row_or_names_it() -> None:
    audit = route.public_code_route_audit()
    assert audit.row_count == len(route.ROUTE_AUDIT_ROWS)
    assert audit.score_affecting_contradictory == (
        "alignment_then_enhancement_ordering",
    )
    assert set(audit.score_affecting_ambiguous) == {
        "aligned_crop_border_fill",
        "downsample_to_fdrn_input",
        "four_branch_orchestration",
    }
    assert audit.resolved is False


def test_every_audit_row_carries_a_paper_statement_and_a_code_location() -> None:
    for row in route.ROUTE_AUDIT_ROWS:
        assert row.paper_statement.strip()
        assert row.paper_source.strip()
        assert row.official_code_location.strip()


def test_the_blockers_the_route_contributes_are_derived_not_listed() -> None:
    blockers = {item.value for item in route.route_blockers()}
    assert blockers == {
        "SCORE_AFFECTING_PARAMETER_UNRESOLVED",
        "PAPER_CODE_CONTRADICTION",
        "FULL_FOUR_BRANCH_ROUTE_UNRESOLVED",
    }


def test_every_score_affecting_parameter_has_a_source_and_an_authority() -> None:
    for parameter in route.PARAMETER_PROVENANCE:
        assert parameter.value.strip()
        assert parameter.source_type.strip()
        assert parameter.source_locator.strip()
        if parameter.blocks:
            assert "unresolved" in parameter.value.lower()


def test_the_priorenh_weight_comes_from_the_pinned_cli_default() -> None:
    parameter = next(
        item for item in route.PARAMETER_PROVENANCE if item.parameter == "priorenh.w"
    )
    assert parameter.value == "0.5"
    assert parameter.authority is frozen.OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT


# --------------------------------------------------------- the score contract


def test_the_score_contract_states_the_masked_cosine_and_not_a_library_cosine() -> None:
    contract = route.score_contract()
    assert contract["library_cosine_substitution_permitted"] is False
    assert "clip(1e-3, None)" in contract["denominator_clip"]
    assert contract["mask_semantics"].startswith("continuous")
    assert contract["score_direction"] == "HIGHER_IS_MORE_SIMILAR"
    assert contract["degenerate_overlap"]["new_policy_required"] is False


def test_the_route_model_qualifies_every_property_of_that_contract() -> None:
    model = qualification.run_route_model_qualification()
    assert model.all_hold, model.failing
    assert len(model.cases) >= 10


def test_fusion_refuses_anything_but_the_four_frozen_branches() -> None:
    with pytest.raises(FlareQualificationError, match="fuses exactly"):
        qualification.reference_route_score(
            {"voting_unetenh": 1.0, "voting_priorenh": 0.0, "regression_unetenh": 0.0}
        )


def test_a_descriptor_that_does_not_tile_its_mask_cannot_be_scored() -> None:
    with pytest.raises(FlareQualificationError, match="does not tile"):
        qualification.reference_branch_score([0.0] * 10, [0.0] * 10, [1.0], [1.0])


# ----------------------------------------------------- checkpoint bindings


def test_every_checkpoint_has_a_declared_binding_that_cites_its_script() -> None:
    assert len(qualification.CHECKPOINT_BINDINGS) == 6
    for binding in qualification.CHECKPOINT_BINDINGS:
        assert binding.construction_locator.strip()
        assert binding.loader_locator.strip()
        assert binding.constructor_arguments
        assert binding.state_dict_path.strip()
        assert binding.key_transformations


def test_the_enhancement_repository_loader_differs_from_flare_s() -> None:
    """Recorded because it differs, not unified because it should not."""
    unetenh = qualification.binding_for("flare_unetenh_checkpoint")
    fdd = qualification.binding_for("flare_fdd_checkpoint")
    assert unetenh.state_dict_path == 'checkpoint["model"]'
    assert "else the checkpoint itself" in fdd.state_dict_path
    assert fdd.wrapped_in_data_parallel is True
    assert unetenh.wrapped_in_data_parallel is False


def test_the_prior_artifact_takes_a_different_path_and_can_drop_keys() -> None:
    prior = qualification.binding_for("flare_prior_codebook_checkpoint")
    assert prior.state_dict_path == 'checkpoint["state_dict"]'
    assert any(
        "dropped" in item.transformation for item in prior.key_transformations
    )


def test_no_module_relaxes_strictness_or_filters_keys() -> None:
    """Checked as code rather than as text: a docstring may say the word."""
    for relative in frozen.STAGE_9A_SOURCE_FILES:
        tree = ast.parse(
            (REPOSITORY_ROOT / Path(relative)).read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "strict" and isinstance(
                    keyword.value, ast.Constant
                ):
                    assert keyword.value.value is not False, (
                        f"{relative} relaxes load strictness"
                    )


def test_the_compatibility_report_says_not_performed_rather_than_compatible() -> None:
    report = qualification.build_compatibility_report(repository_root=REPOSITORY_ROOT)
    assert report.all_established is False
    assert set(report.unestablished) == set(
        qualification.REQUIRED_CHECKPOINT_ARTIFACTS
    )
    for entry in report.entries:
        assert entry.established is False
        assert entry.reason.strip()


def test_uninspected_compatibility_is_not_reported_as_a_model_mismatch() -> None:
    unresolved = qualification.CheckpointCompatibility(
        artifact_id="not_inspected",
        model_class="Model",
        established=False,
        inspection_performed=False,
        reason="checkpoint bytes are absent",
    )
    mismatch = qualification.CheckpointCompatibility(
        artifact_id="inspected_mismatch",
        model_class="Model",
        established=False,
        inspection_performed=True,
        unexplained_shape_mismatches=1,
        reason="one inference parameter has the wrong shape",
    )
    report = qualification.CompatibilityReport(
        entries=(unresolved, mismatch),
        torch_available=True,
        report_fingerprint="0" * 64,
    )

    blockers = {
        item.blocker_code: item.affected_component
        for item in qualification._checkpoint_compatibility_blockers(report)
    }
    assert blockers == {
        "CHECKPOINT_COMPATIBILITY_UNRESOLVED": "not_inspected",
        "CHECKPOINT_MODEL_MISMATCH": "inspected_mismatch",
    }


# ----------------------------------------------------- the FLARE byte guard


def test_no_flare_byte_is_tracked_in_this_public_repository() -> None:
    audit = qualification.require_no_flare_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.tracked_file_count > 0
    assert audit.hashed_file_count > 0
    assert audit.known_digest_count > 0


def test_the_guard_catches_a_known_artifact_however_it_was_renamed(
    tmp_path: Path,
) -> None:
    """The digest rule fires on bytes, not on names, which is its whole job.

    Exercised against a stand-in registry, because reproducing an actual FLARE
    artifact in a test would be the very thing the guard exists to prevent.
    """
    import hashlib
    import subprocess

    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    payload = b"pretend these are upstream bytes\n"
    (tmp_path / "innocuous_name.txt").write_bytes(payload)
    (tmp_path / "unrelated.txt").write_bytes(b"nothing upstream here\n")
    subprocess.run(("git", "-C", str(tmp_path), "add", "-A"), check=True)

    registry = {
        hashlib.sha256(payload).hexdigest(): ("stand_in", "a stand-in artifact")
    }
    audit = qualification.audit_tracked_bytes_against_flare_artifacts(
        tmp_path, digests=registry
    )
    assert audit.clean is False
    assert [finding.path for finding in audit.findings] == ["innocuous_name.txt"]
    assert audit.findings[0].artifact_id == "stand_in"
    assert audit.hashed_file_count == 2


def test_every_established_flare_digest_is_in_the_guard_registry() -> None:
    registry = qualification.flare_artifact_digests()
    established = {
        item.expected_sha256
        for item in frozen.REQUIRED_ARTIFACTS
        if item.identity_established
    }
    assert set(registry) == established
    assert len(established) >= 4


def test_the_synthetic_fixture_writer_refuses_to_write_into_the_repository() -> None:
    with pytest.raises(FlareQualificationError, match="inside the repository"):
        qualification.write_synthetic_images(REPOSITORY_ROOT / "tests" / "fixtures")


def test_the_synthetic_fixtures_are_generated_at_test_time(tmp_path: Path) -> None:
    written = qualification.write_synthetic_images(tmp_path / "flare")
    assert {path.name for path in written} == set(
        qualification.SYNTHETIC_IMAGE_NAMES
    )
    for path in written:
        assert path.stat().st_size > 0


def test_stage9a_adds_no_image_to_the_tracked_tree() -> None:
    from fpbench.third_party.repository_guard import (
        ALLOWED_SYNTHETIC_FIXTURES,
        require_no_third_party_bytes_in_git,
    )

    audit = require_no_third_party_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert set(audit.allowed_exceptions) == set(ALLOWED_SYNTHETIC_FIXTURES)
    assert len(ALLOWED_SYNTHETIC_FIXTURES) == 10


# ------------------------------------------------------------- the boundaries


def test_no_stage9a_module_imports_a_runtime_at_module_level() -> None:
    from fpbench.experiments.stage9a_flare_finalization import (
        _DEFERRED_ONLY_IMPORT_PREFIXES,
        _module_level_imports,
    )

    for relative in frozen.STAGE_9A_SOURCE_FILES:
        tree = ast.parse(
            (REPOSITORY_ROOT / Path(relative)).read_text(encoding="utf-8")
        )
        eager = [
            name
            for name in _module_level_imports(tree)
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in _DEFERRED_ONLY_IMPORT_PREFIXES
            )
        ]
        assert not eager, f"{relative} imports {eager} at module level"


def test_no_stage9a_module_imports_an_algorithm_or_a_derivation_layer() -> None:
    from fpbench.experiments.stage9a_flare_finalization import (
        _FORBIDDEN_IMPORT_PREFIXES,
    )

    for relative in frozen.STAGE_9A_SOURCE_FILES:
        tree = ast.parse(
            (REPOSITORY_ROOT / Path(relative)).read_text(encoding="utf-8")
        )
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        blocked = [
            name
            for name in imported
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in _FORBIDDEN_IMPORT_PREFIXES
            )
        ]
        assert not blocked, f"{relative} imports {blocked}"


def test_every_stage9a_source_file_exists_and_is_pinned_by_the_fingerprint() -> None:
    for relative in frozen.STAGE_9A_SOURCE_FILES:
        assert (REPOSITORY_ROOT / Path(relative)).is_file()
    assert len(stage9a_source_fingerprint(REPOSITORY_ROOT)) == 64


def test_every_stage9a_adr_and_document_is_present() -> None:
    for relative in frozen.STAGE_9A_ADRS:
        assert (REPOSITORY_ROOT / Path(relative)).is_file()
    for relative in frozen.STAGE_9A_DOCUMENTS:
        assert (REPOSITORY_ROOT / Path(relative)).is_file()


def test_the_baseline_commit_is_an_ancestor_of_head() -> None:
    import subprocess

    completed = subprocess.run(
        (
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "merge-base",
            "--is-ancestor",
            STAGE_9A_BASELINE_COMMIT,
            "HEAD",
        ),
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0


# ----------------------------------------------------------------- the marker


def _ready_claims() -> dict:
    """A marker whose every gate is closed, for exercising the READY branch."""
    return {
        "schema_version": "1",
        "kind": "stage_9a_finalization",
        "outcome": frozen.STAGE_9A_READY_OUTCOME,
        "algorithm_candidate": frozen.ALGORITHM_CANDIDATE_ID,
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage9a_source_fingerprint": "a" * 64,
        "required_source_repositories": 2,
        "required_pose_estimators": 2,
        "required_enhancers": 2,
        "required_descriptor_branches": 4,
        "binary_route_enabled": False,
        "upstream_source_manifest_fingerprint": "b" * 64,
        "artifact_manifest_fingerprint": "c" * 64,
        "third_party_usage_manifest_fingerprint": "d" * 64,
        "required_artifact_count": 10,
        "all_required_artifacts_identity_established": True,
        "all_required_artifacts_locally_verified": True,
        "all_required_research_use_decisions_open_execution": True,
        "transform_graph_fingerprint": "e" * 64,
        "public_code_route_audit_fingerprint": "f" * 64,
        "checkpoint_compatibility_fingerprint": "0" * 64,
        "route_model_qualification_fingerprint": "1" * 64,
        "qualification_fingerprint": "2" * 64,
        "paper_route_resolved": True,
        "public_code_route_resolved": True,
        "transform_graph_resolved": True,
        "checkpoint_compatibility_resolved": True,
        "material_parameter_provenance_complete": True,
        "route_model_qualification_holds": True,
        "training_overlap_with_sd300_found": False,
        "training_overlap_status": "NO_EVIDENCE_FOUND",
        "sd300_image_bytes_read": False,
        "sd300_score_rows_read": False,
        "prior_algorithm_scores_read": False,
        "calibration_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "production_adapter_created": False,
        "runtime_qualified": False,
        "benchmark_run_performed": False,
        "third_party_bytes_added_to_git": False,
        "stage8e_evidence_changed": False,
        "upstream_behaviour_modified": False,
        "opens_stage_9b": True,
        "blockers": (),
        "evidence_content_hashes": {},
        "source_commit": "3" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "3" * 40,
        "verifier_source_tree_clean": True,
    }


def _marker(claims: dict) -> Stage9AFinalization:
    return Stage9AFinalization(
        **claims,
        stage_9a_finalization_fingerprint=stage_9a_finalization_fingerprint(claims),
        created_utc="2026-08-08T00:00:00Z",
    )


def test_a_ready_marker_with_a_blocker_is_refused() -> None:
    claims = _ready_claims()
    claims["blockers"] = (
        {
            "blocker_code": "REQUIRED_ARTIFACT_MISSING",
            "affected_component": "x",
            "evidence": "y",
            "why_score_fidelity_cannot_be_established": "z",
        },
    )
    with pytest.raises(ValueError, match="carries no blockers"):
        _marker(claims)


def test_a_ready_marker_with_an_open_gate_is_refused() -> None:
    claims = _ready_claims()
    claims["transform_graph_resolved"] = False
    with pytest.raises(ValueError, match="every gate"):
        _marker(claims)


def test_a_blocked_marker_with_no_blocker_is_refused() -> None:
    claims = _ready_claims()
    claims["outcome"] = frozen.STAGE_9A_BLOCKED_OUTCOME
    claims["opens_stage_9b"] = False
    with pytest.raises(ValueError, match="names which blockers"):
        _marker(claims)


def test_a_blocked_marker_may_not_open_stage_9b() -> None:
    claims = _ready_claims()
    claims["outcome"] = frozen.STAGE_9A_BLOCKED_OUTCOME
    claims["blockers"] = (
        {
            "blocker_code": "SCORE_AFFECTING_PARAMETER_UNRESOLVED",
            "affected_component": "aligned_crop_512.border_fill",
            "evidence": "transform-graph-resolution.json",
            "why_score_fidelity_cannot_be_established": "no authority",
        },
    )
    with pytest.raises(ValueError, match="opens nothing"):
        _marker(claims)


def test_a_marker_with_three_branches_is_refused() -> None:
    claims = _ready_claims()
    claims["required_descriptor_branches"] = 3
    with pytest.raises(ValueError, match="different algorithm"):
        _marker(claims)


def test_a_marker_that_enabled_the_binary_route_is_refused() -> None:
    claims = _ready_claims()
    claims["binary_route_enabled"] = True
    with pytest.raises(ValueError, match="binary_route_enabled is false"):
        _marker(claims)


def test_proven_absent_is_not_an_available_training_overlap_status() -> None:
    claims = _ready_claims()
    claims["training_overlap_status"] = "PROVEN_ABSENT"
    with pytest.raises(ValueError, match="absence of evidence"):
        _marker(claims)


def test_a_marker_that_claimed_a_calibration_is_refused() -> None:
    claims = _ready_claims()
    claims["calibration_performed"] = True
    with pytest.raises(ValueError, match="calibration_performed is false"):
        _marker(claims)


def test_a_marker_bound_to_a_different_stage8e_policy_is_refused() -> None:
    claims = _ready_claims()
    claims["stage8e_policy_fingerprint"] = "9" * 64
    with pytest.raises(ValueError, match="closed stage"):
        _marker(claims)


def test_a_marker_whose_fingerprint_does_not_cover_its_claims_is_refused() -> None:
    claims = _ready_claims()
    with pytest.raises(ValueError, match="does not cover"):
        Stage9AFinalization(
            **claims,
            stage_9a_finalization_fingerprint="4" * 64,
            created_utc="2026-08-08T00:00:00Z",
        )


def test_a_blocked_marker_is_a_complete_and_legal_outcome() -> None:
    claims = _ready_claims()
    claims["outcome"] = frozen.STAGE_9A_BLOCKED_OUTCOME
    claims["opens_stage_9b"] = False
    claims["transform_graph_resolved"] = False
    claims["blockers"] = (
        {
            "blocker_code": "SCORE_AFFECTING_PARAMETER_UNRESOLVED",
            "affected_component": (
                "aligned_crop_512.border_fill, "
                "downsample_512_to_256.interpolation"
            ),
            "evidence": "transform-graph-resolution.json",
            "why_score_fidelity_cannot_be_established": (
                "every implementation of these produces different pixels"
            ),
        },
    )
    marker = _marker(claims)
    assert marker.outcome == frozen.STAGE_9A_BLOCKED_OUTCOME
    assert marker.opens_stage_9b is False
    assert len(marker.blockers) == 1


# ------------------------------------------------------- the qualification


def test_qualification_identity_ignores_partial_local_cache_population() -> None:
    def blocker(affected_component: str) -> qualification.BlockerDetail:
        return qualification.BlockerDetail(
            blocker_code=frozen.BlockerCode.REQUIRED_ARTIFACT_MISSING.value,
            affected_component=affected_component,
            evidence="artifact-manifest.json local_status",
            why_score_fidelity_cannot_be_established="required bytes are absent",
        )

    gates: dict[str, bool | int] = {
        "all_identities_established": False,
        "all_locally_verified": False,
        "research_use_opens_execution": False,
        "checkpoint_compatibility_established": False,
        "paper_route_resolved": True,
        "public_code_route_resolved": False,
        "transform_graph_resolved": False,
        "parameter_provenance_complete": False,
        "route_model_holds": True,
        "training_overlap_found": False,
        "flare_bytes_in_git": 0,
    }
    fixed = {
        "outcome": frozen.STAGE_9A_BLOCKED_OUTCOME,
        "gate_conclusions": gates,
        "graph_fingerprint": "a" * 64,
        "audit_fingerprint": "b" * 64,
        "usage_audit_fingerprint": "c" * 64,
        "route_model_fingerprint": "d" * 64,
    }

    empty_store = qualification._qualification_fingerprint(
        blockers=(blocker("all ten required artifacts"),), **fixed
    )
    partial_store = qualification._qualification_fingerprint(
        blockers=(blocker("the six artifacts not present on this machine"),),
        **fixed,
    )
    assert empty_store == partial_store

    closed_gates = dict(gates)
    closed_gates["all_locally_verified"] = True
    fully_verified = qualification._qualification_fingerprint(
        outcome=frozen.STAGE_9A_BLOCKED_OUTCOME,
        blockers=(),
        gate_conclusions=closed_gates,
        graph_fingerprint="a" * 64,
        audit_fingerprint="b" * 64,
        usage_audit_fingerprint="c" * 64,
        route_model_fingerprint="d" * 64,
    )
    assert fully_verified != partial_store


def test_the_outcome_is_derived_from_the_gates_rather_than_supplied() -> None:
    outcome = qualification.build_qualification_report(
        repository_root=REPOSITORY_ROOT
    )
    assert outcome.outcome in frozen.STAGE_9A_OUTCOMES
    assert outcome.ready is (outcome.outcome == frozen.STAGE_9A_READY_OUTCOME)
    if outcome.blockers:
        assert outcome.outcome == frozen.STAGE_9A_BLOCKED_OUTCOME
    for blocker in outcome.blockers:
        assert blocker.blocker_code in {item.value for item in frozen.BlockerCode}
        assert blocker.affected_component.strip()
        assert blocker.why_score_fidelity_cannot_be_established.strip()


def test_this_stage_read_no_sd300_data_and_produced_no_decision() -> None:
    outcome = qualification.build_qualification_report(
        repository_root=REPOSITORY_ROOT
    )
    document = qualification.qualification_report_document(
        outcome,
        graph=route.resolve_transform_graph(),
        audit=route.public_code_route_audit(),
        model=qualification.run_route_model_qualification(),
        byte_audit=qualification.audit_tracked_bytes_against_flare_artifacts(
            REPOSITORY_ROOT
        ),
    )
    denials = document["what_this_stage_did_not_do"]
    assert all(value is False for value in denials.values())


def test_the_training_provenance_reports_no_evidence_not_proof_of_absence() -> None:
    provenance = route.training_provenance()
    assert provenance["sd300_training_overlap_status"] == "NO_EVIDENCE_FOUND"
    assert provenance["sd300_training_overlap_found"] is False
    assert provenance["sd300_data_read_by_this_stage"] is False
    assert "SD300" not in provenance["datasets_named_anywhere_in_the_paper"]
    assert "NIST SD302" in provenance["datasets_named_anywhere_in_the_paper"]


def test_the_stage_publishes_no_forbidden_key_in_any_document() -> None:
    from fpbench.experiments.stage9a_flare_finalization import _forbidden_keys

    outcome = qualification.build_qualification_report(
        repository_root=REPOSITORY_ROOT
    )
    inventory = artifacts.build_artifact_inventory(repository_root=REPOSITORY_ROOT)
    usage = artifacts.build_flare_usage_audit()
    documents = (
        artifacts.upstream_source_manifest(),
        artifacts.artifact_manifest(inventory),
        artifacts.third_party_usage_manifest_document(usage),
        route.training_provenance(),
        route.paper_route_contract(),
        route.score_contract(),
        qualification.checkpoint_compatibility_document(
            qualification.build_compatibility_report(repository_root=REPOSITORY_ROOT)
        ),
        qualification.qualification_report_document(
            outcome,
            graph=route.resolve_transform_graph(),
            audit=route.public_code_route_audit(),
            model=qualification.run_route_model_qualification(),
            byte_audit=qualification.audit_tracked_bytes_against_flare_artifacts(
                REPOSITORY_ROOT
            ),
        ),
    )
    for document in documents:
        assert _forbidden_keys(document) == set()
