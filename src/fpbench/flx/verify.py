"""Re-derive and verify the committed Stage 8B chain, without a runtime.

The point of this module is that it needs nothing the qualification needed.
No torch, no checkpoint, no bundle, no network: it reads the published
documents, rebuilds every profile from the repository's own source, re-applies
the frozen gates to the published probe, and re-hashes the exact bytes.

That separation is deliberate.  Verification that could only run where the
experiment ran would be the experiment agreeing with itself.
"""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fpbench.core.flx_errors import Stage8BFinalizationError
from fpbench.core.flx_models import FlxOutcome
from fpbench.core.serialization import to_plain
from fpbench.flx import identity
from fpbench.flx.finalization import (
    build_stage8b_finalization,
    file_sha256,
    verify_stage8b_workspace_boundaries,
)
from fpbench.flx.integration import build_adapter_profile
from fpbench.flx.loading import load_published_evidence
from fpbench.flx.lock import load_runtime_lock
from fpbench.flx.preprocessing import build_preprocessing_profile
from fpbench.flx.qualification import build_qualification_report
from fpbench.flx.representation import build_representation_profile
from fpbench.flx.score import build_score_profile
from fpbench.storage.flx_store import Stage8BEvidenceStore

__all__ = ["Stage8BVerification", "verify_stage8b_evidence"]

_VERIFIER_AUTHORITY_PATHS = (
    "configs/flx",
    "src/fpbench/core/flx_errors.py",
    "src/fpbench/core/flx_models.py",
    "src/fpbench/flx",
    "src/fpbench/storage/flx_store.py",
)


@dataclass(frozen=True, slots=True)
class Stage8BVerification:
    outcome: FlxOutcome
    gate_count: int
    evidence_files_verified: int
    opens_stage_8c: bool


def _require_repository_input(
    repository_root: Path, supplied: Path, expected_relative: str, what: str
) -> Path:
    expected = repository_root / PurePosixPath(expected_relative)
    try:
        if Path(supplied).resolve(strict=True) != expected.resolve(strict=True):
            raise Stage8BFinalizationError(
                f"{what} must be the exact repository-owned Stage 8B path"
            )
    except OSError as exc:
        raise Stage8BFinalizationError(f"cannot resolve the repository-owned {what}: {exc}") from exc
    current = expected
    while current != repository_root:
        try:
            info = current.lstat()
        except OSError as exc:
            raise Stage8BFinalizationError(f"cannot inspect {what}: {exc}") from exc
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if current.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse):
            raise Stage8BFinalizationError(f"{what} and its ancestors may not be links")
        current = current.parent
    return expected


def _verify_verifier_source_commit(
    repository_root: Path, commit: str, *, require_git_provenance: bool
) -> None:
    def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ("git", "-C", str(repository_root), *arguments),
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Stage8BFinalizationError(
                f"cannot inspect the Stage 8B verifier commit with Git: {exc}"
            ) from exc

    worktree = run_git("rev-parse", "--show-toplevel")
    if worktree.returncode != 0:
        if require_git_provenance:
            raise Stage8BFinalizationError(
                "the committed Stage 8B workspace requires readable Git provenance"
            )
        return
    if run_git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise Stage8BFinalizationError(
            "verifier_source_commit is not a commit in this repository"
        )
    if run_git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        raise Stage8BFinalizationError(
            "verifier_source_commit is not an ancestor of the current source"
        )
    if run_git("diff", "--quiet", commit, "--", *_VERIFIER_AUTHORITY_PATHS).returncode != 0:
        raise Stage8BFinalizationError(
            "the active Stage 8B authority source differs from verifier_source_commit"
        )
    untracked = run_git(
        "status", "--porcelain", "--untracked-files=all", "--", *_VERIFIER_AUTHORITY_PATHS
    )
    if untracked.returncode != 0 or untracked.stdout.strip():
        raise Stage8BFinalizationError(
            "the active Stage 8B authority source tree is not clean"
        )


