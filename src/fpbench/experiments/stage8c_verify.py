"""Re-derive and verify the committed Stage 8C chain, two different ways.

**Workspace verification** needs SD300, the prepared image set, the raw
ResultSet, the checkpoint and the runtime bundle, and it verifies the whole
experiment.  It lives in
:mod:`fpbench.experiments.flx_canonical500_full`.

**Evidence-only verification** is this module.  It needs none of those.  It reads
the seven published documents plus the marker, re-derives every fingerprint it
can from the repository's own source, re-hashes the exact bytes, and checks that
the relationships between the documents hold.

The separation is deliberate: verification that could only run where the
experiment ran would be the experiment agreeing with itself.  It is equally
deliberate that this module makes no claim the algorithm was executed.  A green
evidence-only run says the published documents are internally consistent and
byte-stable; it does not say CI ran 6,000 comparisons, and the CI workflow says
so out loud (spec section 29).
"""

from __future__ import annotations

import json
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.errors import ResearchPreflightError
from fpbench.core.serialization import read_json
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage8c_finalization import (
    Stage8CFinalization,
    alignment_report_content_hash,
    file_sha256,
    operational_summary_content_hash,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    stage_8c_finalization_fingerprint,
    verify_stage8c_workspace_boundaries,
)

__all__ = [
    "Stage8CVerification",
    "read_stage8c_finalization",
    "verify_stage8c_evidence",
]

#: The source Stage 8C's published evidence is an authority over. A verifier
#: that ran against edited authority code would be checking a different stage.
_VERIFIER_AUTHORITY_PATHS = (
    "configs/algorithms/flx_deepprint_texminu_512_without_localization_v1.yaml",
    "configs/execution/flx_canonical500_sequential_no_retry_v1.yaml",
    "configs/experiments/flx_canonical500_full_v1.yaml",
    "src/fpbench/experiments/flx_adapter.py",
    "src/fpbench/experiments/flx_canonical500_full.py",
    "src/fpbench/experiments/flx_failure_mapping.py",
    "src/fpbench/experiments/flx_research.py",
    "src/fpbench/experiments/flx_validation.py",
    "src/fpbench/experiments/stage8b_binding.py",
    "src/fpbench/experiments/stage8c_finalization.py",
    "src/fpbench/experiments/stage8c_verify.py",
    "src/fpbench/experiments/stage8c_identity.py",
)


@dataclass(frozen=True, slots=True)
class Stage8CVerification:
    """What an evidence-only pass established, and what it deliberately did not."""

    outcome: str
    run_id: str
    evidence_files_verified: int
    stored_count: int
    success_count: int
    algorithmic_failure_count: int
    logical_extraction_call_count: int
    physical_forward_row_count: int
    opens_stage_8d: bool

    #: Always false. Evidence-only verification does not execute the algorithm
    #: and never claims to (spec section 29).
    algorithm_executed: bool = False


def read_stage8c_finalization(
    *, repository_root: Path = REPOSITORY_ROOT
) -> Stage8CFinalization:
    path = (
        Path(repository_root)
        / frozen.EVIDENCE_DIRECTORY
        / frozen.STAGE_8C_FINALIZATION_NAME
    )
    if not path.is_file():
        raise ResearchPreflightError(f"Stage 8C finalization not found: {path}")
    try:
        return Stage8CFinalization(**read_json(path))
    except (KeyError, TypeError, ValueError) as exc:
        raise ResearchPreflightError(
            f"{path.name}: unreadable Stage 8C finalization ({exc})"
        ) from exc


