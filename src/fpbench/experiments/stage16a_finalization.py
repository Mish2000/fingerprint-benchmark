"""The nine documents, the marker, and the refusals that shape both.

Two writes, in the shape every stage since 8D has used: ``documents`` derives the
eight readable files and commits them, ``publish`` writes the marker over
evidence that already exists in Git. Splitting them is what makes the marker a
statement about committed bytes rather than about whatever was on disk.

**Gates that were not reached are written, and written as unreached.** Stage 16A
stops at the first gate that fails, so G3 through G7 have documents with
``gate_state: NOT_REACHED``, no findings and no invented content. The alternative
— omitting them — would leave a reader unable to tell "this was fine" from "this
was never asked", which is the distinction Stage 10B and Stage 14A both had to
publish explicitly.

**The marker refuses to overstate what happened.** ``algorithm_5_established``
is true only when the outcome is the complete one, and the four acceptance
conditions are published beside it whichever way it went. Stage 15A was accepted
on "the result set carries at least one score", which turned out to mean
twenty-two comparisons of two different prints out of six thousand; that
criterion is retired here and its replacement deliberately carries no number
(docs/adr/0130).

**No Stage 15A byte is touched.** The predecessor document cites Stage 15A's
extraction mechanism and never its scores, and the two facts it publishes about
that — ``predecessor_scores_read: false`` and the three reasons this is *not* —
are checked by :func:`verify_stage16a_evidence` rather than merely asserted.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.serialization import stable_hash
from fpbench.core.stage16a_errors import (
    Stage16AFinalizationError,
    Stage16ASelectionError,
)
from fpbench.experiments import stage16a_artifacts as artifacts
from fpbench.experiments import stage16a_identity as frozen
from fpbench.experiments import stage16a_route as route

__all__ = [
    "build_predecessor_selection_document",
    "build_artifact_runtime_identity_document",
    "build_upstream_inference_route_document",
    "build_score_contract_document",
    "build_qualification_document",
    "build_canonical_run_binding_document",
    "build_result_integrity_document",
    "build_stage16a_finalization",
    "stage16a_finalization_fingerprint",
    "stage16a_source_fingerprint",
    "decide_outcome",
    "publish_stage16a_evidence",
    "publish_stage16a_finalization",
    "verify_stage16a_evidence",
    "main",
]

_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/stage16a_errors.py",
    "src/fpbench/experiments/stage16a_identity.py",
    "src/fpbench/experiments/stage16a_acquire.py",
    "src/fpbench/experiments/stage16a_artifacts.py",
    "src/fpbench/experiments/stage16a_route.py",
    "src/fpbench/experiments/stage16a_finalization.py",
)

#: What a document looks like when the stage never got to its gate. Deliberately
#: uniform, so that "not reached" is one shape rather than five improvisations.
_NOT_REACHED = "NOT_REACHED"


# --------------------------------------------------------------- the documents


def build_predecessor_selection_document() -> dict[str, Any]:
    """Why Stage 15A did not fill the Algorithm 5 slot, in mechanism only.

    Stage 15A's raw results are untouched and its scores were not consulted. The
    finding is that its image-to-features route fails structurally on valid
    input: a single degenerate contour aborts an otherwise processable image, the
    behaviour is deterministic, and a repair would mean editing the upstream
    algorithm. None of that is a statement about how well it matched
    (docs/adr/0130).
    """
    return {
        "schema": "stage_16a_predecessor_selection_v1",
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "stage15a_outcome": frozen.PREDECESSOR_OUTCOME,
        "stage15a_selected_for_algorithm_5": (
            frozen.PREDECESSOR_SELECTED_FOR_ALGORITHM_5
        ),
        "reason": frozen.PREDECESSOR_REASON,
        "evidence": list(frozen.PREDECESSOR_EVIDENCE),
        "reason_is_not": list(frozen.PREDECESSOR_REASON_IS_NOT),
        "stage15a_evidence_modified": False,
        "stage15a_raw_results_modified": False,
        "stage15a_rerun": False,
        "predecessor_scores_read": False,
        "prior_algorithm_scores_read": False,
        "forbidden_reads": list(frozen.FORBIDDEN_READS),
        "how_the_successor_was_chosen": (
            "it was already chosen. fingerflow_3_0_1 is the reserve candidate "
            "Stage 15A's own predecessor-selection record names, under a "
            "selection policy that predates any result from either candidate"
        ),
        "selection_policy": {
            "self_service_acquisition": "HARD_REQUIREMENT",
            "runnable_without_vendor_action": "HARD_REQUIREMENT",
        },
        "why_the_mechanism_and_not_the_scores": (
            "a score distribution cannot distinguish an algorithm that is strict "
            "from one that is broken, and Stage 15A was both complete and valid "
            "while being unusable. Choosing a successor on separation or on "
            "genuine-score counts would also rank two algorithms before there is "
            "a common operating point between any of the five, which every stage "
            "since 7D has refused to do"
        ),
        "bound_markers": [dict(record) for record in frozen.BOUND_MARKERS],
    }


def build_artifact_runtime_identity_document(
    *, repository_root: Path
) -> dict[str, Any]:
    return artifacts.inspect_artifacts(repository_root=repository_root).as_document()


def build_upstream_inference_route_document(*, repository_root: Path) -> dict[str, Any]:
    return route.read_route_closure(repository_root=repository_root).as_document()


def build_score_contract_document(*, reached: bool) -> dict[str, Any]:
    """G3 — what a score would have been, frozen whether or not it was reached.

    The contract is written down even when the gate is not reached, because it
    is the thing G2 failed to make usable: ``Matcher.verify`` is unambiguous and
    the route that feeds it is not. Recording only the failure would lose the
    half that was in good order.
    """
    document: dict[str, Any] = {
        "schema": "stage_16a_score_contract_v1",
        "gate": frozen.GATES["G3"],
        "gate_state": "PASS" if reached else _NOT_REACHED,
        "candidate_id": frozen.CANDIDATE_ID,
        "entry_point": "fingerflow.matcher.Matcher.verify",
        "entry_signature": [frozen.LEFT_ARGUMENT, frozen.RIGHT_ARGUMENT],
        "argument_binding": {
            "pair.left": frozen.LEFT_ARGUMENT,
            "pair.right": frozen.RIGHT_ARGUMENT,
            "reversed": False,
            "averaged": False,
            "maximum_of_both_orderings": False,
        },
        "score_native_type": frozen.SCORE_NATIVE_TYPE,
        "score_direction": frozen.SCORE_DIRECTION,
        "score_range": frozen.SCORE_RANGE,
        "score_transform": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "threshold": frozen.DECISION_THRESHOLD,
        "calibration": frozen.CALIBRATION,
        "symmetry_required": frozen.SYMMETRY_REQUIRED,
        "symmetry_repairs_refused": list(frozen.SYMMETRY_REPAIRS_REFUSED),
        "why_symmetry_is_tested_not_assumed": (
            "verify runs both sides through one shared embedding network and "
            "combines them with a euclidean distance, which is symmetric in "
            "principle — but a BatchNormalization layer sits between that "
            "distance and the sigmoid. If the two orderings differ the "
            "orientation is frozen, never repaired (docs/adr/0109)"
        ),
        "what_the_artifact_shows": {
            "verify returns one scalar": True,
            "observed_python_type": "numpy.float32",
            "type_note": (
                "numpy.float32 is widened to a Python float for storage; that is "
                "a type normalisation and not a score transformation"
            ),
            "final_layer": "Dense(1, activation='sigmoid')",
            "threshold_inside_verify": "NONE",
            "observed_under": (
                "the frozen closure, loading VerifyNet-30.h5 at precision 30 and "
                "calling verify on two synthetic six-column arrays"
            ),
        },
        "upstream_readme_range": "0-1",
        "upstream_readme_range_is_fpbench_contract": False,
        "why_range_is_unspecified": (
            "the sigmoid bounds the value by construction and the README says "
            "0-1, but a published range is the first thing a later stage would "
            "build an operating point on. It is recorded as observed, not frozen "
            "as a contract"
        ),
    }
    if not reached:
        document["why_not_reached"] = (
            "G2 did not close the route, so there is no defined feature vector to "
            "hand verify and no comparison to make. The contract above is what "
            "the artifact establishes about the matcher alone, which was never "
            "the part in question"
        )
    return document


def build_qualification_document(*, reached: bool) -> dict[str, Any]:
    """G4 — the qualification protocol, and the failure split it exists to apply."""
    document: dict[str, Any] = {
        "schema": "stage_16a_qualification_v1",
        "gate": frozen.GATES["G4"],
        "gate_state": "PASS" if reached else _NOT_REACHED,
        "candidate_id": frozen.CANDIDATE_ID,
        "comparisons_budget": frozen.QUALIFICATION_MAX_COMPARISONS,
        "comparisons_used": 0 if not reached else None,
        "sd300_used": False,
        "fixtures": "non-SD300 only",
        "required_cases": list(frozen.QUALIFICATION_CASES),
        "failure_probes": list(frozen.FAILURE_PROBES),
        "determinism_required": True,
        "non_result_classes": dict(frozen.NON_RESULT_CLASSES),
        "why_the_split_exists": (
            "Stage 15A's candidate aborted whole images from inside "
            "cv2.convexityDefects on valid prints, and a result set recorded that "
            "as template extraction failing. It is not the same thing as an "
            "algorithm declining an input, and a candidate that does it "
            "systematically is disqualified rather than described "
            "(docs/adr/0131)"
        ),
        "observations": [],
    }
    if not reached:
        document["why_not_reached"] = (
            "the qualification runs the route, and G2 established there is no "
            "single route to run. Probing one of the four undetermined "
            "alternatives would qualify a pipeline fpbench invented"
        )
    return document


def build_canonical_run_binding_document(
    *,
    reached: bool,
    run_id: str | None = None,
    plan_id: str | None = None,
    result_set_id: str | None = None,
) -> dict[str, Any]:
    """G6 — the run this stage would have executed, and what it would have reused."""
    document: dict[str, Any] = {
        "schema": "stage_16a_canonical_run_binding_v1",
        "gate": frozen.GATES["G6"],
        "gate_state": "PASS" if reached else _NOT_REACHED,
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
        },
        "cohort_selected_here": False,
        "pairs_generated_here": False,
        "images_materialised_here": False,
        "sd300_pilot_before_the_run": frozen.SD300_PILOT,
        "why_no_pilot": (
            "a pilot over the evaluation set is an SD300 run nobody counted. The "
            "qualification runs on non-SD300 fixtures and the 6,000 are the "
            "production execution"
        ),
    }
    if not reached:
        document["why_not_reached"] = (
            "no adapter was frozen, because G5 requires G1 through G4 to pass and "
            "G2 did not. Nothing was executed and no SD300 image was opened"
        )
        document["sd300_images_opened"] = 0
    return document


def build_result_integrity_document(
    *, reached: bool, integrity: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """G7 — what the run produced, and the four conditions for Algorithm 5."""
    if reached and integrity is not None:
        document = dict(integrity)
        document.setdefault("schema", "stage_16a_result_integrity_v1")
        document.setdefault("gate", frozen.GATES["G7"])
        document.setdefault("gate_state", "PASS")
    else:
        document = {
            "schema": "stage_16a_result_integrity_v1",
            "gate": frozen.GATES["G7"],
            "gate_state": _NOT_REACHED,
            "expected_comparisons": frozen.EXPECTED_JOBS,
            "stored_outcomes": 0,
            "missing": frozen.EXPECTED_JOBS,
            "duplicates": 0,
            "scores": 0,
            "algorithm_failures": 0,
            "infrastructure_failures": 0,
            "route_failures": 0,
            "why_not_reached": (
                "there is no result set. The stage closed at G2 and executed "
                "nothing"
            ),
        }
    document["thresholds"] = False
    document["calibration"] = False
    document["metrics"] = False
    document["score_statistics_published"] = False
    document["score_export"] = False
    document["prior_algorithm_scores_read"] = False
    document["failures_recorded_as_zero"] = False
    document["algorithm_5_acceptance_conditions"] = list(
        frozen.ALGORITHM_5_ACCEPTANCE_CONDITIONS
    )
    document["at_least_one_score_is_not_sufficient"] = True
    document["why_the_fourth_condition_has_no_number"] = (
        "a count invented after seeing the data is a threshold chosen from the "
        "evaluation set. If a candidate approaches Stage 15A's extreme the stage "
        "stops before the marker and the judgement is made on the mechanism, by "
        "a person (docs/adr/0130)"
    )
    return document


# ------------------------------------------------------------------ the marker


def decide_outcome(
    *, route_document: Mapping[str, Any], artifact_document: Mapping[str, Any]
) -> tuple[str, str | None]:
    """Which of the three outcomes this is, and the blocker behind it."""
    if artifact_document.get("gate_state") != "PASS":
        return (
            frozen.OUTCOME_QUALIFICATION_FAIL,
            str(artifact_document.get("blocker") or "SELF_SERVICE_ARTIFACT_INCOMPLETE"),
        )
    if route_document.get("gate_state") != "PASS":
        return (
            frozen.OUTCOME_ROUTE_FAIL,
            str(route_document.get("blocker") or "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED"),
        )
    return frozen.OUTCOME_COMPLETE, None


def stage16a_source_fingerprint(repository_root: Path) -> str:
    """A digest over every file that decides what Stage 16A does."""
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage16AFinalizationError(
                f"a Stage 16A source file is missing: {relative}"
            )
        digests[relative] = _file_sha256(path)
    return stable_hash({"schema": "stage_16a_source_v1", "files": digests}, length=64)


def stage16a_finalization_fingerprint(marker: Mapping[str, Any]) -> str:
    """The digest a later stage binds to, at the width every other marker uses."""
    payload = {
        k: v for k, v in marker.items() if k != "stage_16a_finalization_fingerprint"
    }
    return stable_hash(payload, length=64)


def build_stage16a_finalization(
    *,
    repository_root: Path,
    artifact_document: Mapping[str, Any],
    route_document: Mapping[str, Any],
    score_document: Mapping[str, Any],
    qualification_document: Mapping[str, Any],
    integrity_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the marker, and refuse to assemble one the evidence does not support."""
    root = Path(repository_root)
    outcome, blocker = decide_outcome(
        route_document=route_document, artifact_document=artifact_document
    )
    complete = outcome == frozen.OUTCOME_COMPLETE

    gate_states = {
        frozen.GATES["G1"]: artifact_document.get("gate_state"),
        frozen.GATES["G2"]: route_document.get("gate_state"),
        frozen.GATES["G3"]: score_document.get("gate_state"),
        frozen.GATES["G4"]: qualification_document.get("gate_state"),
        frozen.GATES["G5"]: _NOT_REACHED if not complete else "PASS",
        frozen.GATES["G6"]: _NOT_REACHED if not complete else "PASS",
        frozen.GATES["G7"]: integrity_document.get("gate_state"),
    }
    if complete and any(state != "PASS" for state in gate_states.values()):
        raise Stage16AFinalizationError(
            "a complete outcome was assembled over a gate that did not pass: "
            + ", ".join(f"{k}={v}" for k, v in gate_states.items() if v != "PASS")
        )

    marker: dict[str, Any] = {
        "kind": "stage_16a_finalization",
        "schema_version": "1",
        # -------------------------------------------------------- the candidate
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_id": frozen.CANDIDATE_ID,
        "display_name": frozen.DISPLAY_NAME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "package": frozen.PACKAGE_REQUIREMENT,
        "implementation_version": frozen.PACKAGE_VERSION,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "license": frozen.LICENSE,
        "upstream_commit": frozen.UPSTREAM_COMMIT,
        "upstream_tag": frozen.UPSTREAM_TAG,
        "runtime_artifact_sha256": frozen.RUNTIME_ARTIFACT_SHA256,
        "source_artifact_sha256": frozen.SOURCE_ARTIFACT_SHA256,
        "self_service_acquisition": True,
        "runnable_without_vendor_action": True,
        "vendor_request_sent": False,
        # ------------------------------------------------------------- the gates
        "gates": gate_states,
        "gate_order": list(frozen.GATE_ORDER),
        "gate_count_defined": len(frozen.GATE_ORDER),
        "gate_reached_last": _last_reached(gate_states),
        # ---------------------------------------------------------- the outcome
        "outcome": outcome,
        "blocker": blocker,
        "route_questions_total": len(route_document.get("questions") or ()),
        "route_questions_settled": len(route_document.get("settled_questions") or ()),
        "route_questions_unsettled": list(
            route_document.get("unsettled_questions") or ()
        ),
        # ------------------------------------------------------ what this opens
        "algorithm_5_established": complete,
        "reopens_algorithm_5_search": not complete,
        "opens_common_calibration": complete,
        "calibration_roster": (
            ["sourceafis", "nbis", "flx", "verifinger_1to1", frozen.CANDIDATE_ID]
            if complete
            else []
        ),
        "algorithm_5_acceptance_conditions": list(
            frozen.ALGORITHM_5_ACCEPTANCE_CONDITIONS
        ),
        # ------------------------------------------------------- the predecessor
        "stage15a_outcome": frozen.PREDECESSOR_OUTCOME,
        "stage15a_selected_for_algorithm_5": (
            frozen.PREDECESSOR_SELECTED_FOR_ALGORITHM_5
        ),
        "stage15a_reason": frozen.PREDECESSOR_REASON,
        "stage15a_evidence_modified": False,
        "stage15a_rerun": False,
        "predecessor_scores_read": False,
        # ------------------------------------------------------- what did not run
        "adapter_frozen": complete,
        "sd300_images_opened": 0 if not complete else None,
        "canonical_run_executed": complete,
        "expected_comparisons": frozen.EXPECTED_JOBS,
        "stored_outcomes": int(integrity_document.get("stored_outcomes") or 0),
        # ------------------------------------------------------------ the denials
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "score_statistics_published": False,
        "failure_rates_published": False,
        "algorithm_ranking_published": False,
        "prior_algorithm_scores_consulted": False,
        "fpbench_chose_a_score_affecting_step": False,
        "experiments_run_to_choose_between_route_alternatives": 0,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "absolute_paths_in_evidence": False,
        # ------------------------------------------------------------ provenance
        "stage16a_source_fingerprint": stage16a_source_fingerprint(root),
        "evidence_content_hashes": _evidence_content_hashes(root),
        "source_commit": _head_commit(root),
        "source_tree_clean": _tree_is_clean(root),
        "created_utc": _utc_now(),
    }

    if outcome == frozen.OUTCOME_ROUTE_FAIL:
        marker["why_not_complete"] = (
            "six of the ten questions between a canonical image and a confidence "
            "close on upstream authority and four do not: how many minutiae are "
            "retained, whether inference rotates the image, what happens below "
            "the required minutiae count, and which of the five published "
            "VerifyNet weights is the matcher. Each has several upstream "
            "alternatives and no declared default, each moves the score, and "
            "answering one would make fpbench a co-author of the algorithm "
            "(docs/adr/0132)"
        )
        marker["fallback_candidate"] = None
        marker["why_no_fallback_named"] = (
            "Stage 15A named this candidate as its reserve and there is no "
            "further reserve to name. Selecting the next one is research this "
            "stage did not do, and inventing a name here would look like a "
            "decision that was never made"
        )

    marker["stage_16a_finalization_fingerprint"] = stage16a_finalization_fingerprint(
        marker
    )
    return marker


