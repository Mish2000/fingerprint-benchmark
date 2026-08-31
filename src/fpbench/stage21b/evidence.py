"""Publish and verify non-score Stage 21B receipts after all six seals exist."""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.evidence_sanitisation import find_absolute_paths
from fpbench.core.json_io import publish_evidence_document
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.bindings import (
    Stage21ABinding,
    load_frozen_pairs,
    load_stage21a_binding,
    verify_legacy_manifest_unchanged,
)
from fpbench.stage21b.constants import (
    EXECUTION_POLICY_PATH,
    EXPECTED_METHODS,
    EXPECTED_PAIRS_PER_METHOD,
    EXPECTED_PAIRS_PER_RELEASE,
    EXPECTED_RELEASES,
    EXPECTED_TOTAL_ATTEMPTS,
    FUTURE_TEST_RELEASE,
    LEGACY_PAIR_COUNT,
    LEGACY_PAIR_MANIFEST_HASH,
    OUTCOME,
    PREPARATION_PROFILE_ID,
    PREPARATION_SET_ID,
    STAGE21B_EVIDENCE,
    STAGE21B_MARKER,
)
from fpbench.stage21b.errors import Stage21BIntegrityError
from fpbench.stage21b.integrity import (
    audit_cross_method_alignment,
    discover_authoritative_run_directories,
    verify_sealed_run_directory,
)
from fpbench.stage21b.models import FrozenRunSpec
from fpbench.stage21b.policy import load_execution_policy
from fpbench.stage21b.source_freeze import (
    execution_source_file_sha256s,
    source_file_sha256,
)


def run_contract_suite(repository_root: Path) -> dict[str, Any]:
    """Run only synthetic/contract and frozen-identity regression tests."""
    root = Path(repository_root).resolve()
    targets = [
        "tests/stage21b",
        "tests/regression/test_stage21b_regression.py",
    ]
    completed = subprocess.run(
        (sys.executable, "-m", "pytest", *targets, "-q"),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode:
        tail = "\n".join(completed.stdout.splitlines()[-30:])
        raise Stage21BIntegrityError(f"Stage 21B contract suite failed:\n{tail}")
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_contract_test_attestation",
        "command": ["python", "-m", "pytest", *targets, "-q"],
        "synthetic_only": True,
        "sd300_matcher_attempts": 0,
        "vendor_sdk_required": False,
        "contract_tests_pass": True,
        "regression_tests_pass": True,
        "completed_utc": _utc_now(),
    }