def verify_stage8c_evidence(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    require_git_provenance: bool = True,
) -> Stage8CVerification:
    """Verify the published Stage 8C chain with no workspace and no runtime."""
    repository_root = Path(repository_root)
    directory = repository_root / frozen.EVIDENCE_DIRECTORY

    names = published_evidence_names(repository_root)
    run_file = require_expected_evidence_files(names)
    _require_strict_json(directory, names)
    require_no_forbidden_published_data(repository_root)

    marker = read_stage8c_finalization(repository_root=repository_root)

    if require_git_provenance:
        verify_stage8c_workspace_boundaries(
            repository_root, span_end_commit=marker.verifier_source_commit
        )
    _verify_verifier_source_commit(
        repository_root,
        marker.verifier_source_commit,
        require_git_provenance=require_git_provenance,
    )

    # The marker fingerprints to what it carries. An edited count that was
    # re-fingerprinted consistently still fails the checks below, because those
    # compare it with the documents it describes.
    if stage_8c_finalization_fingerprint(marker) != (
        marker.stage_8c_finalization_fingerprint
    ):
        raise ResearchPreflightError(
            "the Stage 8C finalization does not fingerprint to what it carries"
        )

    _require_frozen_identities(marker)
    _require_profiles_match_this_source(marker)

    documents = {name: read_json(directory / name) for name in names if name.endswith(".json")}
    _require_document_relationships(marker, documents, run_file=run_file)

    for name, expected in marker.evidence_content_hashes.items():
        path = directory / name
        if not path.is_file():
            raise ResearchPreflightError(
                f"the finalization names {name}, which is not published"
            )
        if file_sha256(path) != expected:
            raise ResearchPreflightError(
                f"{name}: exact bytes changed after finalization"
            )
    covered = set(marker.evidence_content_hashes)
    uncovered = sorted(set(names) - covered - {frozen.STAGE_8C_FINALIZATION_NAME})
    if uncovered:
        raise ResearchPreflightError(
            f"published files no content hash covers: {uncovered}"
        )

    return Stage8CVerification(
        outcome=marker.outcome,
        run_id=marker.run_id,
        evidence_files_verified=len(names),
        stored_count=marker.stored_count,
        success_count=marker.success_count,
        algorithmic_failure_count=marker.algorithmic_failure_count,
        logical_extraction_call_count=marker.logical_extraction_call_count,
        physical_forward_row_count=marker.physical_forward_row_count,
        opens_stage_8d=marker.opens_stage_8d,
    )


# ----------------------------------------------------------------- internals


def _require_strict_json(directory: Path, names: tuple[str, ...]) -> None:
    """Every published JSON parses strictly and holds no duplicate key."""
    for name in names:
        if not name.endswith(".json"):
            continue
        path = directory / name
        text = path.read_text(encoding="utf-8")
        try:
            json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except ValueError as exc:
            raise ResearchPreflightError(f"{name}: {exc}") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r} in published evidence")
        seen[key] = value
    return seen