def _last_reached(gate_states: Mapping[str, Any]) -> str:
    reached = [
        gate
        for key in frozen.GATE_ORDER
        for gate in (frozen.GATES[key],)
        if gate_states.get(gate) != _NOT_REACHED
    ]
    return reached[-1] if reached else "NONE"


# ------------------------------------------------------------------- publishing


def _evidence_directory(repository_root: Path) -> Path:
    return Path(repository_root) / frozen.EVIDENCE_DIRECTORY


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(document, indent=2, sort_keys=True, default=str) + "\n").encode(
            "utf-8"
        )
    )


def build_all_documents(*, repository_root: Path) -> dict[str, dict[str, Any]]:
    """Every derivable document, with each gate's reach decided by the one before."""
    root = Path(repository_root)
    artifact_document = build_artifact_runtime_identity_document(repository_root=root)
    route_document = build_upstream_inference_route_document(repository_root=root)
    reached_after_route = (
        artifact_document.get("gate_state") == "PASS"
        and route_document.get("gate_state") == "PASS"
    )
    return {
        "predecessor-selection.json": build_predecessor_selection_document(),
        "artifact-runtime-identity.json": artifact_document,
        "upstream-inference-route.json": route_document,
        "score-contract.json": build_score_contract_document(
            reached=reached_after_route
        ),
        "qualification.json": build_qualification_document(reached=reached_after_route),
        "canonical-run-binding.json": build_canonical_run_binding_document(
            reached=reached_after_route
        ),
        "result-integrity.json": build_result_integrity_document(
            reached=reached_after_route
        ),
    }


