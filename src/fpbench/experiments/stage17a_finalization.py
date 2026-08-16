"""The five documents, the marker, and the refusals that shape both.

Two writes, in the shape every stage since 8D has used: ``documents`` derives the
readable files and commits them, ``publish`` writes the marker over evidence that
already exists in Git.

The one property this stage's marker enforces beyond the usual: a marker may not
record a score direction, a score type or an execution when
:data:`stage17a_identity.OUTCOME_SCORE_CONTRACT_FAIL` is the outcome. The
temptation here is specific and worth blocking in code — the package *does*
compute a similarity ratio, it is obviously higher-is-more-similar, and writing
that down would be describing a number the package never publishes
(docs/adr/0133).
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
from fpbench.core.stage17a_errors import Stage17AFinalizationError
from fpbench.experiments import stage17a_identity as frozen
from fpbench.experiments import stage17a_score_contract as gate

__all__ = [
    "build_artifact_identity_document",
    "build_score_contract_document",
    "build_upstream_route_document",
    "build_stage17a_finalization",
    "stage17a_finalization_fingerprint",
    "stage17a_source_fingerprint",
    "publish_stage17a_evidence",
    "publish_stage17a_finalization",
    "verify_stage17a_evidence",
    "main",
]

_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/stage17a_errors.py",
    "src/fpbench/experiments/stage17a_identity.py",
    "src/fpbench/experiments/stage17a_acquire.py",
    "src/fpbench/experiments/stage17a_score_contract.py",
    "src/fpbench/experiments/stage17a_finalization.py",
)

_NOT_REACHED = "NOT_REACHED"


# --------------------------------------------------------------- the documents


def build_artifact_identity_document(*, repository_root: Path) -> dict[str, Any]:
    return gate.inspect_artifacts(repository_root=repository_root).as_document()


def build_score_contract_document(*, repository_root: Path) -> dict[str, Any]:
    return gate.read_score_contract(repository_root=repository_root).as_document()


def build_upstream_route_document(*, reached: bool) -> dict[str, Any]:
    """G3 — the route, which is only a question once there is a number at its end."""
    document: dict[str, Any] = {
        "schema": "stage_17a_upstream_route_v1",
        "gate": frozen.GATES["G3"],
        "gate_state": "PASS" if reached else _NOT_REACHED,
        "candidate_id": frozen.CANDIDATE_ID,
        "route_would_have_to_be": [
            "image1, image2",
            "package preprocessing",
            "feature extraction",
            "matching",
            "raw scalar",
        ],
        "fpbench_refuses_to_add": list(frozen.REFUSED_FPBENCH_STEPS),
    }
    if not reached:
        document["why_not_reached"] = (
            "the route gate asks whether every step from an image to a scalar "
            "belongs to upstream. G2 established that there is no scalar at the "
            "end of it, and a route to a number that does not exist is not a "
            "route with a gap in it"
        )
        document["observed_without_being_a_gate_conclusion"] = {
            "note": (
                "the entry point does decode both images with cv2.imread and "
                "build SIFT features itself, so fpbench would not have had to "
                "supply preprocessing. That is recorded because it is true, and "
                "it does not rescue the stage"
            )
        }
    return document


# ------------------------------------------------------------------ the marker


def stage17a_source_fingerprint(repository_root: Path) -> str:
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage17AFinalizationError(
                f"a Stage 17A source file is missing: {relative}"
            )
        digests[relative] = _file_sha256(path)
    return stable_hash({"schema": "stage_17a_source_v1", "files": digests}, length=64)


def stage17a_finalization_fingerprint(marker: Mapping[str, Any]) -> str:
    payload = {
        k: v for k, v in marker.items() if k != "stage_17a_finalization_fingerprint"
    }
    return stable_hash(payload, length=64)


def build_stage17a_finalization(
    *,
    repository_root: Path,
    artifact_document: Mapping[str, Any],
    score_document: Mapping[str, Any],
    route_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the marker, and refuse to assemble one the evidence does not support."""
    root = Path(repository_root)
    artifact_state = artifact_document.get("gate_state")
    score_state = score_document.get("gate_state")
    complete = artifact_state == "PASS" and score_state == "PASS"
    outcome = (
        frozen.OUTCOME_COMPLETE if complete else frozen.OUTCOME_SCORE_CONTRACT_FAIL
    )

    gate_states = {
        frozen.GATES["G1"]: artifact_state,
        frozen.GATES["G2"]: score_state,
        frozen.GATES["G3"]: route_document.get("gate_state"),
        frozen.GATES["G4"]: _NOT_REACHED if not complete else "PASS",
        frozen.GATES["G5"]: _NOT_REACHED if not complete else "PASS",
        frozen.GATES["G6"]: _NOT_REACHED if not complete else "PASS",
        frozen.GATES["G7"]: _NOT_REACHED if not complete else "PASS",
    }
    if complete and any(state != "PASS" for state in gate_states.values()):
        raise Stage17AFinalizationError(
            "a complete outcome was assembled over a gate that did not pass"
        )
    if not complete and score_document.get("score_direction") is not None:
        raise Stage17AFinalizationError(
            "the score contract failed, so no score direction may be published: "
            "the package computes a ratio and does not return it, and writing a "
            "direction down would describe a number it never publishes"
        )

    marker: dict[str, Any] = {
        "kind": "stage_17a_finalization",
        "schema_version": "1",
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_id": frozen.CANDIDATE_ID,
        "display_name": frozen.DISPLAY_NAME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "package": frozen.PACKAGE_REQUIREMENT,
        "implementation_version": frozen.PACKAGE_VERSION,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "license": frozen.LICENSE,
        "runtime_artifact_sha256": frozen.RUNTIME_ARTIFACT_SHA256,
        "source_artifact_sha256": frozen.SOURCE_ARTIFACT_SHA256,
        "module_sha256": frozen.MODULE_SHA256,
        "authority_is_the_distribution": frozen.AUTHORITY_IS_THE_DISTRIBUTION,
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
        "blocker": None if complete else score_document.get("blocker"),
        "immediate_stop_conditions": list(frozen.IMMEDIATE_STOP_CONDITIONS),
        "entry_point": frozen.ENTRY_QUALNAME,
        "returns_native_scalar_before_decision": bool(
            score_document.get("returns_native_scalar_before_decision")
        ),
        "score_direction_provable_from_source": bool(
            score_document.get("score_direction_provable_from_source")
        ),
        "score_direction": None if not complete else "HIGHER_MORE_SIMILAR",
        "internal_decision_thresholds": list(
            (score_document.get("findings") or {}).get(
                "internal_decision_thresholds", []
            )
        ),
        # ------------------------------------------------------ what this opens
        "algorithm_5_established": complete,
        "reopens_algorithm_5_search": not complete,
        "opens_common_calibration": complete,
        "calibration_roster": [] if not complete else [
            "sourceafis",
            "nbis",
            "flx",
            "verifinger_1to1",
            frozen.CANDIDATE_ID,
        ],
        "fallback_candidate": None,
        # ------------------------------------------------------- what did not run
        "package_installed": False,
        "package_executed": False,
        "adapter_frozen": complete,
        "sd300_images_opened": 0,
        "canonical_run_executed": complete,
        "stored_outcomes": 0,
        # ------------------------------------------------------------ the denials
        "score_reconstructed_by_fpbench": False,
        "stdout_parsed_for_a_score": False,
        "upstream_function_reimplemented": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "score_statistics_published": False,
        "algorithm_ranking_published": False,
        "prior_algorithm_scores_consulted": False,
        "third_party_bytes_added_to_git": False,
        "absolute_paths_in_evidence": False,
        # ------------------------------------------------------------ provenance
        "bound_markers": [dict(record) for record in frozen.BOUND_MARKERS],
        "stage17a_source_fingerprint": stage17a_source_fingerprint(root),
        "evidence_content_hashes": _evidence_content_hashes(root),
        "source_commit": _head_commit(root),
        "source_tree_clean": _tree_is_clean(root),
        "created_utc": _utc_now(),
    }

    if not complete:
        marker["why_not_complete"] = (
            "match_fingerprints returns nothing. Its own docstring declares "
            "Returns: None, it contains no return statement carrying a value, "
            "and its only observable is printed text. The similarity ratio it "
            "computes is compared against a hard-coded 0.95 and discarded, so "
            "what the package publishes is a decision on somebody else's "
            "threshold rather than a raw score. Recovering the ratio would mean "
            "re-implementing the function or scraping stdout, and both make "
            "fpbench the author of the number (docs/adr/0133)"
        )

    marker["stage_17a_finalization_fingerprint"] = stage17a_finalization_fingerprint(
        marker
    )
    return marker