def publish_stage21b_evidence(
    *,
    repository_root: Path,
    workspace: Path,
    evidence_directory: Path | None = None,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    directory = (
        Path(evidence_directory).resolve()
        if evidence_directory is not None
        else root / STAGE21B_EVIDENCE
    )
    marker_path = directory / STAGE21B_MARKER
    if marker_path.is_file():
        return verify_stage21b_evidence(root, evidence_directory=directory)
    # The finalizer obtains its own test evidence.  Accepting a caller-supplied
    # PASS mapping would make the contract gate an assertion rather than a
    # check.  Tests replace ``run_contract_suite`` at this read boundary.
    test_attestation = run_contract_suite(root)
    if test_attestation.get("contract_tests_pass") is not True or test_attestation.get(
        "regression_tests_pass"
    ) is not True:
        raise Stage21BIntegrityError("publication requires passing contract/regression tests")
    if test_attestation.get("sd300_matcher_attempts") != 0:
        raise Stage21BIntegrityError("contract tests must not run SD300 matchers")

    stage21a = load_stage21a_binding(root, require_predecessor_files=True)
    policy = load_execution_policy(root / EXECUTION_POLICY_PATH)
    policy.require_roster_adapters(stage21a.adapter_ids)
    run_dirs = discover_authoritative_run_directories(
        workspace, stage21a.algorithm_ids
    )
    frozen_pairs = load_frozen_pairs(workspace=workspace, binding=stage21a)
    legacy = verify_legacy_manifest_unchanged(
        workspace=workspace, binding=stage21a
    )
    verified: dict[str, dict[str, Any]] = {}
    specs: dict[str, FrozenRunSpec] = {}
    source_bindings: dict[str, dict[str, Any]] = {}
    for algorithm in stage21a.algorithms:
        result = verify_sealed_run_directory(
            run_dirs[algorithm.algorithm_id], require_production_shape=True
        )
        spec = result.pop("spec")
        result.pop("seal")
        _require_spec_binding(spec, stage21a, algorithm)
        source_binding = _json(run_dirs[algorithm.algorithm_id] / "execution-source-binding.json")
        _verify_source_binding(root, spec, source_binding)
        verified[algorithm.algorithm_id] = result
        specs[algorithm.algorithm_id] = spec
        source_bindings[algorithm.algorithm_id] = source_binding

    alignment = audit_cross_method_alignment(
        run_dirs,
        expected_algorithm_ids=stage21a.algorithm_ids,
        require_production_shape=True,
        expected_pair_manifest_hash=stage21a.pair_manifest_hash,
        expected_pair_ids_sha256=stage21a.pair_ids_sha256,
        expected_manifest_pairs=frozen_pairs.pairs,
        expected_preparation_set_id=PREPARATION_SET_ID,
        expected_preparation_profile_id=PREPARATION_PROFILE_ID,
    )
    if alignment["future_sd300b_pair_ids_sha256"] in (None, ""):
        raise Stage21BIntegrityError("future SD300B identity was not derived")
    documents: dict[str, dict[str, Any]] = {}
    documents["stage21a-binding.json"] = _stage21a_document(stage21a)
    documents["execution-roster.json"] = _roster_document(stage21a, specs)
    documents["pair-manifest-binding.json"] = _pair_document(stage21a, legacy)
    documents["prepared-input-binding.json"] = _prepared_document(specs)
    documents["execution-policy.json"] = _policy_document(policy, root)
    documents["runtime-bindings.json"] = _runtime_document(stage21a, specs)
    documents["result-integrity.json"] = {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_result_integrity",
        "method_count": len(verified),
        "methods": [verified[key] for key in stage21a.algorithm_ids],
        "all_result_sets_sealed": True,
        "all_integrity_gates_pass": True,
        "raw_score_contract_checked": True,
        "score_summaries_computed": False,
    }
    documents["cross-method-alignment.json"] = alignment
    documents["future-challenger-binding.json"] = {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_future_challenger_binding",
        "release": FUTURE_TEST_RELEASE,
        "pair_count": EXPECTED_PAIRS_PER_RELEASE,
        "pair_ids_sha256": alignment["future_sd300b_pair_ids_sha256"],
        "same_pairs_in_every_baseline_result_set": True,
        "future_lane": "native_1000ppi_or_higher",
        "baseline_lane": "canonical500",
        "future_method_development_started": False,
        "reservation_fingerprint": stage21a.high_resolution_reservation_fingerprint,
    }
    documents["no-evaluation-audit.json"] = _no_evaluation_document(root)
    documents["contract-test-attestation.json"] = dict(test_attestation)

    for algorithm_id in stage21a.algorithm_ids:
        relative = f"method-runs/{algorithm_id}.json"
        documents[relative] = _method_receipt(
            verified[algorithm_id], specs[algorithm_id], source_bindings[algorithm_id]
        )

    if not (directory / "README.md").is_file():
        raise Stage21BIntegrityError("Stage 21B evidence README is missing")
    for relative, document in documents.items():
        publish_evidence_document(directory / relative, document)

    content_hashes = {"README.md": _sha256(directory / "README.md")}
    content_hashes.update(
        {relative: _sha256(directory / relative) for relative in sorted(documents)}
    )
    methods = [
        {
            "algorithm_id": algorithm_id,
            "run_id": specs[algorithm_id].run_id,
            "result_set_id": specs[algorithm_id].result_set_id,
            "result_set_fingerprint": verified[algorithm_id][
                "result_set_fingerprint"
            ],
            "planned_attempts": verified[algorithm_id]["planned_attempts"],
            "terminal_outcomes": verified[algorithm_id]["terminal_outcomes"],
            "score_bearing_outcomes": verified[algorithm_id][
                "score_bearing_outcomes"
            ],
            "algorithm_failures": verified[algorithm_id]["algorithm_failures"],
            "runtime_identity_fingerprint": specs[
                algorithm_id
            ].runtime_identity_fingerprint,
            "execution_source_fingerprint": specs[
                algorithm_id
            ].execution_source_fingerprint,
        }
        for algorithm_id in stage21a.algorithm_ids
    ]
    conditions = {
        "accepted_stage21a_bound": True,
        "frozen_roster_bound": True,
        "all_six_methods_completed": True,
        "all_result_sets_sealed": True,
        "all_pair_sets_identical": True,
        "canonical500_binding_valid": True,
        "cross_subject_manifest_exact": True,
        "legacy_manifest_unchanged": True,
        "complete_terminal_coverage": True,
        "raw_score_contract_valid": True,
        "failure_semantics_preserved": True,
        "infrastructure_gaps_zero": True,
        "runtime_and_provenance_bound": True,
        "future_sd300b_binding_preserved": True,
        "contract_tests_pass": True,
        "regression_tests_pass": True,
        "source_and_evidence_integrity_valid": True,
        "no_evaluation_performed": True,
    }
    marker: dict[str, Any] = {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_finalization",
        "outcome": OUTCOME,
        "stage21a_finalization_fingerprint": stage21a.finalization_fingerprint,
        "stage21a_source_fingerprint": stage21a.source_fingerprint,
        "roster_id": stage21a.roster_id,
        "roster_size": EXPECTED_METHODS,
        "planned_pairs_per_method": EXPECTED_PAIRS_PER_METHOD,
        "planned_total_attempts": EXPECTED_TOTAL_ATTEMPTS,
        "methods_completed": EXPECTED_METHODS,
        "all_result_sets_sealed": True,
        "all_pair_sets_identical": True,
        "canonical500_binding_valid": True,
        "cross_subject_manifest_hash": stage21a.pair_manifest_hash,
        "legacy_manifest_unchanged": True,
        "legacy_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "accepted_legacy_result_identities_fingerprint": (
            stage21a.accepted_legacy_result_identities_fingerprint
        ),
        "metrics_computed": False,
        "tar_computed": False,
        "far_computed": False,
        "frr_computed": False,
        "score_sweep_performed": False,
        "threshold_selected": False,
        "calibration_performed": False,
        "score_normalization_performed": False,
        "ranking_performed": False,
        "algorithm_tuning_performed": False,
        "pair_filtering_performed": False,
        "methods": methods,
        "conditions": conditions,
        "failed_conditions": [],
        "evidence_content_hashes": content_hashes,
        "created_utc": _utc_now(),
    }
    marker["stage_21b_finalization_fingerprint"] = _canonical_json_hash(marker)
    # Validate the complete non-score publication while the PASS marker is
    # still absent.  A publisher defect must leave an incomplete evidence
    # directory, never a marker that only a subsequent verification discovers
    # to be invalid.
    committed_receipts = {
        algorithm_id: _json(directory / f"method-runs/{algorithm_id}.json")
        for algorithm_id in sorted(stage21a.algorithm_ids)
    }
    for receipt in committed_receipts.values():
        _verify_committed_source_receipt(root, receipt)
    _verify_committed_document_set(
        repository_root=root,
        directory=directory,
        marker=marker,
        stage21a=stage21a,
        receipts=committed_receipts,
    )
    _verify_no_evaluation_document(_json(directory / "no-evaluation-audit.json"))
    publish_evidence_document(marker_path, marker)
    return verify_stage21b_evidence(root, evidence_directory=directory)