def publish_stage16a_evidence(*, repository_root: Path) -> dict[str, Path]:
    """Write the seven derivable JSON documents. Never the marker, never the README."""
    root = Path(repository_root)
    directory = _evidence_directory(root)
    written: dict[str, Path] = {}
    for name, document in build_all_documents(repository_root=root).items():
        path = directory / name
        _write_json(path, document)
        written[name] = path
    _require_no_forbidden_published_data(directory)
    return written


def publish_stage16a_finalization(*, repository_root: Path) -> Path:
    """Write the marker, over evidence that is already committed."""
    root = Path(repository_root)
    directory = _evidence_directory(root)
    for name in frozen.EVIDENCE_DOCUMENTS:
        if name == frozen.STAGE_16A_FINALIZATION_NAME:
            continue
        if not (directory / name).is_file():
            raise Stage16AFinalizationError(
                f"{name} is not published yet; run the documents step and commit "
                "it before writing a marker"
            )

    def _read(name: str) -> dict[str, Any]:
        return json.loads((directory / name).read_text(encoding="utf-8"))

    marker = build_stage16a_finalization(
        repository_root=root,
        artifact_document=_read("artifact-runtime-identity.json"),
        route_document=_read("upstream-inference-route.json"),
        score_document=_read("score-contract.json"),
        qualification_document=_read("qualification.json"),
        integrity_document=_read("result-integrity.json"),
    )
    path = directory / frozen.STAGE_16A_FINALIZATION_NAME
    _write_json(path, marker)
    return path