def _last_reached(gate_states: Mapping[str, Any]) -> str:
    reached = [
        gate_name
        for key in frozen.GATE_ORDER
        for gate_name in (frozen.GATES[key],)
        if gate_states.get(gate_name) != _NOT_REACHED
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


def publish_stage17a_evidence(*, repository_root: Path) -> dict[str, Path]:
    root = Path(repository_root)
    directory = _evidence_directory(root)
    artifact_document = build_artifact_identity_document(repository_root=root)
    score_document = build_score_contract_document(repository_root=root)
    reached = (
        artifact_document.get("gate_state") == "PASS"
        and score_document.get("gate_state") == "PASS"
    )
    documents = {
        "artifact-identity.json": artifact_document,
        "score-contract.json": score_document,
        "upstream-route.json": build_upstream_route_document(reached=reached),
    }
    written: dict[str, Path] = {}
    for name, document in documents.items():
        path = directory / name
        _write_json(path, document)
        written[name] = path
    _require_no_forbidden_published_data(directory)
    return written


def publish_stage17a_finalization(*, repository_root: Path) -> Path:
    root = Path(repository_root)
    directory = _evidence_directory(root)
    for name in frozen.EVIDENCE_DOCUMENTS:
        if name == frozen.STAGE_17A_FINALIZATION_NAME:
            continue
        if not (directory / name).is_file():
            raise Stage17AFinalizationError(
                f"{name} is not published yet; run the documents step and commit "
                "it before writing a marker"
            )

    def _read(name: str) -> dict[str, Any]:
        return json.loads((directory / name).read_text(encoding="utf-8"))

    marker = build_stage17a_finalization(
        repository_root=root,
        artifact_document=_read("artifact-identity.json"),
        score_document=_read("score-contract.json"),
        route_document=_read("upstream-route.json"),
    )
    path = directory / frozen.STAGE_17A_FINALIZATION_NAME
    _write_json(path, marker)
    return path


def verify_stage17a_evidence(*, repository_root: Path) -> dict[str, Any]:
    """Re-derive what committed evidence alone can re-derive."""
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
        raise Stage17AFinalizationError(
            f"the Stage 17A evidence is incomplete: {', '.join(missing)}"
        )

    marker = json.loads(
        (directory / frozen.STAGE_17A_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    recomputed = stage17a_finalization_fingerprint(marker)
    if recomputed != marker.get("stage_17a_finalization_fingerprint"):
        raise Stage17AFinalizationError(
            "the marker's fingerprint does not match its own contents"
        )
    if marker.get("outcome") not in frozen.OUTCOMES:
        raise Stage17AFinalizationError(
            f"{marker.get('outcome')!r} is not a Stage 17A outcome"
        )

    score = json.loads((directory / "score-contract.json").read_text(encoding="utf-8"))
    if score.get("returns_native_scalar_before_decision") != (
        score.get("gate_state") == "PASS"
    ):
        raise Stage17AFinalizationError(
            "the score contract's gate state disagrees with its own finding"
        )
    if score.get("gate_state") != "PASS":
        if score.get("score_direction") is not None:
            raise Stage17AFinalizationError(
                "a score direction is published for a package that returns no score"
            )
        if marker.get("algorithm_5_established"):
            raise Stage17AFinalizationError(
                "the marker establishes Algorithm 5 over a failed score contract"
            )
        for denial in (
            "score_reconstructed_by_fpbench",
            "stdout_parsed_for_a_score",
            "upstream_function_reimplemented",
        ):
            if marker.get(denial):
                raise Stage17AFinalizationError(
                    f"the marker admits {denial}, which this stage refuses"
                )

    observed = _evidence_content_hashes(root)
    recorded = marker.get("evidence_content_hashes") or {}
    drifted = sorted(
        name for name, digest in recorded.items() if observed.get(name) != digest
    )
    if drifted:
        raise Stage17AFinalizationError(
            "published evidence has changed since the marker was written: "
            + ", ".join(drifted)
        )

    _require_no_forbidden_published_data(directory)
    findings["outcome"] = marker["outcome"]
    findings["blocker"] = marker.get("blocker")
    findings["gate_reached_last"] = marker.get("gate_reached_last")
    findings["documents_verified"] = len(frozen.EVIDENCE_DOCUMENTS)
    findings["algorithm_5_established"] = marker.get("algorithm_5_established")
    findings["stage_17a_finalization_fingerprint"] = recomputed
    return findings


# --------------------------------------------------------------------- helpers


def _require_no_forbidden_published_data(directory: Path) -> None:
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        offending = sorted(
            key for key in _forbidden_keys(document) if not _is_denial(document, key)
        )
        if offending:
            raise Stage17AFinalizationError(
                f"{path.name} carries decision-shaped keys: {', '.join(offending)}"
            )
        text = path.read_text(encoding="utf-8")
        for absolute in ("C:\\\\", "C:/", "/home/", "/Users/"):
            if absolute in text:
                raise Stage17AFinalizationError(
                    f"{path.name} carries an absolute machine path"
                )


def _is_denial(document: Any, key: str) -> bool:
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
        value is False or value in (None, "NONE", "none", 0, []) for value in values
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
        if name == frozen.STAGE_17A_FINALIZATION_NAME:
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
        written = publish_stage17a_evidence(repository_root=root)
        for name in sorted(written):
            print(f"wrote {frozen.EVIDENCE_DIRECTORY.as_posix()}/{name}")
        print("\nWrite the README, commit these, then run `publish`.")
        return 0

    if command == "publish":
        path = publish_stage17a_finalization(repository_root=root)
        marker = json.loads(path.read_text(encoding="utf-8"))
        print(f"wrote {path.as_posix()}")
        print(f"outcome              {marker['outcome']}")
        print(f"blocker              {marker['blocker']}")
        print(f"last gate reached    {marker['gate_reached_last']}")
        print(f"algorithm 5          {marker['algorithm_5_established']}")
        return 0

    if command == "verify":
        print(
            json.dumps(
                verify_stage17a_evidence(repository_root=root), indent=2, sort_keys=True
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