def verify_stage21b_evidence(
    repository_root: Path, *, evidence_directory: Path | None = None
) -> dict[str, Any]:
    """Verify committed receipts without SD300, raw result stores, or SDKs.

    ``evidence_directory`` defaults to the committed one and is overridden only
    by the round-trip test, which must not write into the repository's evidence
    tree to find out whether the publisher and this verifier agree.
    """
    root = Path(repository_root).resolve()
    directory = (
        Path(evidence_directory) if evidence_directory is not None
        else root / STAGE21B_EVIDENCE
    )
    marker = _json(directory / STAGE21B_MARKER)
    fingerprint = marker.get("stage_21b_finalization_fingerprint")
    body = dict(marker)
    body.pop("stage_21b_finalization_fingerprint", None)
    if fingerprint != _canonical_json_hash(body):
        raise Stage21BIntegrityError("Stage 21B finalization fingerprint is invalid")
    if marker.get("outcome") != OUTCOME or marker.get("stage") != "21B":
        raise Stage21BIntegrityError("Stage 21B evidence is not a final PASS")
    if marker.get("roster_size") != EXPECTED_METHODS:
        raise Stage21BIntegrityError("Stage 21B final roster size changed")
    if marker.get("planned_pairs_per_method") != EXPECTED_PAIRS_PER_METHOD:
        raise Stage21BIntegrityError("Stage 21B planned pair count changed")
    if marker.get("planned_total_attempts") != EXPECTED_TOTAL_ATTEMPTS:
        raise Stage21BIntegrityError("Stage 21B total attempt count changed")
    conditions = marker.get("conditions")
    if not isinstance(conditions, Mapping) or not conditions or not all(conditions.values()):
        raise Stage21BIntegrityError("Stage 21B finalization has a failed condition")
    for name in (
        "metrics_computed",
        "tar_computed",
        "far_computed",
        "frr_computed",
        "score_sweep_performed",
        "threshold_selected",
        "calibration_performed",
        "score_normalization_performed",
        "ranking_performed",
        "algorithm_tuning_performed",
        "pair_filtering_performed",
    ):
        if marker.get(name) is not False:
            raise Stage21BIntegrityError(f"Stage 21B finalization violates {name}=false")

    hashes = marker.get("evidence_content_hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        raise Stage21BIntegrityError("Stage 21B evidence content hashes are missing")
    stage21a = load_stage21a_binding(root, require_predecessor_files=False)
    if marker.get("stage21a_finalization_fingerprint") != stage21a.finalization_fingerprint:
        raise Stage21BIntegrityError("Stage 21A binding changed")
    expected_method_files = {
        f"method-runs/{algorithm_id}.json" for algorithm_id in stage21a.algorithm_ids
    }
    required_documents = {
        "README.md",
        "stage21a-binding.json",
        "execution-roster.json",
        "pair-manifest-binding.json",
        "prepared-input-binding.json",
        "execution-policy.json",
        "runtime-bindings.json",
        "result-integrity.json",
        "cross-method-alignment.json",
        "future-challenger-binding.json",
        "no-evaluation-audit.json",
        "contract-test-attestation.json",
        *expected_method_files,
    }
    if set(map(str, hashes)) != required_documents:
        raise Stage21BIntegrityError(
            "Stage 21B evidence hash closure does not contain exactly the required documents"
        )
    for relative, expected in hashes.items():
        if not _is_digest(expected) or _sha256(directory / str(relative)) != expected:
            raise Stage21BIntegrityError(f"Stage 21B evidence changed: {relative}")
    actual_documents = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != STAGE21B_MARKER
    }
    if actual_documents != required_documents:
        raise Stage21BIntegrityError("Stage 21B evidence directory contains an unbound file")
    if any(directory.rglob("*.parquet")) or any(directory.rglob("*.sqlite3")):
        raise Stage21BIntegrityError("raw result stores must not be copied into evidence")

    actual_method_files = {
        path.relative_to(directory).as_posix()
        for path in (directory / "method-runs").glob("*.json")
    }
    if actual_method_files != expected_method_files:
        raise Stage21BIntegrityError("Stage 21B method receipts do not exactly match roster")
    receipts: dict[str, dict[str, Any]] = {}
    for relative in sorted(expected_method_files):
        receipt = _json(directory / relative)
        _verify_committed_source_receipt(root, receipt)
        if any(
            _contains_key(receipt, key)
            for key in ("raw_score", "raw_score_hex", "raw_scores", "score_values")
        ):
            raise Stage21BIntegrityError("method evidence contains raw score values")
        receipts[str(receipt.get("algorithm_id"))] = receipt
    _verify_committed_document_set(
        repository_root=root,
        directory=directory,
        marker=marker,
        stage21a=stage21a,
        receipts=receipts,
    )

    no_eval = _json(directory / "no-evaluation-audit.json")
    _verify_no_evaluation_document(no_eval)
    alignment = _json(directory / "cross-method-alignment.json")
    if alignment.get("alignment_pass") is not True:
        raise Stage21BIntegrityError("cross-method alignment is not PASS")
    if alignment.get("raw_score_column_loaded") is not False:
        raise Stage21BIntegrityError("alignment loaded score values")
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".md"}:
            value: Any = (
                _json(path) if path.suffix.lower() == ".json" else path.read_text(encoding="utf-8")
            )
            leaks = find_absolute_paths(value, path=path.name)
            if leaks:
                raise Stage21BIntegrityError(f"evidence contains an absolute path: {path}")
    return marker