def verify_stage16a_evidence(*, repository_root: Path) -> dict[str, Any]:
    """Re-derive what committed evidence alone can re-derive.

    Runs with no artifact store, no frozen runtime and no workspace: that is what
    makes it a CI gate rather than a re-run. The route document's *conclusion* is
    checked against its own questions, so a marker cannot claim a closure the
    questions do not support.
    """
    root = Path(repository_root)
    directory = _evidence_directory(root)
    findings: dict[str, Any] = {
        "evidence_directory": frozen.EVIDENCE_DIRECTORY.as_posix()
    }

    missing = [
        name for name in frozen.EVIDENCE_DOCUMENTS if not (directory / name).is_file()
    ]
    findings["missing_documents"] = missing
    if missing:
        raise Stage16AFinalizationError(
            f"the Stage 16A evidence is incomplete: {', '.join(missing)}"
        )

    marker = json.loads(
        (directory / frozen.STAGE_16A_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    recomputed = stage16a_finalization_fingerprint(marker)
    if recomputed != marker.get("stage_16a_finalization_fingerprint"):
        raise Stage16AFinalizationError(
            "the marker's fingerprint does not match its own contents"
        )
    if marker.get("outcome") not in frozen.OUTCOMES:
        raise Stage16AFinalizationError(
            f"{marker.get('outcome')!r} is not a Stage 16A outcome"
        )

    route_document = json.loads(
        (directory / "upstream-inference-route.json").read_text(encoding="utf-8")
    )
    unsettled = list(route_document.get("unsettled_questions") or ())
    if bool(unsettled) == (route_document.get("gate_state") == "PASS"):
        raise Stage16AFinalizationError(
            "the route document's gate state disagrees with its own questions"
        )
    if unsettled and marker.get("algorithm_5_established"):
        raise Stage16AFinalizationError(
            "the marker establishes Algorithm 5 over an inference route that is "
            "not closed"
        )
    if route_document.get("experiments_run_to_choose_between_alternatives"):
        raise Stage16AFinalizationError(
            "an alternative was chosen by experiment; the route may only be "
            "settled by upstream authority"
        )

    selection = json.loads(
        (directory / "predecessor-selection.json").read_text(encoding="utf-8")
    )
    if selection.get("reason") != frozen.PREDECESSOR_REASON:
        raise Stage16ASelectionError(
            "the predecessor record gives Stage 15A a reason it was not given"
        )
    if selection.get("predecessor_scores_read") or selection.get(
        "prior_algorithm_scores_read"
    ):
        raise Stage16ASelectionError(
            "the predecessor record admits reading scores it may not read"
        )
    if selection.get("stage15a_evidence_modified") or selection.get("stage15a_rerun"):
        raise Stage16ASelectionError(
            "Stage 15A's evidence is recorded as modified or rerun; it is neither"
        )
    for phrase in frozen.PREDECESSOR_REASON_IS_NOT:
        if phrase not in (selection.get("reason_is_not") or ()):
            raise Stage16ASelectionError(
                f"the predecessor record no longer denies {phrase!r} as its reason"
            )

    observed = _evidence_content_hashes(root)
    recorded = marker.get("evidence_content_hashes") or {}
    drifted = sorted(
        name for name, digest in recorded.items() if observed.get(name) != digest
    )
    if drifted:
        raise Stage16AFinalizationError(
            "published evidence has changed since the marker was written: "
            + ", ".join(drifted)
        )

    _require_no_forbidden_published_data(directory)
    findings["outcome"] = marker["outcome"]
    findings["blocker"] = marker.get("blocker")
    findings["stage_16a_finalization_fingerprint"] = recomputed
    findings["documents_verified"] = len(frozen.EVIDENCE_DOCUMENTS)
    findings["route_questions_settled"] = marker.get("route_questions_settled")
    findings["route_questions_unsettled"] = marker.get("route_questions_unsettled")
    findings["algorithm_5_established"] = marker.get("algorithm_5_established")
    findings["opens_common_calibration"] = marker.get("opens_common_calibration")
    return findings


# --------------------------------------------------------------------- helpers


def _require_no_forbidden_published_data(directory: Path) -> None:
    """No threshold-shaped key with a value, and no absolute path, in anything."""
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        offending = sorted(
            key for key in _forbidden_keys(document) if not _is_denial(document, key)
        )
        if offending:
            raise Stage16AFinalizationError(
                f"{path.name} carries decision-shaped keys: {', '.join(offending)}"
            )
        text = path.read_text(encoding="utf-8")
        for absolute in ("C:\\\\", "C:/", "/home/", "/Users/"):
            if absolute in text:
                raise Stage16AFinalizationError(
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
        if name == frozen.STAGE_16A_FINALIZATION_NAME:
            continue
        path = directory / name
        if path.is_file():
            hashes[name] = _file_sha256(path)
    return hashes


def _file_sha256(path: Path) -> str:
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

    if command == "documents":
        written = publish_stage16a_evidence(repository_root=root)
        for name in sorted(written):
            print(f"wrote {frozen.EVIDENCE_DIRECTORY.as_posix()}/{name}")
        print(
            "\nWrite the README, commit these, then run `publish` — the marker is "
            "a statement about committed bytes."
        )
        return 0

    if command == "publish":
        path = publish_stage16a_finalization(repository_root=root)
        marker = json.loads(path.read_text(encoding="utf-8"))
        print(f"wrote {path.as_posix()}")
        print(f"outcome              {marker['outcome']}")
        print(f"blocker              {marker['blocker']}")
        print(f"last gate reached    {marker['gate_reached_last']}")
        print(f"algorithm 5          {marker['algorithm_5_established']}")
        print(f"opens calibration    {marker['opens_common_calibration']}")
        return 0

    if command == "verify":
        print(
            json.dumps(
                verify_stage16a_evidence(repository_root=root), indent=2, sort_keys=True
            )
        )
        return 0

    print(
        f"unknown command {command!r}; expected documents, publish or verify",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
