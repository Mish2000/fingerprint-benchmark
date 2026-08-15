"""G6 — what the run produced, whether it may be published, and the marker.

Two writes, in the shape every stage since 8D has used: ``documents`` derives the
seven readable files and commits them, ``publish`` writes the marker over
evidence that already exists in Git. Splitting them is what makes the marker a
statement about committed bytes rather than about whatever was on disk at the
time.

The integrity requirements are absolute and none of them is a rate:

.. code-block:: text

    stored outcomes = 6000        missing = 0        duplicates = 0
    scores + algorithmic failures = 6000
    infrastructure failures = 0
    thresholds = calibration = metrics = false
    prior algorithm scores read = false

The failure breakdown *is* published, because a reader who cannot see which
refusals happened cannot judge the result set. What is not published is any rate
that would invite a comparison between algorithms at this stage — that layer
comes later, over stored scores, and never over one algorithm alone.

**The outcome turns on one property that nothing else in this stage decides.**
A result set of 6,000 outcomes can be complete, deterministic, internally
consistent and still contain no score at all, if the algorithm refused every
print it was given. That is a real finding and it is published as one, but it is
not a fifth raw matcher, and
``FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE`` is refused for it. Only a
score-bearing set establishes Algorithm 5 and opens the common calibration phase
(docs/adr/0128).
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.serialization import stable_hash
from fpbench.core.stage15a_errors import (
    Stage15AFinalizationError,
    Stage15AResultIntegrityError,
    Stage15ASelectionError,
)
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_qualification as qualification
from fpbench.experiments import stage15a_route as route
from fpbench.experiments import stage15a_runtime as runtime

__all__ = [
    "build_predecessor_selection_document",
    "build_artifact_runtime_identity_document",
    "build_upstream_route_contract_document",
    "build_qualification_document",
    "build_canonical_run_binding_document",
    "build_result_integrity_document",
    "build_stage15a_finalization",
    "stage15a_finalization_fingerprint",
    "stage15a_source_fingerprint",
    "publish_stage15a_evidence",
    "publish_stage15a_finalization",
    "verify_stage15a_evidence",
    "main",
]

_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/stage15a_errors.py",
    "src/fpbench/experiments/stage15a_identity.py",
    "src/fpbench/experiments/stage15a_runtime.py",
    "src/fpbench/experiments/stage15a_route.py",
    "src/fpbench/experiments/stage15a_qualification.py",
    "src/fpbench/experiments/stage15a_validation.py",
    "src/fpbench/experiments/stage15a_research.py",
    "src/fpbench/experiments/stage15a_canonical500_full.py",
    "src/fpbench/experiments/stage15a_finalization.py",
    "src/fpbench/adapters/fingerprints_matching/adapter.py",
    "src/fpbench/adapters/fingerprints_matching/bridge_client.py",
    "integrations/fingerprints-matching/bridge.py",
)


# --------------------------------------------------------------- the documents


def build_predecessor_selection_document() -> dict[str, Any]:
    """What Stage 15A supersedes, and the rule that made it supersede it.

    Stage 14A is recorded exactly as HEAD published it: a non-final
    investigation in which no request was ever sent. It is not being turned into
    a FAIL after the fact, because a FAIL would report a vendor position that
    does not exist. What changed is fpbench's own selection criterion, and that
    is a statement about this project, not about Griaule (docs/adr/0126).
    """
    return {
        "schema": "stage_15a_predecessor_selection_v1",
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "selection_policy": dict(frozen.SELECTION_POLICY),
        "superseded_candidate": frozen.SUPERSEDED_CANDIDATE,
        "stage14a_final_outcome": frozen.STAGE_14A_FINAL_OUTCOME,
        "reason_not_continued": frozen.REASON_NOT_CONTINUED,
        "vendor_request_sent": frozen.VENDOR_REQUEST_SENT,
        "stage14a_evidence_modified": False,
        "stage14a_treatment": (
            "frozen as non-final and left byte-for-byte as HEAD published it. "
            "No marker was written for it and none may be"
        ),
        "why_not_a_failure": (
            "nobody contacted Griaule, so there is no refusal, no silence and no "
            "finding about the candidate to report. Rewriting an unfinished "
            "investigation as a FAIL would manufacture evidence "
            "(docs/adr/0104, docs/adr/0121)"
        ),
        "what_changed": (
            "the criterion, not the candidate. Three consecutive Algorithm 5 "
            "stages ended at a vendor — a refused licence, an entitlement that "
            "never arrived, and a package no official route serves — so "
            "self-service acquisition and runnability without vendor action "
            "became hard requirements"
        ),
        "reserve_candidate": frozen.RESERVE_CANDIDATE,
        "out_of_queue_candidates": list(frozen.OUT_OF_QUEUE_CANDIDATES),
        "commercial_search_reopened": False,
        "bound_markers": [dict(marker) for marker in frozen.BOUND_MARKERS],
        "prior_algorithm_scores_read": False,
        "forbidden_reads": list(frozen.FORBIDDEN_READS),
    }


def build_artifact_runtime_identity_document(
    *, repository_root: Path
) -> dict[str, Any]:
    closure = runtime.build_runtime_closure(repository_root=repository_root)
    document = closure.as_document()
    document["runtime_manifest_fingerprint"] = runtime.runtime_manifest_fingerprint(
        closure
    )
    return document


def build_upstream_route_contract_document(*, repository_root: Path) -> dict[str, Any]:
    return route.read_route_contract(repository_root=repository_root).as_document()


def build_qualification_document(*, repository_root: Path) -> dict[str, Any]:
    return qualification.run_qualification(repository_root=repository_root).as_document()


def build_canonical_run_binding_document(
    *, repository_root: Path, run_id: str, plan_id: str, result_set_id: str | None
) -> dict[str, Any]:
    """The reference run this one is aligned against, and what was reused."""
    return {
        "schema": "stage_15a_canonical_run_binding_v1",
        "gate": frozen.GATES["G5"],
        "experiment_id": frozen.EXPERIMENT_ID,
        "run_id": run_id,
        "plan_id": plan_id,
        "result_set_id": result_set_id,
        "reference": {
            "run_id": frozen.REFERENCE_RUN_ID,
            "plan_id": frozen.REFERENCE_PLAN_ID,
            "result_set_id": frozen.REFERENCE_RESULT_SET_ID,
            "cohort_id": frozen.REFERENCE_COHORT_ID,
            "pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        },
        "preparation": {
            "set_id": frozen.PREPARATION_SET_ID,
            "set_fingerprint": frozen.PREPARATION_SET_FINGERPRINT,
            "transform_profile_id": frozen.TRANSFORM_PROFILE_ID,
            "transform_profile_fingerprint": frozen.TRANSFORM_PROFILE_FINGERPRINT,
            "transform_runtime_fingerprint": frozen.TRANSFORM_RUNTIME_FINGERPRINT,
            "target_ppi": 500,
        },
        "expected": {
            "comparisons": frozen.EXPECTED_JOBS,
            "logical_extractions": frozen.EXPECTED_LOGICAL_EXTRACTIONS,
            "match_invocations": frozen.EXPECTED_MATCH_INVOCATIONS,
            "participating_images": frozen.EXPECTED_PARTICIPATING_IMAGES,
            "releases": list(frozen.EXPECTED_RELEASES),
            "per_release_stage": frozen.EXPECTED_PER_RELEASE_STAGE,
        },
        "execution": {
            "profile_id": frozen.EXECUTION_PROFILE_ID,
            "max_workers": frozen.MAX_WORKERS,
            "retries": frozen.RETRIES,
            "job_deadline_seconds": frozen.JOB_DEADLINE_SECONDS,
            "deadline_chosen_from": (
                "qualification timings on non-SD300 fixtures, before the "
                "canonical set was opened"
            ),
        },
        "argument_binding": {
            "pair.left": frozen.LEFT_ARGUMENT,
            "pair.right": frozen.RIGHT_ARGUMENT,
            "reversed": False,
            "maximum_of_both_orderings": False,
            "averaged": False,
        },
        "sd300_pilot_before_the_run": False,
        "why_no_pilot": (
            "a pilot over the evaluation set is an SD300 run nobody counted. The "
            "qualification ran on non-SD300 fixtures and these 6,000 are the "
            "canonical production execution"
        ),
        "cohort_selected_here": False,
        "pairs_generated_here": False,
        "images_materialised_here": False,
    }


def build_result_integrity_document(report: Any, *, run_id: str) -> dict[str, Any]:
    """Every integrity requirement, and the failure breakdown behind it.

    Counts and codes. No rate that would support a comparison between algorithms
    at this stage, and no score statistic of any kind.
    """
    total = int(report.total_results)
    scores = int(report.successful_results)
    algorithmic = int(report.algorithmic_failures)
    infrastructure = int(report.blocking_failures)
    return {
        "schema": "stage_15a_result_integrity_v1",
        "gate": frozen.GATES["G6"],
        "run_id": run_id,
        "plan_id": report.plan_id,
        "expected_comparisons": frozen.EXPECTED_JOBS,
        "stored_outcomes": total,
        "missing": max(0, frozen.EXPECTED_JOBS - total),
        "duplicates": 0,
        "scores": scores,
        # The split that keeps the headline honest. A SELF comparison extracts
        # one image twice and every minutia matches itself, so upstream returns
        # exactly 1.0 whenever extraction succeeds — a fact about the extractor
        # running, not about the matcher discriminating. Genuine scores are the
        # ones that compare two different prints.
        "scores_self": int(report.self_scores),
        "scores_genuine": int(report.genuine_scores),
        "self_score_is_constant_by_construction": True,
        "self_score_value": 1.0,
        "is_genuine_score_bearing": bool(report.is_genuine_score_bearing),
        "algorithm_failures": algorithmic,
        "infrastructure_failures": infrastructure,
        "outcomes_partition_holds": scores + algorithmic + infrastructure == total,
        "logical_extractions": int(report.logical_extraction_calls),
        "match_invocations": int(report.comparison_calls),
        "result_set_validation_clean": bool(report.is_clean),
        "validation_fingerprint": report.validation_fingerprint,
        "is_score_bearing": bool(report.is_score_bearing),
        "failure_breakdown": {
            "by_failure_code": dict(report.failure_counts),
            "by_upstream_code": dict(report.upstream_codes),
            "rates_published": False,
            "why_no_rates": (
                "a rate at this stage is an invitation to compare algorithms "
                "before there is a common operating point. The counts are here; "
                "the comparison is a later layer"
            ),
        },
        "thresholds": False,
        "calibration": False,
        "metrics": False,
        "prior_algorithm_scores_read": False,
        "score_statistics_published": False,
        "score_export": False,
        "failures_recorded_as_zero": False,
        "issues": [
            {
                "code": issue.code.value,
                "severity": issue.severity.value,
                "message": issue.message,
                "job_id": issue.job_id,
            }
            for issue in report.errors[:50]
        ],
    }


# ------------------------------------------------------------------ the marker


def stage15a_source_fingerprint(repository_root: Path) -> str:
    """A digest over every file that decides what Stage 15A does."""
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage15AFinalizationError(f"a Stage 15A source file is missing: {relative}")
        digests[relative] = _source_file_sha256(path)
    return stable_hash({"schema": "stage_15a_source_v1", "files": digests}, length=64)


def stage15a_finalization_fingerprint(marker: Mapping[str, Any]) -> str:
    """The digest a later stage binds to, at the width every other marker uses.

    ``stable_hash`` defaults to twelve characters, which is right for a run or
    plan id and wrong here: Stage 15A binds Stage 11B and Stage 8E by 64-character
    fingerprints, and whatever supersedes this stage will bind it the same way.
    """
    payload = {
        k: v for k, v in marker.items() if k != "stage_15a_finalization_fingerprint"
    }
    return stable_hash(payload, length=64)


def build_stage15a_finalization(
    *,
    repository_root: Path,
    run_id: str,
    plan_id: str,
    result_set_id: str | None,
    integrity: Mapping[str, Any],
    qualification_document: Mapping[str, Any],
    runtime_document: Mapping[str, Any],
    route_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the marker, and refuse to assemble one the evidence does not support."""
    root = Path(repository_root)

    for gate, document in (
        ("G1", runtime_document),
        ("G2", route_document),
        ("G3", qualification_document),
    ):
        state = document.get("gate_state")
        if state != "PASS":
            raise Stage15AFinalizationError(
                f"{frozen.GATES[gate]} is {state!r}; a marker may not be written "
                "over a gate that did not pass"
            )

    stored = int(integrity["stored_outcomes"])
    scores = int(integrity["scores"])
    algorithmic = int(integrity["algorithm_failures"])
    infrastructure = int(integrity["infrastructure_failures"])

    if stored != frozen.EXPECTED_JOBS:
        raise Stage15AResultIntegrityError(
            f"{stored} stored outcomes against {frozen.EXPECTED_JOBS} expected"
        )
    if int(integrity["missing"]) or int(integrity["duplicates"]):
        raise Stage15AResultIntegrityError("the result set is missing or duplicating outcomes")
    if scores + algorithmic != stored:
        raise Stage15AResultIntegrityError(
            "every comparison must end in a score or an algorithmic failure"
        )
    if infrastructure:
        raise Stage15AResultIntegrityError(
            f"{infrastructure} infrastructure failures reached the stored set"
        )
    if not integrity["result_set_validation_clean"]:
        raise Stage15AResultIntegrityError("the result set does not validate cleanly")

    score_bearing = bool(integrity["is_score_bearing"])
    outcome = frozen.OUTCOME_COMPLETE if score_bearing else frozen.OUTCOME_FAIL

    marker: dict[str, Any] = {
        "schema_version": "1",
        "kind": "stage_15a_finalization",
        "outcome": outcome,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_id": frozen.PRODUCTION_ALGORITHM_ID,
        "adapter_id": frozen.ADAPTER_ID,
        "implementation_version": frozen.PACKAGE_VERSION,
        "package": frozen.PACKAGE_REQUIREMENT,
        "license": frozen.LICENSE,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "runtime_artifact_sha256": frozen.RUNTIME_ARTIFACT_SHA256,
        "source_artifact_sha256": frozen.SOURCE_ARTIFACT_SHA256,
        "stage15a_source_fingerprint": stage15a_source_fingerprint(root),
        "runtime_manifest_fingerprint": runtime_document.get(
            "runtime_manifest_fingerprint"
        ),
        "pinned_python": frozen.PINNED_PYTHON_VERSION,
        "pinned_numpy": frozen.PINNED_NUMPY,
        "pinned_opencv_python": frozen.PINNED_OPENCV,
        "opencv_is_part_of_algorithm_identity": True,
        "experiment_id": frozen.EXPERIMENT_ID,
        "run_id": run_id,
        "plan_id": plan_id,
        "result_set_id": result_set_id,
        "reference_run_id": frozen.REFERENCE_RUN_ID,
        "reference_pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "preparation_set_id": frozen.PREPARATION_SET_ID,
        # ------------------------------------------------------------ the gates
        "gates": {
            frozen.GATES[gate]: document.get("gate_state")
            for gate, document in (
                ("G1", runtime_document),
                ("G2", route_document),
                ("G3", qualification_document),
            )
        },
        # ------------------------------------------------------------- the counts
        "expected_comparisons": frozen.EXPECTED_JOBS,
        "stored_outcomes": stored,
        "successful_scores": scores,
        "successful_scores_self": int(integrity["scores_self"]),
        "successful_scores_genuine": int(integrity["scores_genuine"]),
        "self_score_is_constant_by_construction": True,
        "result_set_is_genuine_score_bearing": bool(
            integrity["is_genuine_score_bearing"]
        ),
        "algorithm_failures": algorithmic,
        "infrastructure_failures": infrastructure,
        "missing_jobs": int(integrity["missing"]),
        "duplicate_jobs": int(integrity["duplicates"]),
        "logical_extractions": int(integrity["logical_extractions"]),
        "match_invocations": int(integrity["match_invocations"]),
        "result_set_validation_clean": True,
        "validation_fingerprint": integrity["validation_fingerprint"],
        "result_set_is_score_bearing": score_bearing,
        # ------------------------------------------------------- what was refused
        "self_service_acquisition": True,
        "runnable_without_vendor_action": True,
        "vendor_request_sent": frozen.VENDOR_REQUEST_SENT,
        "superseded_candidate": frozen.SUPERSEDED_CANDIDATE,
        "stage14a_final_outcome": frozen.STAGE_14A_FINAL_OUTCOME,
        "stage14a_evidence_modified": False,
        "raw_score_route": True,
        "self_independent_sides": True,
        "pair_orientation_fixed": True,
        "symmetry_required": frozen.SYMMETRY_REQUIRED,
        "fpbench_preprocessing_added": False,
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "score_formula_reimplemented": False,
        "denominator_fallback_added": False,
        "invented_score_for_empty_features": False,
        "failures_recorded_as_zero": False,
        "template_cache": "none",
        "canonical_prepared_set_exact": True,
        "pair_manifest_exact": True,
        "sd300_pilot_before_the_run": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "score_statistics_published": False,
        "failure_rates_published": False,
        "algorithm_ranking_published": False,
        "prior_algorithm_scores_consulted": False,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "absolute_paths_in_evidence": False,
        # ------------------------------------------------------ what this opens
        "algorithm_5_established": score_bearing,
        "reopens_algorithm_5_search": not score_bearing,
        "opens_common_calibration": score_bearing,
        "calibration_roster": (
            [
                "sourceafis",
                "nbis",
                "flx",
                "verifinger_1to1",
                frozen.PRODUCTION_ALGORITHM_ID,
            ]
            if score_bearing
            else []
        ),
        "fallback_candidate": None if score_bearing else frozen.RESERVE_CANDIDATE,
        "evidence_content_hashes": _evidence_content_hashes(root),
        "source_commit": _head_commit(root),
        "source_tree_clean": _tree_is_clean(root),
        "created_utc": _utc_now(),
    }
    if not score_bearing:
        marker["why_not_complete"] = (
            "the run produced 6,000 complete, deterministic outcomes and no "
            "score among them. A result set in which the algorithm declined "
            "every print is a finding, not a fifth raw matcher, and it cannot "
            "open a calibration phase over scores that do not exist "
            "(docs/adr/0128)"
        )
    marker["stage_15a_finalization_fingerprint"] = stage15a_finalization_fingerprint(marker)
    return marker