def _require_frozen_identities(marker: Stage8CFinalization) -> None:
    """The marker names the stage this source is, not another one."""
    for label, actual, expected in (
        ("algorithm_id", marker.algorithm_id, frozen.ALGORITHM_ID),
        ("integration_id", marker.integration_id, frozen.INTEGRATION_ID),
        (
            "stage8b_finalization_fingerprint",
            marker.stage8b_finalization_fingerprint,
            frozen.STAGE8B_FINALIZATION_FINGERPRINT,
        ),
        ("stage8b_outcome", marker.stage8b_outcome, frozen.STAGE8B_OUTCOME),
        ("checkpoint_sha256", marker.checkpoint_sha256, frozen.CHECKPOINT_SHA256),
        (
            "source_archive_sha256",
            marker.source_archive_sha256,
            frozen.SOURCE_ARCHIVE_SHA256,
        ),
        ("reference_run_id", marker.reference_run_id, frozen.REFERENCE_RUN_ID),
        ("reference_plan_id", marker.reference_plan_id, frozen.REFERENCE_PLAN_ID),
        (
            "reference_result_set_id",
            marker.reference_result_set_id,
            frozen.REFERENCE_RESULT_SET_ID,
        ),
        (
            "pair_manifest_hash",
            marker.pair_manifest_hash,
            frozen.REFERENCE_PAIR_MANIFEST_HASH,
        ),
        ("preparation_set_id", marker.preparation_set_id, frozen.PREPARATION_SET_ID),
        (
            "preparation_set_fingerprint",
            marker.preparation_set_fingerprint,
            frozen.PREPARATION_SET_FINGERPRINT,
        ),
        (
            "transform_profile_fingerprint",
            marker.transform_profile_fingerprint,
            frozen.TRANSFORM_PROFILE_FINGERPRINT,
        ),
        (
            "transform_runtime_fingerprint",
            marker.transform_runtime_fingerprint,
            frozen.TRANSFORM_RUNTIME_FINGERPRINT,
        ),
    ):
        if actual != expected:
            raise ResearchPreflightError(
                f"the published {label} is {str(actual)[:16]}..., but this source "
                f"is Stage 8C against {str(expected)[:16]}..."
            )
    if marker.planned_count != frozen.EXPECTED_JOBS:
        raise ResearchPreflightError(
            f"the publication plans {marker.planned_count} comparisons, not "
            f"{frozen.EXPECTED_JOBS}"
        )
    if marker.logical_extraction_call_count != frozen.PLANNED_LOGICAL_EXTRACTIONS:
        raise ResearchPreflightError(
            f"the publication records {marker.logical_extraction_call_count} "
            f"logical extractions, not {frozen.PLANNED_LOGICAL_EXTRACTIONS}"
        )
    if marker.physical_forward_row_count != frozen.PLANNED_PHYSICAL_FORWARD_ROWS:
        raise ResearchPreflightError(
            f"the publication records {marker.physical_forward_row_count} physical "
            f"forward rows, not {frozen.PLANNED_PHYSICAL_FORWARD_ROWS}"
        )


def _require_profiles_match_this_source(marker: Stage8CFinalization) -> None:
    """The four flx profiles are the ones this repository's source produces."""
    from fpbench.flx.integration import build_adapter_profile
    from fpbench.flx.preprocessing import build_preprocessing_profile
    from fpbench.flx.representation import build_representation_profile
    from fpbench.flx.score import build_score_profile

    for label, rebuilt, published in (
        (
            "preprocessing",
            build_preprocessing_profile().fingerprint,
            marker.preprocessing_profile_fingerprint,
        ),
        (
            "representation",
            build_representation_profile().fingerprint,
            marker.representation_profile_fingerprint,
        ),
        ("score", build_score_profile().fingerprint, marker.score_profile_fingerprint),
        (
            "adapter",
            build_adapter_profile().fingerprint,
            marker.adapter_profile_fingerprint,
        ),
    ):
        if rebuilt != published:
            raise ResearchPreflightError(
                f"the published {label} profile is not the one this source produces"
            )