def verify_stage8b_evidence(
    *,
    repository_root: Path,
    lock_config: Path,
    policy_config: Path,
    require_git_provenance: bool = True,
) -> Stage8BVerification:
    repository_root = Path(repository_root)
    if require_git_provenance:
        lock_config = _require_repository_input(
            repository_root, Path(lock_config), "configs/flx/flx_runtime_lock_v1.txt", "runtime lock"
        )
        policy_config = _require_repository_input(
            repository_root,
            Path(policy_config),
            "configs/flx/stage8b_flx_runtime_policy_v1.yaml",
            "runtime policy",
        )
    store = Stage8BEvidenceStore(repository_root)
    published = load_published_evidence(
        store, policy_config=policy_config, require_finalization=True
    )
    finalization = published.finalization
    if finalization is None:
        raise Stage8BFinalizationError("the Stage 8B publication has no finalization")

    if require_git_provenance:
        verify_stage8b_workspace_boundaries(
            repository_root, span_end_commit=finalization.verifier_source_commit
        )
    _verify_verifier_source_commit(
        repository_root,
        finalization.verifier_source_commit,
        require_git_provenance=require_git_provenance,
    )

    # The three profiles are rebuilt from this repository's source and must
    # equal what was published: a profile that drifted would silently change
    # what every stored representation means.
    for label, rebuilt, stored in (
        ("preprocessing", build_preprocessing_profile(), published.preprocessing),
        ("representation", build_representation_profile(), published.representation),
        ("score", build_score_profile(), published.score),
        ("adapter", build_adapter_profile(), published.adapter),
    ):
        if to_plain(rebuilt) != to_plain(stored):
            raise Stage8BFinalizationError(
                f"the published {label} profile is not the one this source produces"
            )

    lock = load_runtime_lock(lock_config)
    if published.manifest.dependency_lock_sha256 != lock.sha256:
        raise Stage8BFinalizationError(
            "the runtime manifest names a different dependency lock than the committed one"
        )
    if published.binding.checkpoint_sha256 != identity.CHECKPOINT_SHA256:
        raise Stage8BFinalizationError("the published binding names another checkpoint")
    if published.binding.source_archive_sha256 != identity.SOURCE_ARCHIVE_SHA256:
        raise Stage8BFinalizationError("the published binding names another source archive")

    rederived_report = build_qualification_report(
        binding=published.binding,
        manifest=published.manifest,
        probe=published.probe,
        qualified_utc=published.report.qualified_utc,
    )
    if to_plain(rederived_report) != to_plain(published.report):
        raise Stage8BFinalizationError(
            "the qualification report is not the frozen gates applied to the published probe"
        )

    rederived_marker = build_stage8b_finalization(
        store=store,
        binding=published.binding,
        manifest=published.manifest,
        probe=published.probe,
        report=published.report,
        policy=published.policy,
        profile_fingerprints=published.profile_fingerprints,
        stage8a_finalization_fingerprint=published.stage8a_finalization_fingerprint,
        verifier_source_commit=finalization.verifier_source_commit,
        verifier_source_tree_clean=finalization.verifier_source_tree_clean,
        created_utc=finalization.created_utc,
        require_git_provenance=require_git_provenance,
    )
    if to_plain(rederived_marker) != to_plain(finalization):
        raise Stage8BFinalizationError(
            "the finalization is not the last-written authority over the exact evidence bytes"
        )
    for name, expected in finalization.evidence_content_hashes.items():
        if file_sha256(store.path(name)) != expected:
            raise Stage8BFinalizationError(f"{name}: exact bytes changed after finalization")

    return Stage8BVerification(
        outcome=published.report.outcome,
        gate_count=len(published.report.gates),
        evidence_files_verified=len(store.ALL_NAMES),
        opens_stage_8c=published.report.opens_stage_8c,
    )