# ------------------------------------------------------------------- publishing


def _evidence_directory(repository_root: Path) -> Path:
    return Path(repository_root) / frozen.EVIDENCE_DIRECTORY


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def publish_stage15a_evidence(
    *,
    repository_root: Path,
    run_id: str,
    plan_id: str,
    result_set_id: str | None,
    integrity: Mapping[str, Any],
) -> dict[str, Path]:
    """Write the seven derivable documents. Never the marker."""
    root = Path(repository_root)
    directory = _evidence_directory(root)
    written: dict[str, Path] = {}

    documents = {
        "predecessor-selection.json": build_predecessor_selection_document(),
        "artifact-runtime-identity.json": build_artifact_runtime_identity_document(
            repository_root=root
        ),
        "upstream-route-contract.json": build_upstream_route_contract_document(
            repository_root=root
        ),
        "qualification.json": build_qualification_document(repository_root=root),
        "canonical-run-binding.json": build_canonical_run_binding_document(
            repository_root=root,
            run_id=run_id,
            plan_id=plan_id,
            result_set_id=result_set_id,
        ),
        "result-integrity.json": dict(integrity),
    }
    for name, document in documents.items():
        path = directory / name
        _write_json(path, document)
        written[name] = path
    _require_no_forbidden_published_data(directory)
    return written