def _verify_committed_document_set(
    *,
    repository_root: Path,
    directory: Path,
    marker: Mapping[str, Any],
    stage21a: Stage21ABinding,
    receipts: Mapping[str, Mapping[str, Any]],
) -> None:
    expected_ids = stage21a.algorithm_ids
    if tuple(receipts) != tuple(sorted(expected_ids)) or set(receipts) != set(expected_ids):
        raise Stage21BIntegrityError("method receipt identities do not match the roster")
    expected_release_counts = {
        release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES
    }

    stage21a_document = _json(directory / "stage21a-binding.json")
    expected_stage21a = {
        "accepted_outcome": "FINAL_BASELINE_EVALUATION_PROTOCOL_READY",
        "stage21a_finalization_fingerprint": stage21a.finalization_fingerprint,
        "stage21a_source_fingerprint": stage21a.source_fingerprint,
        "roster_fingerprint": stage21a.roster_fingerprint,
        "protocol_config_fingerprint": stage21a.protocol_config_sha256,
        "cross_subject_pair_manifest_fingerprint": stage21a.pair_manifest_hash,
        "high_resolution_reservation_fingerprint": (
            stage21a.high_resolution_reservation_fingerprint
        ),
        "accepted_legacy_result_identities_fingerprint": (
            stage21a.accepted_legacy_result_identities_fingerprint
        ),
    }
    _require_values(stage21a_document, expected_stage21a, "Stage 21A receipt")

    pair = _json(directory / "pair-manifest-binding.json")
    _require_values(
        pair,
        {
            "protocol_id": stage21a.pair_binding["protocol_id"],
            "population": stage21a.pair_binding["population"],
            "pair_manifest_hash": stage21a.pair_manifest_hash,
            "pair_ids_sha256": stage21a.pair_ids_sha256,
            "pair_count": EXPECTED_PAIRS_PER_METHOD,
            "release_counts": expected_release_counts,
            "ground_truth": "NON_MATED",
            "exhaustive": True,
            "sampling_performed": False,
            "legacy_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
            "accepted_legacy_result_identities_fingerprint": (
                stage21a.accepted_legacy_result_identities_fingerprint
            ),
        },
        "pair-manifest receipt",
    )
    # The legacy half of the claim is re-read from the local store at
    # publication; here — where there is no workspace — the committed receipt
    # is held against the accepted Stage 21A invariance document instead.
    _require_values(
        pair.get("legacy_manifest_reverified") or {},
        {
            "protocol_id": stage21a.legacy_binding["protocol_id"],
            "cohort_id": stage21a.legacy_binding["cohort_id"],
            "pair_count": LEGACY_PAIR_COUNT,
            "pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
            "pair_ids_sha256": stage21a.legacy_binding["pair_ids_sha256"],
            "reread_from_local_store": True,
            "accepted_legacy_result_identities": (
                stage21a.accepted_legacy_result_identities
            ),
            "accepted_legacy_result_identities_fingerprint": (
                stage21a.accepted_legacy_result_identities_fingerprint
            ),
        },
        "legacy manifest re-verification",
    )

    prepared = _json(directory / "prepared-input-binding.json")
    _require_values(
        prepared,
        {
            "preparation_set_id": PREPARATION_SET_ID,
            "preparation_profile_id": PREPARATION_PROFILE_ID,
            "effective_ppi": 500,
            "method_count": EXPECTED_METHODS,
            "canonical500_v2_created": False,
            "native_1000ppi_baseline_run": False,
        },
        "prepared-input receipt",
    )
    if not _is_digest(prepared.get("preparation_set_fingerprint")) or not _is_digest(
        prepared.get("preparation_profile_fingerprint")
    ):
        raise Stage21BIntegrityError("prepared-input fingerprints are invalid")

    policy = _json(directory / "execution-policy.json")
    _require_values(
        policy,
        {
            "execution_strategy": "sequential_single_worker",
            "concurrency": 1,
            "orchestrator_algorithm_retries": 0,
            "infrastructure_resume_allowed": True,
            "optimizations_enabled": False,
            "algorithm_failure_is_terminal": True,
            "algorithm_failure_score": None,
            "infrastructure_failure_is_biometric_outcome": False,
            "status_outputs_raw_scores": False,
            "metrics_allowed": False,
            "calibration_allowed": False,
            "threshold_allowed": False,
            "score_transform_allowed": False,
        },
        "execution-policy receipt",
    )
    _require_values(
        policy.get("prepared_input_verification") or {},
        {
            "every_planned_image_verified": True,
            "verification_memoised_per_image": True,
            "reverified_when_artefact_changes": True,
            "bytes_delivered_to_adapter_unchanged": True,
            "per_comparison_verification_in_frozen_route": False,
        },
        "prepared-input verification receipt",
    )
    policy_routes = policy.get("routes")
    if not isinstance(policy_routes, list) or [
        row.get("adapter_id") for row in policy_routes
    ] != list(stage21a.adapter_ids):
        raise Stage21BIntegrityError("execution-policy routes differ from the roster")
    policy_by_adapter = {str(row["adapter_id"]): row for row in policy_routes}
    for row in policy_routes:
        if (
            Path(str(row.get("algorithm_config", ""))).is_absolute()
            or not _is_digest(row.get("algorithm_config_sha256"))
            or not str(row.get("failure_classifier", "")).strip()
            or not isinstance(row.get("timeout_seconds"), (int, float))
            or isinstance(row.get("timeout_seconds"), bool)
            or float(row["timeout_seconds"]) <= 0
        ):
            raise Stage21BIntegrityError("execution-policy route binding is invalid")
        # The committed digest is re-derived from this checkout rather than
        # only cross-read against the method receipt: two documents agreeing
        # with each other is not evidence that either still describes the
        # algorithm configuration the run consumed.
        configured = (Path(repository_root) / str(row["algorithm_config"])).resolve()
        if not configured.is_file() or source_file_sha256(configured) != row[
            "algorithm_config_sha256"
        ]:
            raise Stage21BIntegrityError(
                f"algorithm execution config changed: {row['algorithm_config']}"
            )

    for algorithm in stage21a.algorithms:
        receipt = receipts[algorithm.algorithm_id]
        expected = {
            "algorithm_id": algorithm.algorithm_id,
            "adapter_id": algorithm.adapter_id,
            "implementation_version": algorithm.implementation_version,
            "integration_id": algorithm.integration_id,
            "score_direction": algorithm.score_direction,
            "predecessor_finalization_fingerprint": (
                algorithm.predecessor_finalization_fingerprint
            ),
            "planned_attempts": EXPECTED_PAIRS_PER_METHOD,
            "terminal_outcomes": EXPECTED_PAIRS_PER_METHOD,
            "infrastructure_gaps": 0,
            "release_counts": expected_release_counts,
            "stage21a_finalization_fingerprint": stage21a.finalization_fingerprint,
            "stage21a_source_fingerprint": stage21a.source_fingerprint,
            "high_resolution_reservation_fingerprint": (
                stage21a.high_resolution_reservation_fingerprint
            ),
            "roster_id": stage21a.roster_id,
            "roster_fingerprint": stage21a.roster_fingerprint,
            "protocol_id": stage21a.pair_binding["protocol_id"],
            "protocol_config_sha256": stage21a.protocol_config_sha256,
            "pair_manifest_hash": stage21a.pair_manifest_hash,
            "pair_ids_sha256": stage21a.pair_ids_sha256,
            "preparation_set_id": PREPARATION_SET_ID,
            "preparation_set_fingerprint": prepared[
                "preparation_set_fingerprint"
            ],
            "preparation_profile_id": PREPARATION_PROFILE_ID,
            "preparation_profile_fingerprint": prepared[
                "preparation_profile_fingerprint"
            ],
            "execution_strategy": "sequential_single_worker",
            "concurrency": 1,
            "orchestrator_algorithm_retries": 0,
            "infrastructure_resume_allowed": True,
            "metrics_allowed": False,
            "calibration_allowed": False,
            "threshold_allowed": False,
            "score_transform_allowed": False,
            "sealed": True,
            "integrity_pass": True,
            "score_summary_computed": False,
        }
        _require_values(receipt, expected, f"{algorithm.algorithm_id} receipt")
        route = policy_by_adapter[algorithm.adapter_id]
        _require_values(
            receipt,
            {
                "timeout_seconds": float(route["timeout_seconds"]),
                "algorithm_execution_config_sha256": route[
                    "algorithm_config_sha256"
                ],
            },
            f"{algorithm.algorithm_id} execution route",
        )
        scored = receipt.get("score_bearing_outcomes")
        failures = receipt.get("algorithm_failures")
        if type(scored) is not int or type(failures) is not int or scored + failures != EXPECTED_PAIRS_PER_METHOD:
            raise Stage21BIntegrityError(
                f"{algorithm.algorithm_id}: score/failure partition is invalid"
            )
        for key in (
            "run_spec_fingerprint",
            "result_set_fingerprint",
            "result_set_manifest_sha256",
            "result_set_manifest_fingerprint",
            "planned_pair_input_fingerprint",
            "preparation_set_fingerprint",
            "runtime_identity_fingerprint",
            "adapter_descriptor_fingerprint",
            "execution_source_fingerprint",
            "algorithm_execution_config_sha256",
            "private_adapter_config_sha256",
            "preparation_profile_fingerprint",
        ):
            if not _is_digest(receipt.get(key)):
                raise Stage21BIntegrityError(
                    f"{algorithm.algorithm_id}: receipt has invalid {key}"
                )
        assets = receipt.get("runtime_assets")
        if not isinstance(assets, list) or not assets or any(
            not isinstance(asset, Mapping)
            or not asset.get("role")
            or not _is_digest(asset.get("sha256"))
            or type(asset.get("size_bytes")) is not int
            or asset.get("size_bytes") < 1
            for asset in assets
        ):
            raise Stage21BIntegrityError(
                f"{algorithm.algorithm_id}: runtime-asset receipt is invalid"
            )
        orchestrator_runtime = receipt.get("orchestrator_runtime")
        if not isinstance(orchestrator_runtime, Mapping) or set(
            orchestrator_runtime
        ) != {
            "python_implementation",
            "python_version",
            "python_executable_identity",
            "platform_system",
            "platform_machine",
            "sqlite_version",
            "pyarrow_version",
        } or any(not str(value).strip() for value in orchestrator_runtime.values()):
            raise Stage21BIntegrityError(
                f"{algorithm.algorithm_id}: orchestrator runtime provenance is invalid"
            )

    roster = _json(directory / "execution-roster.json")
    runtime = _json(directory / "runtime-bindings.json")
    result_integrity = _json(directory / "result-integrity.json")
    roster_rows = roster.get("methods")
    runtime_rows = runtime.get("methods")
    integrity_rows = result_integrity.get("methods")
    if not all(isinstance(rows, list) for rows in (roster_rows, runtime_rows, integrity_rows)):
        raise Stage21BIntegrityError("roster/runtime/integrity method lists are malformed")
    if [row.get("algorithm_id") for row in roster_rows] != list(expected_ids):
        raise Stage21BIntegrityError("execution-roster order differs from Stage 21A")
    if [row.get("algorithm_id") for row in runtime_rows] != list(expected_ids):
        raise Stage21BIntegrityError("runtime-binding order differs from Stage 21A")
    if [row.get("algorithm_id") for row in integrity_rows] != list(expected_ids):
        raise Stage21BIntegrityError("result-integrity order differs from Stage 21A")
    _require_values(
        roster,
        {
            "roster_id": stage21a.roster_id,
            "roster_fingerprint": stage21a.roster_fingerprint,
            "method_count": EXPECTED_METHODS,
            "roster_selected_from_new_scores": False,
        },
        "execution roster",
    )
    _require_values(
        result_integrity,
        {
            "method_count": EXPECTED_METHODS,
            "all_result_sets_sealed": True,
            "all_integrity_gates_pass": True,
            "raw_score_contract_checked": True,
            "score_summaries_computed": False,
        },
        "result integrity",
    )
    for algorithm, roster_row, runtime_row in zip(
        stage21a.algorithms, roster_rows, runtime_rows, strict=True
    ):
        receipt = receipts[algorithm.algorithm_id]
        _require_values(
            roster_row,
            {
                "algorithm_id": algorithm.algorithm_id,
                "role": algorithm.role,
                "display_name": algorithm.display_name,
                "adapter_id": algorithm.adapter_id,
                "integration_id": algorithm.integration_id,
                "implementation_version": algorithm.implementation_version,
                "score_direction": algorithm.score_direction,
                "predecessor_finalization_fingerprint": (
                    algorithm.predecessor_finalization_fingerprint
                ),
                "run_spec_fingerprint": receipt["run_spec_fingerprint"],
            },
            f"{algorithm.algorithm_id} roster row",
        )
        _require_values(
            runtime_row,
            {
                "algorithm_id": algorithm.algorithm_id,
                "adapter_id": algorithm.adapter_id,
                "implementation_version": algorithm.implementation_version,
                "predecessor_finalization_fingerprint": (
                    algorithm.predecessor_finalization_fingerprint
                ),
                "adapter_descriptor_fingerprint": receipt[
                    "adapter_descriptor_fingerprint"
                ],
                "runtime_identity_fingerprint": receipt[
                    "runtime_identity_fingerprint"
                ],
                "assets": receipt["runtime_assets"],
                "orchestrator_runtime": receipt["orchestrator_runtime"],
            },
            f"{algorithm.algorithm_id} runtime row",
        )
    for row in integrity_rows:
        receipt = receipts[str(row["algorithm_id"])]
        for key in (
            "run_id",
            "result_set_id",
            "run_spec_fingerprint",
            "result_set_fingerprint",
            "planned_attempts",
            "terminal_outcomes",
            "score_bearing_outcomes",
            "algorithm_failures",
            "pair_manifest_hash",
            "pair_ids_sha256",
            "planned_pair_input_fingerprint",
            "preparation_set_id",
            "preparation_set_fingerprint",
            "preparation_profile_id",
        ):
            if row.get(key) != receipt.get(key):
                raise Stage21BIntegrityError(
                    f"{row['algorithm_id']}: integrity and method receipt disagree on {key}"
                )

    alignment = _json(directory / "cross-method-alignment.json")
    _require_values(
        alignment,
        {
            "method_count": EXPECTED_METHODS,
            "pair_count_per_method": EXPECTED_PAIRS_PER_METHOD,
            "release_counts_per_method": expected_release_counts,
            "future_sd300b_pair_count": EXPECTED_PAIRS_PER_RELEASE,
            "pair_manifest_hash": stage21a.pair_manifest_hash,
            "pair_ids_sha256": stage21a.pair_ids_sha256,
            "preparation_set_id": PREPARATION_SET_ID,
            "preparation_profile_id": PREPARATION_PROFILE_ID,
            "raw_score_column_loaded": False,
            "common_score_population_computed": False,
            "alignment_pass": True,
        },
        "cross-method alignment",
    )
    if not isinstance(alignment.get("gates"), Mapping) or not all(
        alignment["gates"].values()
    ):
        raise Stage21BIntegrityError("cross-method alignment contains a failed gate")
    if not _is_digest(alignment.get("future_sd300b_pair_ids_sha256")):
        raise Stage21BIntegrityError("future SD300B pair identity is invalid")
    alignment_methods = alignment.get("methods")
    if not isinstance(alignment_methods, list) or [
        row.get("algorithm_id") for row in alignment_methods
    ] != sorted(expected_ids):
        raise Stage21BIntegrityError("alignment method identities are invalid")
    for row in alignment_methods:
        receipt = receipts[str(row["algorithm_id"])]
        _require_values(
            row,
            {
                "run_id": receipt["run_id"],
                "result_set_id": receipt["result_set_id"],
                "result_set_fingerprint": receipt["result_set_fingerprint"],
            },
            f"{row['algorithm_id']} alignment row",
        )

    future = _json(directory / "future-challenger-binding.json")
    _require_values(
        future,
        {
            "release": FUTURE_TEST_RELEASE,
            "pair_count": EXPECTED_PAIRS_PER_RELEASE,
            "pair_ids_sha256": alignment["future_sd300b_pair_ids_sha256"],
            "same_pairs_in_every_baseline_result_set": True,
            "future_lane": "native_1000ppi_or_higher",
            "baseline_lane": "canonical500",
            "future_method_development_started": False,
            "reservation_fingerprint": stage21a.high_resolution_reservation_fingerprint,
        },
        "future-challenger receipt",
    )

    tests = _json(directory / "contract-test-attestation.json")
    _require_values(
        tests,
        {
            "synthetic_only": True,
            "sd300_matcher_attempts": 0,
            "vendor_sdk_required": False,
            "contract_tests_pass": True,
            "regression_tests_pass": True,
        },
        "contract-test attestation",
    )

    marker_methods = marker.get("methods")
    if not isinstance(marker_methods, list) or [
        row.get("algorithm_id") for row in marker_methods
    ] != list(expected_ids):
        raise Stage21BIntegrityError("final marker method list differs from the roster")
    for row in marker_methods:
        receipt = receipts[str(row["algorithm_id"])]
        for key in (
            "run_id",
            "result_set_id",
            "result_set_fingerprint",
            "planned_attempts",
            "terminal_outcomes",
            "score_bearing_outcomes",
            "algorithm_failures",
            "runtime_identity_fingerprint",
            "execution_source_fingerprint",
        ):
            if row.get(key) != receipt.get(key):
                raise Stage21BIntegrityError(
                    f"final marker and {row['algorithm_id']} receipt disagree on {key}"
                )
    _require_values(
        marker,
        {
            "methods_completed": EXPECTED_METHODS,
            "all_result_sets_sealed": True,
            "all_pair_sets_identical": True,
            "canonical500_binding_valid": True,
            "cross_subject_manifest_hash": stage21a.pair_manifest_hash,
            "legacy_manifest_unchanged": True,
            "legacy_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
            "accepted_legacy_result_identities_fingerprint": (
                stage21a.accepted_legacy_result_identities_fingerprint
            ),
            "failed_conditions": [],
        },
        "final marker",
    )
    expected_conditions = {
        "accepted_stage21a_bound",
        "frozen_roster_bound",
        "all_six_methods_completed",
        "all_result_sets_sealed",
        "all_pair_sets_identical",
        "canonical500_binding_valid",
        "cross_subject_manifest_exact",
        "legacy_manifest_unchanged",
        "complete_terminal_coverage",
        "raw_score_contract_valid",
        "failure_semantics_preserved",
        "infrastructure_gaps_zero",
        "runtime_and_provenance_bound",
        "future_sd300b_binding_preserved",
        "contract_tests_pass",
        "regression_tests_pass",
        "source_and_evidence_integrity_valid",
        "no_evaluation_performed",
    }
    if set(marker.get("conditions", {})) != expected_conditions:
        raise Stage21BIntegrityError("final marker condition vocabulary changed")


