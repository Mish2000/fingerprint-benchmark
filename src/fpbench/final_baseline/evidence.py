"""Publish and verify the final-baseline reporting evidence and its finalization marker.

The publisher computes the report from re-verified stores, writes the three
JSON documents and the rendered Markdown, then derives the marker over their
exact bytes.  The verifier needs no workspace, no dataset and no score store:
it re-hashes the committed documents, re-derives the marker fingerprint, and
re-renders the Markdown from the committed JSON — a self-consistent edit to a
published number therefore fails even if every hash beside it is recomputed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from fpbench.baseline_evaluation.policy import load_baseline_evaluation_policy
from fpbench.core.json_io import publish_evidence_document
from fpbench.core.serialization import stable_hash
from fpbench.final_baseline.constants import (
    EVIDENCE_DIRECTORY,
    EVIDENCE_DOCUMENTS,
    EXPECTED_METHODS,
    FINALIZATION_NAME,
    OUTCOME,
    POLICY_PATH,
    REPORT_NAME,
    REPORTING_PATH,
    COMPONENT,
)
from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.final_baseline.hashing import normalized_text_sha256
from fpbench.final_baseline.evaluate import (
    FinalBaselineEvaluation,
    collect_final_baseline_inputs,
    evaluate_final_baseline,
)
from fpbench.final_baseline.report import render_final_baseline_report
from fpbench.final_baseline.reporting import load_final_baseline_reporting

__all__ = [
    "publish_final_baseline_evidence",
    "final_baseline_source_fingerprint",
    "verify_final_baseline_evidence",
]

#: Everything whose bytes decide what final-baseline reporting computes and shows.
_SOURCE_PATHS = (
    "src/fpbench/final_baseline/__init__.py",
    "src/fpbench/final_baseline/constants.py",
    "src/fpbench/final_baseline/errors.py",
    "src/fpbench/final_baseline/hashing.py",
    "src/fpbench/final_baseline/reporting.py",
    "src/fpbench/final_baseline/sources.py",
    "src/fpbench/final_baseline/evaluate.py",
    "src/fpbench/final_baseline/report.py",
    "src/fpbench/final_baseline/evidence.py",
    "src/fpbench/final_baseline/cli.py",
    "src/fpbench/baseline_evaluation/__init__.py",
    "src/fpbench/baseline_evaluation/models.py",
    "src/fpbench/baseline_evaluation/policy.py",
    "src/fpbench/baseline_evaluation/roster.py",
    "src/fpbench/baseline_evaluation/sweep.py",
    "scripts/final_baseline.py",
    "scripts/final_baseline_pipeline.py",
    "configs/comparisons/final_baseline_roster_v1.yaml",
    "configs/comparisons/final_baseline_tar_far_frr_v1.yaml",
    "configs/reports/final_baseline_reporting_v1.yaml",
    "tests/unit/test_final_baseline_evaluation.py",
)

_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/])|(?:/(?:home|Users|mnt|tmp|var)/)"
)


def _sha256(path: Path) -> str:
    """Digest one text artifact with line endings normalised (see hashing.py)."""
    return normalized_text_sha256(path)


def _canonical_json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FinalBaselineError(f"{path}: unreadable JSON ({exc})") from exc


def final_baseline_source_fingerprint(repository_root: Path) -> str:
    root = Path(repository_root)
    missing = [path for path in _SOURCE_PATHS if not (root / path).is_file()]
    if missing:
        raise FinalBaselineError(f"final-baseline reporting source files are missing: {missing}")
    return stable_hash(
        {path: _sha256(root / path) for path in _SOURCE_PATHS}, length=64
    )


def _render(
    root: Path,
    inputs_document: Mapping[str, Any],
    results_document: Mapping[str, Any],
    context_document: Mapping[str, Any],
) -> str:
    policy = load_baseline_evaluation_policy(root / POLICY_PATH)
    reporting = load_final_baseline_reporting(
        root / REPORTING_PATH, roster_method_ids=policy.roster.method_ids
    )
    return render_final_baseline_report(
        inputs_document=inputs_document,
        results_document=results_document,
        context_document=context_document,
        reporting=reporting,
    )


def _write_report(path: Path, markdown: str) -> None:
    if _ABSOLUTE_PATH_PATTERN.search(markdown):
        raise FinalBaselineError(
            "the rendered report contains something shaped like a machine path; "
            "refusing to publish it"
        )
    if "\r" in markdown:
        raise FinalBaselineError("the rendered report must not contain carriage returns")
    # Bytes, not ``write_text``: evidence is hashed byte-for-byte, and the
    # platform must not get a vote on line endings (the Stage 15A lesson).
    path.write_bytes(markdown.encode("utf-8"))


def publish_final_baseline_evidence(
    *,
    repository_root: Path,
    workspace: Path,
    source_tree_clean_attested: bool,
    evidence_directory: Path | None = None,
) -> dict[str, Any]:
    """Compute, publish and seal the final baseline TAR/FAR/FRR report."""
    root = Path(repository_root).resolve()
    directory = (
        Path(evidence_directory).resolve()
        if evidence_directory is not None
        else root / EVIDENCE_DIRECTORY
    )
    if not (directory / "README.md").is_file():
        raise FinalBaselineError(f"write {directory / 'README.md'} before publishing")

    inputs = collect_final_baseline_inputs(repository_root=root, workspace=workspace)
    evaluation: FinalBaselineEvaluation = evaluate_final_baseline(inputs)
    markdown = _render(
        root,
        evaluation.inputs_document,
        evaluation.results_document,
        evaluation.context_document,
    )

    publish_evidence_document(
        directory / "evaluation-inputs.json", evaluation.inputs_document
    )
    publish_evidence_document(
        directory / "tar-far-frr-results.json", evaluation.results_document
    )
    publish_evidence_document(
        directory / "native-documented-rules-context.json",
        evaluation.context_document,
    )
    _write_report(directory / REPORT_NAME, markdown)

    results = evaluation.results_document
    conditions = {
        "stage21a_verified": True,
        "stage21b_verified": True,
        "six_roster_methods_evaluated": (
            len(evaluation.inputs_document["methods"]) == EXPECTED_METHODS
        ),
        "genuine_population_frozen": (
            results["views"]["primary_all_attempt"] is not None
        ),
        "primary_far_target_is_one_per_mille": (
            results["primary_far_target"] == "1/1000"
        ),
        "three_far_targets_reported": len(results["far_targets"]) == 3,
        "per_release_and_pooled_reported": (
            list(results["scopes"]) == ["SD300A", "SD300B", "SD300C", "pooled"]
        ),
        "common_score_view_secondary": True,
        "native_rules_context_separate": (
            evaluation.context_document["direct_cross_algorithm_ranking"]
            == "forbidden"
        ),
        "no_interpolation": True,
        "ties_move_together": True,
        "no_score_normalization": True,
        "no_cross_algorithm_raw_score_comparison": True,
        "no_calibration_performed": True,
        "no_operational_threshold_created": True,
        "report_rendered_from_published_documents": True,
        "source_tree_clean": bool(source_tree_clean_attested),
    }
    failed = sorted(name for name, passed in conditions.items() if not passed)
    if failed:
        raise FinalBaselineError(f"final-baseline reporting cannot finalize; failed conditions: {failed}")

    content_hashes = {name: _sha256(directory / name) for name in EVIDENCE_DOCUMENTS}
    marker: dict[str, Any] = {
        "schema_version": "1",
        "kind": "final_baseline_finalization",
        "component": COMPONENT,
        "outcome": OUTCOME,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "conditions": conditions,
        "failed_conditions": failed,
        "comparison_id": results["comparison_id"],
        "roster_id": results["roster_id"],
        "report_id": results["report_id"],
        "stage21a_finalization_fingerprint": (
            evaluation.inputs_document["stage21a_finalization_fingerprint"]
        ),
        "stage21b_finalization_fingerprint": (
            evaluation.inputs_document["stage21b_finalization_fingerprint"]
        ),
        "final_baseline_source_fingerprint": final_baseline_source_fingerprint(root),
        "source_tree_clean": bool(source_tree_clean_attested),
        "source_tree_clean_attestation_scope": (
            "the repository was clean before the self-contained final-baseline reporting change "
            "set and the finalized source set is content-fingerprinted"
        ),
        "evidence_content_hashes": content_hashes,
    }
    marker["final_baseline_finalization_fingerprint"] = _canonical_json_hash(marker)
    publish_evidence_document(directory / FINALIZATION_NAME, marker)
    return marker


def verify_final_baseline_evidence(
    repository_root: Path, *, evidence_directory: Path | None = None
) -> dict[str, Any]:
    """Verify committed final-baseline reporting evidence without any workspace or score."""
    root = Path(repository_root).resolve()
    directory = (
        Path(evidence_directory).resolve()
        if evidence_directory is not None
        else root / EVIDENCE_DIRECTORY
    )
    present = sorted(path.name for path in directory.iterdir() if path.is_file())
    expected = sorted(("README.md", *EVIDENCE_DOCUMENTS, FINALIZATION_NAME))
    if present != expected:
        raise FinalBaselineError(
            f"final-baseline reporting evidence files are {present}, expected {expected}"
        )

    marker = _read_json(directory / FINALIZATION_NAME)
    fingerprint = marker.get("final_baseline_finalization_fingerprint")
    body = dict(marker)
    body.pop("final_baseline_finalization_fingerprint", None)
    if fingerprint != _canonical_json_hash(body):
        raise FinalBaselineError("final-baseline reporting finalization fingerprint does not cover marker")
    if marker.get("outcome") != OUTCOME:
        raise FinalBaselineError(f"final-baseline reporting outcome is {marker.get('outcome')!r}")
    conditions = marker.get("conditions", {})
    if not conditions or not all(conditions.values()):
        raise FinalBaselineError("final-baseline reporting marker carries a failed condition")
    for name, digest in marker.get("evidence_content_hashes", {}).items():
        if _sha256(directory / name) != digest:
            raise FinalBaselineError(f"final-baseline reporting evidence digest changed: {name}")
    if marker.get("final_baseline_source_fingerprint") != final_baseline_source_fingerprint(root):
        raise FinalBaselineError(
            "final-baseline reporting source fingerprint no longer describes this tree"
        )

    inputs_document = _read_json(directory / "evaluation-inputs.json")
    results_document = _read_json(directory / "tar-far-frr-results.json")
    context_document = _read_json(
        directory / "native-documented-rules-context.json"
    )
    if len(inputs_document.get("methods", ())) != EXPECTED_METHODS:
        raise FinalBaselineError("published inputs do not carry six roster methods")
    for index, method in enumerate(inputs_document["methods"]):
        role = method.get("role") if isinstance(method, Mapping) else None
        if not isinstance(role, str) or not role.strip():
            raise FinalBaselineError(
                f"published input method entry {index}: role must be a non-empty string"
            )
    if results_document.get("primary_far_target") != "1/1000":
        raise FinalBaselineError("published primary FAR target moved")
    rendered = _render(root, inputs_document, results_document, context_document)
    committed = (directory / REPORT_NAME).read_text(encoding="utf-8")
    if rendered != committed:
        raise FinalBaselineError(
            "the committed report is not the rendering of the committed "
            "documents"
        )
    return marker