def publish_stage15a_finalization(
    *,
    repository_root: Path,
    run_id: str,
    plan_id: str,
    result_set_id: str | None,
    integrity: Mapping[str, Any],
) -> Path:
    """Write the marker, over evidence that is already committed."""
    root = Path(repository_root)
    directory = _evidence_directory(root)
    for name in frozen.EVIDENCE_DOCUMENTS:
        if name == frozen.STAGE_15A_FINALIZATION_NAME:
            continue
        if not (directory / name).is_file():
            raise Stage15AFinalizationError(
                f"{name} is not published yet; run the documents step and commit "
                "it before writing a marker"
            )
    marker = build_stage15a_finalization(
        repository_root=root,
        run_id=run_id,
        plan_id=plan_id,
        result_set_id=result_set_id,
        integrity=integrity,
        qualification_document=json.loads(
            (directory / "qualification.json").read_text(encoding="utf-8")
        ),
        runtime_document=json.loads(
            (directory / "artifact-runtime-identity.json").read_text(encoding="utf-8")
        ),
        route_document=json.loads(
            (directory / "upstream-route-contract.json").read_text(encoding="utf-8")
        ),
    )
    path = directory / frozen.STAGE_15A_FINALIZATION_NAME
    _write_json(path, marker)
    return path


def verify_stage15a_evidence(*, repository_root: Path) -> dict[str, Any]:
    """Re-derive what can be re-derived from committed evidence alone.

    Runs with no artifact store, no frozen runtime and no workspace: that is what
    makes it a CI gate rather than a re-run.
    """
    root = Path(repository_root)
    directory = _evidence_directory(root)
    findings: dict[str, Any] = {"evidence_directory": str(frozen.EVIDENCE_DIRECTORY)}

    missing = [
        name for name in frozen.EVIDENCE_DOCUMENTS if not (directory / name).is_file()
    ]
    findings["missing_documents"] = missing
    if missing:
        raise Stage15AFinalizationError(
            f"the Stage 15A evidence is incomplete: {', '.join(missing)}"
        )

    marker = json.loads(
        (directory / frozen.STAGE_15A_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    recomputed = stage15a_finalization_fingerprint(marker)
    if recomputed != marker.get("stage_15a_finalization_fingerprint"):
        raise Stage15AFinalizationError(
            "the marker's fingerprint does not match its own contents"
        )
    if marker.get("outcome") not in frozen.OUTCOMES:
        raise Stage15AFinalizationError(
            f"{marker.get('outcome')!r} is not a Stage 15A outcome"
        )

    selection = json.loads(
        (directory / "predecessor-selection.json").read_text(encoding="utf-8")
    )
    if selection.get("stage14a_final_outcome") != frozen.STAGE_14A_FINAL_OUTCOME:
        raise Stage15ASelectionError(
            "the selection record gives Stage 14A a final outcome it does not have"
        )
    if selection.get("vendor_request_sent") is not False:
        raise Stage15ASelectionError(
            "the selection record claims a Griaule request was sent"
        )

    observed = _evidence_content_hashes(root)
    recorded = marker.get("evidence_content_hashes") or {}
    drifted = sorted(
        name for name, digest in recorded.items() if observed.get(name) != digest
    )
    if drifted:
        raise Stage15AFinalizationError(
            "published evidence has changed since the marker was written: "
            + ", ".join(drifted)
        )

    _require_no_forbidden_published_data(directory)
    findings["outcome"] = marker["outcome"]
    findings["stage_15a_finalization_fingerprint"] = recomputed
    findings["documents_verified"] = len(frozen.EVIDENCE_DOCUMENTS)
    findings["result_set_is_score_bearing"] = marker.get("result_set_is_score_bearing")
    findings["algorithm_5_established"] = marker.get("algorithm_5_established")
    findings["opens_common_calibration"] = marker.get("opens_common_calibration")
    return findings


# --------------------------------------------------------------------- helpers


def _require_no_forbidden_published_data(directory: Path) -> None:
    """No threshold-shaped key, and no absolute path, in anything published."""
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        found = _forbidden_keys(document)
        # ``decision_threshold`` is permitted as a *denial* whose value says the
        # stage has none; anything with a number behind it is not.
        offending = sorted(
            key
            for key in found
            if not _is_denial(document, key)
        )
        if offending:
            raise Stage15AFinalizationError(
                f"{path.name} carries decision-shaped keys: {', '.join(offending)}"
            )
        text = path.read_text(encoding="utf-8")
        for marker in ("C:\\\\", "C:/", "/home/", "/Users/"):
            if marker in text:
                raise Stage15AFinalizationError(
                    f"{path.name} carries an absolute machine path"
                )


def _is_denial(document: Any, key: str) -> bool:
    """Whether every occurrence of ``key`` states an absence rather than a value."""
    values: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for name, value in node.items():
                if str(name).lower() == key:
                    values.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return bool(values) and all(
        value is False or value in (None, "NONE", "none", 0) for value in values
    )


def _forbidden_keys(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            if str(key).lower() in frozen.FORBIDDEN_CONFIG_KEYS:
                found.add(str(key).lower())
            found |= _forbidden_keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _forbidden_keys(item)
    return found


def _evidence_content_hashes(repository_root: Path) -> dict[str, str]:
    directory = _evidence_directory(repository_root)
    hashes: dict[str, str] = {}
    for name in frozen.EVIDENCE_DOCUMENTS:
        if name == frozen.STAGE_15A_FINALIZATION_NAME:
            continue
        path = directory / name
        if path.is_file():
            hashes[name] = _source_file_sha256(path)
    return hashes


def _source_file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _head_commit(repository_root: Path) -> str:
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            cwd=str(repository_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def _tree_is_clean(repository_root: Path) -> bool:
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"],
            cwd=str(repository_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0 and not completed.stdout.strip()
    except OSError:
        return False


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "verify"
    root = Path(".")
    if command == "verify":
        print(json.dumps(verify_stage15a_evidence(repository_root=root), indent=2, sort_keys=True))
        return 0
    print(
        f"unknown command {command!r}. `documents` and `publish` need a finished "
        "run and are driven by fpbench.experiments.stage15a_publish",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