def _require_document_relationships(
    marker: Stage8CFinalization,
    documents: Mapping[str, Any],
    *,
    run_file: str,
) -> None:
    """Every document names the same run, and the marker names all of them."""
    alignment = documents["alignment-report.json"]
    summary = documents["operational-summary.json"]
    validation = documents["algorithm-validation.json"]
    provenance = documents["runtime-provenance.json"]
    run_document = documents[run_file]

    if alignment_report_content_hash(alignment) != marker.alignment_report_content_hash:
        raise ResearchPreflightError(
            "the published alignment report is not the one the marker binds"
        )
    if operational_summary_content_hash(summary) != (
        marker.operational_summary_content_hash
    ):
        raise ResearchPreflightError(
            "the published operational summary is not the one the marker binds"
        )
    if alignment.get("alignment_fingerprint") != marker.alignment_fingerprint:
        raise ResearchPreflightError(
            "the published alignment report carries another alignment fingerprint"
        )
    if validation.get("validation_fingerprint") != (
        marker.algorithm_validation_fingerprint
    ):
        raise ResearchPreflightError(
            "the published validation report is not the one the marker binds"
        )

    for label, value in (
        ("run definition", run_document.get("run_id")),
        ("runtime provenance", provenance.get("run_id")),
        ("validation report", validation.get("run_id")),
        ("alignment report", alignment.get("candidate_run_id")),
    ):
        if value != marker.run_id:
            raise ResearchPreflightError(
                f"the published {label} names run {value!r}, not {marker.run_id!r}"
            )
    if run_document.get("run_fingerprint") != marker.run_fingerprint:
        raise ResearchPreflightError(
            "the published run definition is not the run the marker binds"
        )

    # docs/adr/0076: the numbers a reader may see, and their arithmetic.
    for label, value, expected in (
        ("stored_count", validation.get("total_results"), marker.stored_count),
        ("success_count", validation.get("successful_results"), marker.success_count),
        (
            "algorithmic_failure_count",
            validation.get("algorithmic_failures"),
            marker.algorithmic_failure_count,
        ),
        (
            "blocking_failure_count",
            validation.get("blocking_failures"),
            marker.blocking_failure_count,
        ),
        (
            "logical_extraction_call_count",
            validation.get("logical_extraction_calls"),
            marker.logical_extraction_call_count,
        ),
        (
            "physical_forward_row_count",
            validation.get("physical_forward_rows"),
            marker.physical_forward_row_count,
        ),
    ):
        if value != expected:
            raise ResearchPreflightError(
                f"the published validation report says {label}={value}, and the "
                f"marker says {expected}"
            )

    operations = summary.get("algorithm_operations") or {}
    measured = operations.get("measured") or {}
    if measured.get("logical_extraction_calls") != marker.logical_extraction_call_count:
        raise ResearchPreflightError(
            "the operational summary and the marker disagree about how many "
            "logical extractions were performed"
        )
    if measured.get("physical_forward_rows") != marker.physical_forward_row_count:
        raise ResearchPreflightError(
            "the operational summary and the marker disagree about how many "
            "physical forward rows were performed"
        )
    if measured.get("physical_forward_rows") != (
        2 * measured.get("logical_extraction_calls", 0)
    ):
        raise ResearchPreflightError(
            "the operational summary conflates logical extractions with physical "
            "forward rows (docs/adr/0075)"
        )

    if provenance.get("artifacts", {}).get("checkpoint_published") is not False:
        raise ResearchPreflightError(
            "the published provenance must state that the checkpoint was not "
            "published (docs/adr/0068)"
        )


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
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ResearchPreflightError(
                f"cannot inspect the Stage 8C verifier commit with Git: {exc}"
            ) from exc

    worktree = run_git("rev-parse", "--show-toplevel")
    if worktree.returncode != 0:
        if require_git_provenance:
            raise ResearchPreflightError(
                "the committed Stage 8C workspace requires readable Git provenance"
            )
        return
    if run_git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise ResearchPreflightError(
            "verifier_source_commit is not a commit in this repository"
        )
    if run_git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        raise ResearchPreflightError(
            "verifier_source_commit is not an ancestor of the current source"
        )
    if run_git(
        "diff", "--quiet", commit, "--", *_VERIFIER_AUTHORITY_PATHS
    ).returncode != 0:
        raise ResearchPreflightError(
            "the active Stage 8C authority source differs from verifier_source_commit"
        )
    untracked = run_git(
        "status", "--porcelain", "--untracked-files=all", "--", *_VERIFIER_AUTHORITY_PATHS
    )
    if untracked.returncode != 0 or untracked.stdout.strip():
        raise ResearchPreflightError(
            "the active Stage 8C authority source tree is not clean"
        )


def _require_no_links(directory: Path) -> None:  # pragma: no cover - used by tests
    for path in sorted(Path(directory).iterdir()):
        info = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse):
            raise ResearchPreflightError(
                f"published evidence may not be a link: "
                f"{PurePosixPath(path.name)}"
            )