def _require_values(
    document: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    different = [
        key for key, value in expected.items() if document.get(key) != value
    ]
    if different:
        raise Stage21BIntegrityError(
            f"{label} differs on: " + ", ".join(different)
        )


def _require_spec_binding(spec: FrozenRunSpec, stage21a: Stage21ABinding, algorithm: Any) -> None:
    expected = {
        "stage21a_finalization_fingerprint": stage21a.finalization_fingerprint,
        "stage21a_source_fingerprint": stage21a.source_fingerprint,
        "high_resolution_reservation_fingerprint": stage21a.high_resolution_reservation_fingerprint,
        "roster_id": stage21a.roster_id,
        "roster_fingerprint": stage21a.roster_fingerprint,
        "algorithm_id": algorithm.algorithm_id,
        "adapter_id": algorithm.adapter_id,
        "integration_id": algorithm.integration_id,
        "implementation_version": algorithm.implementation_version,
        "predecessor_finalization_fingerprint": algorithm.predecessor_finalization_fingerprint,
        "score_direction": algorithm.score_direction,
        "pair_manifest_hash": stage21a.pair_manifest_hash,
        "pair_ids_sha256": stage21a.pair_ids_sha256,
        "pair_count": EXPECTED_PAIRS_PER_METHOD,
        "expected_attempts": EXPECTED_PAIRS_PER_METHOD,
        "preparation_set_id": PREPARATION_SET_ID,
        "preparation_profile_id": PREPARATION_PROFILE_ID,
    }
    different = [key for key, value in expected.items() if getattr(spec, key) != value]
    if different:
        raise Stage21BIntegrityError(
            f"{algorithm.algorithm_id}: frozen run binding differs: {', '.join(different)}"
        )
    if any(
        getattr(spec, name) is not False
        for name in (
            "metrics_allowed",
            "calibration_allowed",
            "threshold_allowed",
            "score_transform_allowed",
        )
    ):
        raise Stage21BIntegrityError("run specification allows evaluation logic")


def _stage21a_document(binding: Stage21ABinding) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_stage21a_binding",
        "accepted_outcome": "FINAL_BASELINE_EVALUATION_PROTOCOL_READY",
        "stage21a_finalization_fingerprint": binding.finalization_fingerprint,
        "stage21a_source_fingerprint": binding.source_fingerprint,
        "roster_fingerprint": binding.roster_fingerprint,
        "protocol_config_fingerprint": binding.protocol_config_sha256,
        "cross_subject_pair_manifest_fingerprint": binding.pair_manifest_hash,
        "high_resolution_reservation_fingerprint": binding.high_resolution_reservation_fingerprint,
        "accepted_legacy_result_identities_fingerprint": (
            binding.accepted_legacy_result_identities_fingerprint
        ),
    }


