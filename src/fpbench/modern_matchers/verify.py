"""Re-derive and verify the complete committed Stage 8A evidence chain."""

from __future__ import annotations

import json
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.errors import Stage8AFinalizationError
from fpbench.core.modern_matcher_models import Stage8AOutcome
from fpbench.core.serialization import to_plain
from fpbench.modern_matchers.acquisition import load_acquisition_manifests
from fpbench.modern_matchers.artifacts import ModernMatcherArtifactStore
from fpbench.modern_matchers.assessments import build_frozen_qualification_reports
from fpbench.modern_matchers.finalization import (
    build_stage8a_finalization,
    file_sha256,
    verify_stage8a_workspace_boundaries,
)
from fpbench.modern_matchers.loading import (
    finalization_from_plain,
    qualification_report_from_plain,
    registry_from_plain,
    selection_decision_from_plain,
)
from fpbench.modern_matchers.policy import load_selection_policy
from fpbench.modern_matchers.registry import load_candidate_registry
from fpbench.modern_matchers.selection import select_modern_matcher
from fpbench.storage.modern_matcher_store import Stage8AEvidenceStore

__all__ = ["Stage8AVerification", "ensure_publishable", "verify_stage8a_evidence"]

_ABSOLUTE_PATH = re.compile(
    r"(?:\b[A-Za-z]:[\\/]|\\\\|(?<!:)//[^\s/]|"
    r"(?<![A-Za-z0-9+.-])file://|"
    r"(?<![:/A-Za-z0-9._-])/(?!/)(?=$|[^\s/]))",
    re.IGNORECASE,
)
_FORBIDDEN_FIELDS = frozenset(
    {
        "weights_bytes",
        "checkpoint_bytes",
        "source_code_body",
        "proprietary_source",
        "license_key",
        "sample_biometric_image",
        "image_bytes",
        "embedding_values",
        "representation_values",
        "raw_scores",
        "scores",
    }
)
_VERIFIER_SOURCE_PATH = "src/fpbench/modern_matchers/verify.py"
_VERIFIER_AUTHORITY_PATHS = (
    "src/fpbench/core/errors.py",
    "src/fpbench/core/identifiers.py",
    "src/fpbench/core/modern_matcher_models.py",
    "src/fpbench/core/serialization.py",
    "src/fpbench/modern_matchers",
    "src/fpbench/storage/__init__.py",
    "src/fpbench/storage/modern_matcher_store.py",
)


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def _read_unique_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, ValueError) as exc:
        raise Stage8AFinalizationError(f"{path}: unreadable Stage 8A evidence ({exc})") from exc
    if not isinstance(value, Mapping):
        raise Stage8AFinalizationError(f"{path}: Stage 8A evidence must be a JSON object")
    return dict(value)