def _roster_document(
    binding: Stage21ABinding, specs: Mapping[str, FrozenRunSpec]
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_execution_roster",
        "roster_id": binding.roster_id,
        "roster_fingerprint": binding.roster_fingerprint,
        "method_count": len(binding.algorithms),
        "methods": [
            {
                "algorithm_id": item.algorithm_id,
                "role": item.role,
                "display_name": item.display_name,
                "adapter_id": item.adapter_id,
                "integration_id": item.integration_id,
                "implementation_version": item.implementation_version,
                "score_direction": item.score_direction,
                "predecessor_finalization_fingerprint": item.predecessor_finalization_fingerprint,
                "run_spec_fingerprint": specs[item.algorithm_id].run_spec_fingerprint,
            }
            for item in binding.algorithms
        ],
        "roster_selected_from_new_scores": False,
    }


def _pair_document(
    binding: Stage21ABinding, legacy: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_pair_manifest_binding",
        "protocol_id": binding.pair_binding["protocol_id"],
        "population": binding.pair_binding["population"],
        "pair_manifest_hash": binding.pair_manifest_hash,
        "pair_ids_sha256": binding.pair_ids_sha256,
        "pair_count": binding.pair_count,
        "release_counts": {
            release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES
        },
        "ground_truth": "NON_MATED",
        "exhaustive": True,
        "sampling_performed": False,
        "legacy_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "accepted_legacy_result_identities_fingerprint": (
            binding.accepted_legacy_result_identities_fingerprint
        ),
        "legacy_manifest_reverified": dict(legacy),
    }


def _prepared_document(specs: Mapping[str, FrozenRunSpec]) -> dict[str, Any]:
    first = next(iter(specs.values()))
    identities = {
        (
            spec.preparation_set_id,
            spec.preparation_set_fingerprint,
            spec.preparation_profile_id,
            spec.preparation_profile_fingerprint,
        )
        for spec in specs.values()
    }
    if len(identities) != 1:
        raise Stage21BIntegrityError("method preparation identities differ")
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_prepared_input_binding",
        "preparation_set_id": first.preparation_set_id,
        "preparation_set_fingerprint": first.preparation_set_fingerprint,
        "preparation_profile_id": first.preparation_profile_id,
        "preparation_profile_fingerprint": first.preparation_profile_fingerprint,
        "effective_ppi": 500,
        "method_count": len(specs),
        "canonical500_v2_created": False,
        "native_1000ppi_baseline_run": False,
    }


def _policy_document(policy: Any, root: Path) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_execution_policy",
        "policy_id": policy.policy_id,
        "execution_strategy": policy.execution_strategy,
        "concurrency": policy.concurrency,
        "orchestrator_algorithm_retries": policy.orchestrator_algorithm_retries,
        "infrastructure_resume_allowed": policy.infrastructure_resume_allowed,
        "optimizations_enabled": policy.optimizations_enabled,
        "algorithm_failure_is_terminal": True,
        "algorithm_failure_score": None,
        "infrastructure_failure_is_biometric_outcome": False,
        "status_outputs_raw_scores": False,
        "metrics_allowed": False,
        "calibration_allowed": False,
        "threshold_allowed": False,
        "score_transform_allowed": False,
        # Gate 21B-EQ1 asks what this stage does that its 6,000-comparison
        # predecessors did not.  The answer for the input lane is "nothing that
        # reaches a matcher": the certified routes verify a canonical artefact
        # when the preparation set is derived or verified, never once per
        # comparison, so memoising that check per image is parity with the
        # frozen route rather than a departure from it.
        "prepared_input_verification": {
            "every_planned_image_verified": True,
            "verification_memoised_per_image": True,
            "reverified_when_artefact_changes": True,
            "bytes_delivered_to_adapter_unchanged": True,
            "per_comparison_verification_in_frozen_route": False,
        },
        "routes": [
            {
                "adapter_id": adapter_id,
                "timeout_seconds": route.timeout_seconds,
                "failure_classifier": route.failure_classifier,
                "algorithm_config": route.algorithm_config.as_posix(),
                "algorithm_config_sha256": source_file_sha256(
                    Path(root) / route.algorithm_config
                ),
            }
            for adapter_id, route in policy.routes.items()
        ],
    }


def _runtime_document(
    binding: Stage21ABinding, specs: Mapping[str, FrozenRunSpec]
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_runtime_bindings",
        "methods": [
            {
                "algorithm_id": item.algorithm_id,
                "adapter_id": item.adapter_id,
                "implementation_version": item.implementation_version,
                "predecessor_finalization_fingerprint": item.predecessor_finalization_fingerprint,
                "adapter_descriptor_fingerprint": specs[
                    item.algorithm_id
                ].adapter_descriptor_fingerprint,
                "runtime_identity_fingerprint": specs[
                    item.algorithm_id
                ].runtime_identity_fingerprint,
                "assets": list(
                    _plain(
                        specs[item.algorithm_id].runtime_binding.get("assets", [])
                    )
                ),
                "orchestrator_runtime": _plain(
                    specs[item.algorithm_id].runtime_binding.get(
                        "orchestrator_runtime", {}
                    )
                ),
            }
            for item in binding.algorithms
        ],
    }


def _method_receipt(
    result: Mapping[str, Any], spec: FrozenRunSpec, source: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_method_run_receipt",
        "algorithm_id": spec.algorithm_id,
        "adapter_id": spec.adapter_id,
        "implementation_version": spec.implementation_version,
        "integration_id": spec.integration_id,
        "score_direction": spec.score_direction,
        "run_id": spec.run_id,
        "run_spec_fingerprint": spec.run_spec_fingerprint,
        "result_set_id": spec.result_set_id,
        "result_set_fingerprint": result["result_set_fingerprint"],
        "result_set_manifest_sha256": result["result_set_manifest_sha256"],
        "result_set_manifest_fingerprint": result[
            "result_set_manifest_fingerprint"
        ],
        "planned_attempts": result["planned_attempts"],
        "terminal_outcomes": result["terminal_outcomes"],
        "score_bearing_outcomes": result["score_bearing_outcomes"],
        "algorithm_failures": result["algorithm_failures"],
        "failure_classifications": result["failure_classifications"],
        "attempt_records": result["attempt_records"],
        "infrastructure_gaps": result["infrastructure_gaps"],
        "infrastructure_events_before_completion": result[
            "infrastructure_events_before_completion"
        ],
        "release_counts": result["release_counts"],
        "stage21a_finalization_fingerprint": (
            spec.stage21a_finalization_fingerprint
        ),
        "stage21a_source_fingerprint": spec.stage21a_source_fingerprint,
        "high_resolution_reservation_fingerprint": (
            spec.high_resolution_reservation_fingerprint
        ),
        "roster_id": spec.roster_id,
        "roster_fingerprint": spec.roster_fingerprint,
        "protocol_id": spec.protocol_id,
        "protocol_config_sha256": spec.protocol_config_sha256,
        "pair_manifest_hash": spec.pair_manifest_hash,
        "pair_ids_sha256": spec.pair_ids_sha256,
        "planned_pair_input_fingerprint": spec.planned_pair_input_fingerprint,
        "preparation_set_id": spec.preparation_set_id,
        "preparation_set_fingerprint": spec.preparation_set_fingerprint,
        "preparation_profile_id": spec.preparation_profile_id,
        "preparation_profile_fingerprint": spec.preparation_profile_fingerprint,
        "runtime_identity_fingerprint": spec.runtime_identity_fingerprint,
        "adapter_descriptor_fingerprint": spec.adapter_descriptor_fingerprint,
        "predecessor_finalization_fingerprint": spec.predecessor_finalization_fingerprint,
        "execution_source_fingerprint": spec.execution_source_fingerprint,
        "algorithm_execution_config_sha256": (
            spec.algorithm_execution_config_sha256
        ),
        "private_adapter_config_sha256": spec.private_adapter_config_sha256,
        "execution_strategy": spec.execution_strategy,
        "concurrency": spec.concurrency,
        "timeout_seconds": spec.timeout_seconds,
        "orchestrator_algorithm_retries": spec.orchestrator_algorithm_retries,
        "infrastructure_resume_allowed": spec.infrastructure_resume_allowed,
        "metrics_allowed": spec.metrics_allowed,
        "calibration_allowed": spec.calibration_allowed,
        "threshold_allowed": spec.threshold_allowed,
        "score_transform_allowed": spec.score_transform_allowed,
        "execution_source": {
            "fingerprint": source["execution_source_fingerprint"],
            "revision": source["execution_source_revision"],
            "file_sha256s": source["file_sha256s"],
            "private_adapter_config_sha256": source[
                "private_adapter_config_sha256"
            ],
            "runtime_identity_fingerprint": source[
                "runtime_identity_fingerprint"
            ],
        },
        "runtime_assets": _plain(spec.runtime_binding.get("assets", [])),
        "orchestrator_runtime": _plain(
            spec.runtime_binding.get("orchestrator_runtime", {})
        ),
        "timing": {
            **dict(result.get("timing", {})),
            "startup_environment_validation_ms": source.get(
                "preflight_environment_validation_ms"
            ),
            "startup_timing_definition": source.get(
                "preflight_environment_validation_timing_definition"
            ),
        },
        "sealed": True,
        "integrity_pass": True,
        "score_summary_computed": False,
    }


def _no_evaluation_document(root: Path) -> dict[str, Any]:
    forbidden_imports = _forbidden_imports(root)
    if forbidden_imports:
        raise Stage21BIntegrityError(
            "Stage 21B imports evaluation logic: " + ", ".join(forbidden_imports)
        )
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_no_evaluation_audit",
        "tar_computed": False,
        "far_computed": False,
        "frr_computed": False,
        "score_sweep_performed": False,
        "far_target_selected_from_results": False,
        "threshold_selected": False,
        "calibration_performed": False,
        "score_normalization_performed": False,
        "cross_algorithm_raw_scores_compared": False,
        "algorithm_ranking_performed": False,
        "pair_selection_used_scores": False,
        "algorithm_parameters_changed_from_results": False,
        "future_method_development_started": False,
        "new_raw_scores_generated": True,
        "forbidden_evaluation_imports": forbidden_imports,
        "runner_import_direction_valid": True,
        "audit_pass": True,
    }