def ensure_publishable(value: Any, *, location: str = "document") -> None:
    """Refuse private payloads and machine-local paths in committed evidence."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_FIELDS:
                raise Stage8AFinalizationError(f"{location}.{key} is forbidden in public Stage 8A evidence")
            ensure_publishable(str(key), location=f"{location}.<key>")
            ensure_publishable(item, location=f"{location}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_publishable(item, location=f"{location}[{index}]")
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise Stage8AFinalizationError(f"{location} contains binary payload bytes")
    if isinstance(value, str):
        if _ABSOLUTE_PATH.search(value.strip()):
            raise Stage8AFinalizationError(
                f"{location} contains a machine-local absolute path"
            )
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise Stage8AFinalizationError(
            f"{location} contains unsupported public value {type(value).__name__}"
        )


def _load_model(path: Path, loader, what: str):
    payload = _read_unique_json(path)
    ensure_publishable(payload, location=what)
    try:
        return payload, loader(payload)
    except (TypeError, ValueError, KeyError) as exc:
        raise Stage8AFinalizationError(
            f"{path}: invalid {what} ({exc})"
        ) from exc


def _require_repository_input(
    repository_root: Path,
    supplied: Path,
    expected_relative: str,
    what: str,
) -> Path:
    """Reject alternate and linked inputs before opening qualification data."""
    expected = repository_root / PurePosixPath(expected_relative)
    supplied = Path(supplied)
    try:
        expected_resolved = expected.resolve(strict=True)
        supplied_resolved = supplied.resolve(strict=True)
    except OSError as exc:
        raise Stage8AFinalizationError(
            f"cannot resolve the repository-owned {what}: {exc}"
        ) from exc
    if supplied_resolved != expected_resolved:
        raise Stage8AFinalizationError(
            f"{what} must be the exact repository-owned Stage 8A path"
        )
    current = expected
    while current != repository_root:
        try:
            info = current.lstat()
        except OSError as exc:
            raise Stage8AFinalizationError(
                f"cannot inspect repository-owned {what}: {exc}"
            ) from exc
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if current.is_symlink() or bool(
            getattr(info, "st_file_attributes", 0) & reparse_flag
        ):
            raise Stage8AFinalizationError(
                f"{what} and its repository ancestors may not be links"
            )
        current = current.parent
    return expected


def _reject_forbidden_artifact_root(
    repository_root: Path, artifact_root: Path | None
) -> None:
    if artifact_root is None:
        return
    candidate = Path(artifact_root)
    try:
        resolved = candidate.resolve(strict=False)
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise Stage8AFinalizationError(
            f"cannot resolve Stage 8A artifact root: {exc}"
        ) from exc
    forbidden_workspace = (
        root / "workspace" / "prepared",
        root / "workspace" / "results",
        root / "workspace" / "derivations",
    )
    evidence_root = root / "evidence"
    forbidden_evidence = False
    try:
        evidence_relative = resolved.relative_to(evidence_root)
    except ValueError:
        pass
    else:
        forbidden_evidence = bool(
            evidence_relative.parts
            and evidence_relative.parts[0].lower().startswith(
                ("sourceafis-", "nbis-")
            )
        )
    if forbidden_evidence or any(
        resolved == path or resolved.is_relative_to(path)
        for path in forbidden_workspace
    ):
        raise Stage8AFinalizationError(
            "Stage 8A artifact root may not enter forbidden prior-stage inputs"
        )


def _verify_verifier_source_commit(
    repository_root: Path,
    commit: str,
    *,
    require_git_provenance: bool,
) -> None:
    """Bind a repository-backed publication to a real committed verifier.

    Synthetic unit-test evidence trees are intentionally portable and have no
    Git metadata.  When the publication lives in a Git worktree, however, the
    provenance claim is mandatory: the named commit must exist in this
    repository, must be in the current history, and must contain this verifier.
    """

    def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ("git", "-C", str(repository_root), *arguments),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Stage8AFinalizationError(
                f"cannot inspect verifier source commit with Git: {exc}"
            ) from exc

    worktree = run_git("rev-parse", "--show-toplevel")
    if worktree.returncode != 0:
        if require_git_provenance:
            raise Stage8AFinalizationError(
                "the committed Stage 8A workspace requires readable Git provenance"
            )
        return
    try:
        actual_root = Path(worktree.stdout.strip()).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise Stage8AFinalizationError(
            f"cannot resolve Stage 8A repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage8AFinalizationError(
            "Stage 8A repository_root must be the Git worktree root"
        )
    commit_object = run_git("cat-file", "-e", f"{commit}^{{commit}}")
    if commit_object.returncode != 0:
        raise Stage8AFinalizationError(
            "verifier_source_commit is not a commit in this repository"
        )
    ancestor = run_git("merge-base", "--is-ancestor", commit, "HEAD")
    if ancestor.returncode != 0:
        raise Stage8AFinalizationError(
            "verifier_source_commit is not an ancestor of the current source"
        )
    verifier_blob = run_git("cat-file", "-e", f"{commit}:{_VERIFIER_SOURCE_PATH}")
    if verifier_blob.returncode != 0:
        raise Stage8AFinalizationError(
            "verifier_source_commit does not contain the Stage 8A verifier"
        )
    unchanged = run_git(
        "diff",
        "--quiet",
        commit,
        "--",
        *_VERIFIER_AUTHORITY_PATHS,
    )
    if unchanged.returncode != 0:
        raise Stage8AFinalizationError(
            "the active Stage 8A authority source differs from "
            "verifier_source_commit"
        )
    untracked = run_git(
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        *_VERIFIER_AUTHORITY_PATHS,
    )
    if untracked.returncode != 0 or untracked.stdout.strip():
        raise Stage8AFinalizationError(
            "the active Stage 8A authority source tree is not clean"
        )


@dataclass(frozen=True, slots=True)
class Stage8AVerification:
    outcome: Stage8AOutcome
    candidate_count: int
    required_artifacts_verified: int

    @property
    def is_valid(self) -> bool:
        return True


def verify_stage8a_evidence(
    *,
    repository_root: Path,
    registry_config: Path,
    policy_config: Path,
    acquisition_manifest_dir: Path | None = None,
    artifact_root: Path | None = None,
    require_git_provenance: bool = True,
) -> Stage8AVerification:
    """Verify only registry/policy/Stage8A evidence and optionally required assets."""
    if type(require_git_provenance) is not bool:
        raise Stage8AFinalizationError(
            "require_git_provenance must be a boolean"
        )
    repository_root = Path(repository_root)
    if require_git_provenance:
        verify_stage8a_workspace_boundaries(repository_root)
        registry_config = _require_repository_input(
            repository_root,
            Path(registry_config),
            "configs/modern-matchers/stage8a_candidates_v1.yaml",
            "candidate registry config",
        )
        policy_config = _require_repository_input(
            repository_root,
            Path(policy_config),
            "configs/modern-matchers/stage8a_selection_policy_v1.yaml",
            "selection policy config",
        )
        acquisition_manifest_dir = _require_repository_input(
            repository_root,
            (
                Path(acquisition_manifest_dir)
                if acquisition_manifest_dir is not None
                else repository_root
                / "integrations"
                / "modern-matchers"
                / "manifests"
            ),
            "integrations/modern-matchers/manifests",
            "acquisition manifest directory",
        )
        _reject_forbidden_artifact_root(repository_root, artifact_root)
    store = Stage8AEvidenceStore(repository_root)
    if require_git_provenance:
        _require_repository_input(
            repository_root,
            store.evidence_dir,
            "evidence/stage8a-modern-matcher-selection",
            "Stage 8A evidence directory",
        )
    configured_registry = load_candidate_registry(registry_config)
    candidate_ids = tuple(
        candidate.candidate_id for candidate in configured_registry.candidates
    )
    expected_evidence_names = {
        store.README_NAME,
        store.REGISTRY_NAME,
        store.SELECTION_NAME,
        store.FINALIZATION_NAME,
        *(f"qualification-{candidate_id}.json" for candidate_id in candidate_ids),
    }
    if not store.evidence_dir.is_dir():
        raise Stage8AFinalizationError(
            f"Stage 8A evidence directory not found: {store.evidence_dir}"
        )
    actual_evidence_names = {path.name for path in store.evidence_dir.iterdir()}
    if actual_evidence_names != expected_evidence_names:
        raise Stage8AFinalizationError(
            "Stage 8A evidence tree must contain exactly the frozen publication; "
            f"missing={sorted(expected_evidence_names - actual_evidence_names)}, "
            f"extra={sorted(actual_evidence_names - expected_evidence_names)}"
        )
    linked = [path.name for path in store.evidence_dir.iterdir() if path.is_symlink()]
    if linked:
        raise Stage8AFinalizationError(
            f"Stage 8A evidence files may not be links: {sorted(linked)}"
        )

    acquisition_directory = (
        Path(acquisition_manifest_dir)
        if acquisition_manifest_dir is not None
        else repository_root / "integrations" / "modern-matchers" / "manifests"
    )
    manifests = load_acquisition_manifests(
        acquisition_directory,
        registry=configured_registry,
    )
    for manifest in manifests:
        ensure_publishable(
            to_plain(manifest), location=f"acquisition.{manifest.candidate_id}"
        )
    evidence_registry_payload, evidence_registry = _load_model(
        store.registry_path, registry_from_plain, "candidate_registry"
    )
    if to_plain(evidence_registry) != to_plain(configured_registry):
        raise Stage8AFinalizationError("candidate-registry.json is not the frozen registry config")
    policy = load_selection_policy(policy_config)

    reports = []
    for candidate in configured_registry.candidates:
        payload, report = _load_model(
            store.qualification_path(candidate.candidate_id),
            qualification_report_from_plain,
            f"qualification.{candidate.candidate_id}",
        )
        if report.candidate_id != candidate.candidate_id:
            raise Stage8AFinalizationError("qualification filename and candidate id disagree")
        reports.append(report)

    rederived_reports = build_frozen_qualification_reports(
        registry=configured_registry,
        manifests=manifests,
    )
    expected_reports = {report.candidate_id: report for report in rederived_reports}
    for report in reports:
        if to_plain(report) != to_plain(expected_reports[report.candidate_id]):
            raise Stage8AFinalizationError(
                f"{report.candidate_id}: qualification report is not the frozen "
                "static inspection applied to its acquisition manifest"
            )

    decision_payload, decision = _load_model(
        store.selection_path, selection_decision_from_plain, "selection_decision"
    )
    rederived = select_modern_matcher(
        registry=configured_registry,
        reports=reports,
        policy=policy,
        verifier_source_commit=decision.verifier_source_commit,
        decided_utc=decision.decided_utc,
    )
    if rederived.fingerprint != decision.fingerprint or to_plain(rederived) != to_plain(decision):
        raise Stage8AFinalizationError("selection decision is not the fixed policy applied to the qualification reports")

    finalization_payload, finalization = _load_model(
        store.finalization_path, finalization_from_plain, "stage8a_finalization"
    )
    try:
        readme_text = store.readme_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Stage8AFinalizationError(
            f"{store.readme_path}: unreadable Stage 8A README ({exc})"
        ) from exc
    ensure_publishable(readme_text, location="stage8a_readme")
    if finalization.registry_fingerprint != configured_registry.fingerprint:
        raise Stage8AFinalizationError("finalization names another registry")
    if finalization.selection_decision_fingerprint != decision.fingerprint:
        raise Stage8AFinalizationError("finalization names another selection decision")
    if finalization.verifier_source_commit != decision.verifier_source_commit:
        raise Stage8AFinalizationError(
            "selection and finalization name different verifier source commits"
        )
    _verify_verifier_source_commit(
        repository_root,
        finalization.verifier_source_commit,
        require_git_provenance=require_git_provenance,
    )
    if finalization.selection_policy_fingerprint != policy.fingerprint:
        raise Stage8AFinalizationError("finalization names another selection policy")
    if finalization.outcome is not decision.outcome:
        raise Stage8AFinalizationError("finalization outcome disagrees with selection")
    if finalization.registry_content_hash != file_sha256(store.registry_path):
        raise Stage8AFinalizationError("candidate registry exact bytes changed after finalization")
    if finalization.selection_decision_content_hash != file_sha256(store.selection_path):
        raise Stage8AFinalizationError("selection decision exact bytes changed after finalization")
    if finalization.readme_content_hash != file_sha256(store.readme_path):
        raise Stage8AFinalizationError("Stage 8A README exact bytes changed after finalization")
    report_map = {report.candidate_id: report for report in reports}
    for candidate_id, expected in finalization.qualification_fingerprints.items():
        if report_map[candidate_id].fingerprint != expected:
            raise Stage8AFinalizationError(f"{candidate_id}: qualification fingerprint changed")
        if file_sha256(store.qualification_path(candidate_id)) != finalization.qualification_content_hashes[candidate_id]:
            raise Stage8AFinalizationError(f"{candidate_id}: qualification exact bytes changed")

    rederived_finalization = build_stage8a_finalization(
        store=store,
        registry=configured_registry,
        reports=reports,
        decision=decision,
        policy=policy,
        verifier_source_commit=finalization.verifier_source_commit,
        verifier_source_tree_clean=finalization.verifier_source_tree_clean,
        created_utc=finalization.created_utc,
        require_git_provenance=require_git_provenance,
    )
    if to_plain(rederived_finalization) != to_plain(finalization):
        raise Stage8AFinalizationError(
            "Stage 8A finalization is not the last-written authority over the exact evidence bytes"
        )

    required = dict(finalization.required_local_artifact_fingerprints)
    if required and artifact_root is None:
        raise Stage8AFinalizationError(
            "this finalized outcome requires local candidate artefacts; set FPBENCH_STAGE8A_ARTIFACT_ROOT"
        )
    verified = 0
    if required:
        artifact_store = ModernMatcherArtifactStore(Path(artifact_root))
        for candidate_id, expected_fingerprint in required.items():
            report = report_map[candidate_id]
            if report.artifact_manifest.fingerprint != expected_fingerprint:
                raise Stage8AFinalizationError(f"{candidate_id}: required artefact fingerprint changed")
            artifact_store.verify_manifest(report.artifact_manifest)
            verified += 1
    return Stage8AVerification(
        outcome=decision.outcome,
        candidate_count=len(reports),
        required_artifacts_verified=verified,
    )