def _verify_no_evaluation_document(value: Mapping[str, Any]) -> None:
    false_fields = (
        "tar_computed",
        "far_computed",
        "frr_computed",
        "score_sweep_performed",
        "far_target_selected_from_results",
        "threshold_selected",
        "calibration_performed",
        "score_normalization_performed",
        "cross_algorithm_raw_scores_compared",
        "algorithm_ranking_performed",
        "pair_selection_used_scores",
        "algorithm_parameters_changed_from_results",
        "future_method_development_started",
    )
    if any(value.get(name) is not False for name in false_fields):
        raise Stage21BIntegrityError("no-evaluation audit contains an evaluation action")
    if value.get("new_raw_scores_generated") is not True:
        raise Stage21BIntegrityError("no-evaluation audit must acknowledge new raw scores")
    if value.get("forbidden_evaluation_imports") != []:
        raise Stage21BIntegrityError("no-evaluation import audit failed")
    if value.get("runner_import_direction_valid") is not True or value.get(
        "audit_pass"
    ) is not True:
        raise Stage21BIntegrityError("no-evaluation audit is not PASS")


def _forbidden_imports(root: Path) -> list[str]:
    found: set[str] = set()
    for path in (root / "src/fpbench/stage21b").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                lowered = name.lower()
                forbidden_prefixes = (
                    "fpbench.baseline_evaluation",
                    "fpbench.metrics",
                    "fpbench.decisions",
                    "fpbench.evaluation",
                    "fpbench.analysis",
                )
                forbidden_fragments = (
                    "calibration",
                    "score_sweep",
                    "threshold_selection",
                    "far_target",
                    "ranking",
                )
                if lowered.startswith(forbidden_prefixes) or any(
                    fragment in lowered for fragment in forbidden_fragments
                ):
                    found.add(f"{path.name}:{name}")
    return sorted(found)


def _verify_source_binding(
    root: Path, spec: FrozenRunSpec, source: Mapping[str, Any]
) -> None:
    if source.get("run_spec_fingerprint") != spec.run_spec_fingerprint:
        raise Stage21BIntegrityError("execution-source binding belongs to another run")
    if source.get("execution_source_revision") != spec.execution_source_revision:
        raise Stage21BIntegrityError("execution-source revision differs from the run spec")
    if source.get("private_adapter_config_sha256") != spec.private_adapter_config_sha256:
        raise Stage21BIntegrityError("private adapter config differs from the run spec")
    if source.get("runtime_identity_fingerprint") != spec.runtime_identity_fingerprint:
        raise Stage21BIntegrityError("execution-source runtime differs from the run spec")
    _verify_source_map(
        root,
        source.get("file_sha256s"),
        adapter_id=spec.adapter_id,
    )
    fingerprint = stable_hash(
        {
            "schema": "stage21b_execution_source_v1",
            "files": source["file_sha256s"],
            "private_adapter_config_sha256": source[
                "private_adapter_config_sha256"
            ],
            "runtime_identity_fingerprint": source[
                "runtime_identity_fingerprint"
            ],
        },
        length=64,
    )
    if fingerprint != spec.execution_source_fingerprint or fingerprint != source.get(
        "execution_source_fingerprint"
    ):
        raise Stage21BIntegrityError("execution-source fingerprint is invalid")


def _verify_committed_source_receipt(root: Path, receipt: Mapping[str, Any]) -> None:
    source = receipt.get("execution_source")
    if not isinstance(source, Mapping):
        raise Stage21BIntegrityError("method receipt has no execution-source closure")
    if not _is_digest(source.get("private_adapter_config_sha256")):
        raise Stage21BIntegrityError("method receipt has an invalid private-config hash")
    if source.get("runtime_identity_fingerprint") != receipt.get(
        "runtime_identity_fingerprint"
    ):
        raise Stage21BIntegrityError("method source/runtime identities disagree")
    if source.get("private_adapter_config_sha256") != receipt.get(
        "private_adapter_config_sha256"
    ):
        raise Stage21BIntegrityError("method source/private-config identities disagree")
    if not str(source.get("revision", "")).strip():
        raise Stage21BIntegrityError("method receipt has no execution-source revision")
    _verify_source_map(
        root,
        source.get("file_sha256s"),
        adapter_id=str(receipt.get("adapter_id", "")),
    )
    fingerprint = stable_hash(
        {
            "schema": "stage21b_execution_source_v1",
            "files": source["file_sha256s"],
            "private_adapter_config_sha256": source[
                "private_adapter_config_sha256"
            ],
            "runtime_identity_fingerprint": source[
                "runtime_identity_fingerprint"
            ],
        },
        length=64,
    )
    if fingerprint != source.get("fingerprint") or fingerprint != receipt.get(
        "execution_source_fingerprint"
    ):
        raise Stage21BIntegrityError("committed execution-source identity is invalid")


def _verify_source_map(root: Path, value: Any, *, adapter_id: str) -> None:
    """Re-derive every execution-source digest from this checkout.

    ``source_file_sha256`` and not ``_sha256``: the closure is repository text
    whose committed identity must reproduce on a checkout that is not the one
    that published it, while the evidence documents above are hashed
    byte-for-byte because they are written LF on every platform.
    """
    if not isinstance(value, Mapping) or not value:
        raise Stage21BIntegrityError("execution-source file closure is empty")
    policy = load_execution_policy(root / EXECUTION_POLICY_PATH)
    try:
        route = policy.routes[adapter_id]
    except KeyError:
        raise Stage21BIntegrityError(
            f"execution source names an unknown adapter route: {adapter_id!r}"
        ) from None
    expected_map = execution_source_file_sha256s(
        repository_root=root,
        algorithm_config=root / route.algorithm_config,
        include_flx=adapter_id == "flx_pytorch_subprocess",
    )
    observed_map = {str(relative): str(digest) for relative, digest in value.items()}
    if observed_map != expected_map:
        missing = sorted(set(expected_map) - set(observed_map))
        extra = sorted(set(observed_map) - set(expected_map))
        changed = sorted(
            relative
            for relative in set(expected_map) & set(observed_map)
            if observed_map[relative] != expected_map[relative]
        )
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing[:3]))
        if extra:
            detail.append("extra=" + ",".join(extra[:3]))
        if changed:
            detail.append("changed=" + ",".join(changed[:3]))
        raise Stage21BIntegrityError(
            "execution-source closure is not exact: " + "; ".join(detail)
        )


def _contains_key(value: Any, wanted: str) -> bool:
    if isinstance(value, Mapping):
        return wanted in value or any(_contains_key(item, wanted) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, wanted) for item in value)
    return False


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage21BIntegrityError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage21BIntegrityError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise Stage21BIntegrityError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _is_digest(value: Any) -> bool:
    text = str(value).strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _canonical_json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
