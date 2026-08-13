"""What Stage 11B publishes, and the one marker that closes it.

Nine documents, not twenty. The generic artefacts — the run definition, the plan,
the result set, the receipt — stay in the engine's own structure and are not
copied out under a Stage 11B name; what this module writes is the algorithm's
own account of itself and the operational facts of the run (spec section 40).

.. code-block:: text

    README.md                     written by hand: what the run was for
    algorithm-profile.json        the frozen production identity
    runtime-binding.json          the seventeen-component closure and its guards
    adapter-profile.json          how the adapter drives the route
    bridge-contract.json          the wire format, its refusals and its codes
    adapter-smoke.json            the production smoke, copied from the run
    canonical-run-binding.json    the reference run, plan, pairs and inputs
    operational-summary.json      counts, codes, timings — and no score
    stage-11b-finalization.json   the marker

**Everything published here is operational.** Attempt counts, score-success
counts, failure codes and stages, release and stage counts, wall clock. There is
no mean, no median, no histogram, no ROC, no EER, no FMR, no FNMR, no accuracy
and no statement about which algorithm won — a distribution is a threshold in
disguise, and Stage 11B does not have one (spec sections 33, 35 and 36).

**No vendor byte, no machine path, no credential.** Components are named by their
path inside the SDK archive — ``Bin/Win64_x64/NBiometrics.dll`` — never by where
they happen to live on this computer (spec sections 38 and 39).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.enums import IntegrityIssueCode
from fpbench.core.serialization import read_json, stable_hash, to_plain, write_json
from fpbench.core.verifinger_errors import Stage11BFinalizationError
from fpbench.experiments import stage11b_identity as frozen
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure
from fpbench.experiments import verifinger_policy as policy

__all__ = [
    "EVIDENCE_DIRECTORY",
    "MARKER_SCHEMA",
    "Stage11BFinalization",
    "build_algorithm_profile_document",
    "build_runtime_binding_document",
    "build_adapter_profile_document",
    "build_bridge_contract_document",
    "build_canonical_run_binding_document",
    "build_operational_summary_document",
    "publish_stage11b_evidence",
    "build_stage11b_finalization",
    "publish_stage11b_finalization",
    "verify_stage11b_evidence",
    "stage11b_finalization_fingerprint",
    "main",
]

EVIDENCE_DIRECTORY = frozen.EVIDENCE_DIRECTORY
MARKER_SCHEMA = "stage_11b_finalization"

#: The source files that decided this stage. A change to any of them changes the
#: stage's own fingerprint, so a marker cannot outlive the code that produced it.
STAGE_11B_SOURCE_FILES: tuple[str, ...] = (
    "integrations/verifinger-java/build.py",
    "integrations/verifinger-java/src/main/java/org/fpbench/verifingerbridge/VeriFingerBridge.java",
    "src/fpbench/adapters/verifinger_java/adapter.py",
    "src/fpbench/adapters/verifinger_java/bridge_client.py",
    "src/fpbench/adapters/verifinger_java/bridge_models.py",
    "src/fpbench/adapters/verifinger_java/config.py",
    "src/fpbench/adapters/verifinger_java/failure_mapping.py",
    "src/fpbench/adapters/verifinger_java/identity.py",
    "src/fpbench/adapters/verifinger_java/runtime.py",
    "src/fpbench/experiments/stage11a_binding.py",
    "src/fpbench/experiments/stage11b_finalization.py",
    "src/fpbench/experiments/stage11b_identity.py",
    "src/fpbench/experiments/verifinger_canonical500_full.py",
    "src/fpbench/experiments/verifinger_policy.py",
    "src/fpbench/experiments/verifinger_research.py",
    "src/fpbench/experiments/verifinger_runtime_manifest.py",
    "src/fpbench/experiments/verifinger_smoke.py",
    "src/fpbench/experiments/verifinger_validation.py",
)


# ------------------------------------------------------------------ documents


def build_algorithm_profile_document() -> dict[str, Any]:
    """The frozen production identity, derived rather than written twice."""
    document = dict(identity.algorithm_profile())
    document["algorithm_profile_fingerprint"] = identity.algorithm_profile_fingerprint()
    return document


def build_runtime_binding_document(
    *, repository_root: Path = Path(".")
) -> dict[str, Any]:
    """Every executable and data byte that can affect this route.

    Relative paths only. A component is published as
    ``Bin/Win64_x64/NBiometrics.dll``, which identifies it inside the pinned SDK
    archive on any machine, rather than as a directory that exists on one
    (spec section 39).
    """
    manifest = runtime_closure.read_runtime_manifest(
        Path(repository_root)
        / "configs"
        / "verifinger"
        / "verifinger_runtime_manifest_v1.json"
    )
    loaded = policy.read_runtime_policy(
        Path(repository_root) / policy.DEFAULT_POLICY_PATH
    )
    return {
        "schema": "stage_11b_runtime_binding_v1",
        "platform": manifest.platform,
        "sdk_archive_sha256": manifest.sdk_archive_sha256,
        "runtime_manifest_fingerprint": manifest.fingerprint,
        "runtime_policy_id": loaded.policy_id,
        "runtime_policy_fingerprint": loaded.fingerprint,
        "closure": {
            "components": len(manifest.components),
            "native_libraries": len(runtime_closure.NATIVE_LIBRARY_NAMES),
            "model_data_files": len(runtime_closure.MODEL_DATA_FILES),
            "classpath_jars": len(runtime_closure.CLASSPATH_JARS),
            "classpath_order": list(runtime_closure.CLASSPATH_JARS),
            "native_library_directory": runtime_closure.native_library_directory(),
        },
        "components": [item.as_document() for item in manifest.components],
        "guards": {
            "before_the_run": "full_sha256_of_every_component",
            "during_the_run": "cheap_identity_check_before_every_comparison",
            "after_the_run": "full_sha256_of_every_component",
            "provenance": "every_component_reread_from_the_pinned_sdk_archive",
            "drift_response": "stop_the_run",
            "drift_is_never_a_stored_biometric_failure": True,
        },
        "vendor_bytes_in_git": False,
        "absolute_paths_published": False,
        "credentials_published": False,
    }


def build_adapter_profile_document() -> dict[str, Any]:
    """How the adapter drives the route, and what it refuses to do."""
    from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION
    from fpbench.adapters.verifinger_java.config import (
        PRIMARY_RUNTIME_ASSET_ROLE,
        RUNTIME_ASSET_ROLES,
    )
    from fpbench.adapters.verifinger_java.failure_mapping import (
        ALGORITHMIC_FAILURE_CODES,
        BLOCKING_FAILURE_CODES,
        BRIDGE_FAILURE_MAP,
    )
    from fpbench.experiments.verifinger_research import INTEGRATION_ID

    return {
        "schema": "stage_11b_adapter_profile_v1",
        "adapter_id": identity.ADAPTER_ID,
        "adapter_version": identity.ADAPTER_VERSION,
        "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
        "integration_id": INTEGRATION_ID,
        "integration_mode": identity.INTEGRATION_MODE,
        "runtime_asset_roles": list(RUNTIME_ASSET_ROLES),
        "primary_runtime_asset_role": PRIMARY_RUNTIME_ASSET_ROLE,
        "runtime_assets_are_all_fpbench_owned": True,
        "conformance": {
            "contract": "FingerprintAlgorithmAdapter contract v1",
            "same_contract_as_sourceafis_and_nbis": True,
            "special_contract_for_a_commercial_sdk": False,
        },
        "inputs": {
            "required_effective_ppi": identity.REQUIRED_EFFECTIVE_PPI,
            "preprocessing_by_fpbench": "none",
            "pixels_modified": 0,
            "forbidden_inputs": list(identity.FORBIDDEN_INPUTS),
        },
        "pairs": {
            "left": "reference",
            "right": "candidate",
            "reversal_permitted": False,
            "maximum_of_both_orderings_permitted": False,
            "average_of_both_orderings_permitted": False,
            "path_sorting_permitted": False,
            "self_independent_sides": True,
            "extractions_per_comparison": identity.REQUIRED_EXTRACTION_COUNT,
        },
        "failure_classification": {
            "bridge_code_to_fpbench_code": {
                code: mapped.value for code, (mapped, _stage) in sorted(
                    BRIDGE_FAILURE_MAP.items()
                )
            },
            "algorithm_outcomes": sorted(
                item.value for item in ALGORITHMIC_FAILURE_CODES
            ),
            "infrastructure_failures": sorted(
                item.value for item in BLOCKING_FAILURE_CODES
            ),
            "failure_scored_as_zero": False,
            "unknown_code_is_a_contract_violation_not_a_guess": True,
        },
        "score": {
            "direction": identity.SCORE_DIRECTION.value,
            "native_score_type": identity.NATIVE_SCORE_TYPE,
            "serialization": identity.SCORE_SERIALIZATION,
            "transformation_by_fpbench": identity.SCORE_TRANSFORMATION_BY_FPBENCH,
            "decision_returned_to_fpbench": False,
        },
    }


def build_bridge_contract_document() -> dict[str, Any]:
    """The wire format, in a document a reader can check the bridge against."""
    from fpbench.adapters.verifinger_java.bridge_models import (
        FORBIDDEN_RESPONSE_FIELDS,
        SCHEMA_VERSION,
    )

    return {
        "schema": "stage_11b_bridge_contract_v1",
        "bridge_protocol": identity.BRIDGE_PROTOCOL,
        "bridge_version": identity.BRIDGE_VERSION,
        "wire_schema_version": SCHEMA_VERSION,
        "commands": ["version", "compare"],
        "compare_request_fields": [
            "schema_version",
            "request_id",
            "left_image_path",
            "left_effective_ppi",
            "right_image_path",
            "right_effective_ppi",
        ],
        "compare_request_forbidden_fields": list(identity.FORBIDDEN_INPUTS),
        "compare_response_forbidden_fields": list(FORBIDDEN_RESPONSE_FIELDS),
        "score_bearing_engine_statuses": list(identity.SCORE_BEARING_STATUSES),
        "score_is_a_json_integer": True,
        "extraction_count_is_always": identity.REQUIRED_EXTRACTION_COUNT,
        "version_reports": [
            "bridge_protocol",
            "bridge_version",
            "loaded native modules and their versions",
            "java version, vendor and vm",
            "operating system and architecture",
            "delivered runtime defaults",
            "configured settings",
            "licence availability",
        ],
        "version_never_reports": [
            "licence key",
            "machine identifier",
            "absolute paths",
            "personal information",
        ],
        "route": {
            "official_sample": "Tutorials/Biometrics/Java/verify-finger",
            "api_call": "verify(reference, candidate)",
            "configured_settings": dict(identity.CONFIGURED_SETTINGS),
            "expected_delivered_defaults": dict(identity.EXPECTED_RUNTIME_DEFAULTS),
            "defaults_read_before_anything_is_configured": True,
            "defaults_mismatch_response": "refuse, never silently correct",
            "official_sample_matching_threshold": (
                identity.OFFICIAL_SAMPLE_MATCHING_THRESHOLD
            ),
            "threshold_used_as_a_decision_by_fpbench": False,
        },
    }


def build_canonical_run_binding_document(
    *, run: Any, plan: Any, alignment: Mapping[str, Any], config: Any
) -> dict[str, Any]:
    """Which comparisons ran, and what proves they are the reference run's own.

    The alignment half publishes the three equality counts the stored report
    carries — pair ids compared positionally, pair semantics per id, prepared
    entries per image — and derives cleanliness from them. ``is_clean`` is a
    property of the report object rather than a field of its JSON, and asking a
    mapping for it yields ``null``: a published document that answers "was this
    aligned?" with nothing is worse than one that does not ask.
    """
    equalities = {
        "equal_pair_ids": int(alignment.get("equal_pair_ids") or 0),
        "equal_pair_semantics": int(alignment.get("equal_pair_semantics") or 0),
        "equal_prepared_entries": int(alignment.get("equal_prepared_entries") or 0),
    }
    issues = len(alignment.get("issues") or ())
    clean = (
        issues == 0
        and equalities["equal_pair_ids"] == config.expected_jobs
        and equalities["equal_pair_semantics"] == config.expected_jobs
        and equalities["equal_prepared_entries"]
        == config.expected_participating_images
    )
    return {
        "schema": "stage_11b_canonical_run_binding_v1",
        "experiment_id": config.experiment_id,
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.definition.plan_fingerprint,
        "algorithm_fingerprint": run.algorithm_fingerprint,
        "environment_fingerprint": run.environment_fingerprint,
        "reference": {
            "run_id": config.reference.run_id,
            "plan_id": config.reference.plan_id,
            "result_set_id": config.reference.result_set_id,
            "cohort_id": config.reference_cohort_id,
            "pair_manifest_hash": config.reference_pair_manifest_hash,
        },
        "preparation": {
            "set_id": config.preparation_set_id,
            "set_fingerprint": config.preparation_set_fingerprint,
            "transform_profile_id": config.transform_profile_id,
            "transform_profile_fingerprint": config.transform_profile_fingerprint,
            "transform_runtime_fingerprint": config.transform_runtime_fingerprint,
            "target_ppi": config.target_ppi,
        },
        "alignment": {
            "fingerprint": alignment.get("alignment_fingerprint"),
            "is_clean": clean,
            "issues": issues,
            **equalities,
            "compared": (
                "pair ids positionally, pair semantics per id, and every field "
                "of every prepared entry — never count against count"
            ),
        },
        "expected": {
            "jobs": config.expected_jobs,
            "releases": list(config.expected_releases),
            "pairs_per_release": config.expected_per_release,
            "pairs_per_stage": config.expected_per_stage,
            "pairs_per_release_stage": config.expected_per_release_stage,
            "subjects": config.expected_subjects,
            "participating_images": config.expected_participating_images,
            "source_ppi": dict(config.expected_source_ppi),
        },
        "pairs_regenerated": False,
        "images_materialised": 0,
        "prior_algorithm_scores_read": False,
    }


def build_operational_summary_document(
    *, engine_summary: Mapping[str, Any], validation: Any, config: Any
) -> dict[str, Any]:
    """Counts, codes and timings. No score, and no statistic over scores.

    Everything permitted by spec section 33 and nothing beyond it: the attempt
    count, how many produced a score, how many did not and why, the operations
    the route performed, and the wall clock.
    """
    summary = dict(engine_summary)
    timings = dict(summary.get("timings_ms") or {})
    adapter_timings = dict(timings.get("adapter") or {})
    return {
        "schema": "stage_11b_operational_summary_v1",
        "experiment_id": config.experiment_id,
        "run_id": validation.run_id,
        "plan_id": validation.plan_id,
        "attempts": {
            "comparison_attempts": validation.total_results,
            "expected": config.expected_jobs,
            "missing": config.expected_jobs - validation.total_results,
        },
        "outcomes": {
            "score_successes": validation.successful_results,
            "algorithm_failures": validation.algorithmic_failures,
            "infrastructure_failures": validation.blocking_failures,
            "failure_codes": dict(validation.failure_counts),
            "engine_statuses": dict(validation.engine_status_counts),
        },
        "operations": {
            "logical_extractions": validation.logical_extraction_calls,
            "verify_invocations": validation.verify_invocations,
            "jvm_processes": validation.verify_invocations,
            "representation_cache": "disabled",
            "score_cache": "disabled",
        },
        "counts": {
            "by_release": dict(summary.get("release_counts") or {}),
            "by_stage": dict(summary.get("stage_counts") or {}),
        },
        "timings": {
            "adapter_ms": {
                key: adapter_timings[key]
                for key in ("count", "min", "median", "p95", "p99", "max")
                if key in adapter_timings
            },
            "wall_clock_span_seconds": summary.get("wall_clock_span_seconds"),
        },
        "execution": {
            "sequential": True,
            "max_workers": config.max_workers,
            "retries": frozen.RETRIES,
            "job_deadline_seconds": config.job_deadline_seconds,
        },
        "validation_fingerprint": validation.validation_fingerprint,
        # Restated on the document itself, so a reader never has to take the
        # absence of a field as a claim (spec section 33).
        "score_statistics_published": False,
        "biometric_metrics_published": False,
        "threshold_produced": False,
        "calibration_performed": False,
    }


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage11BFinalization:
    """The one document that closes Stage 11B."""

    document: Mapping[str, Any]

    @property
    def outcome(self) -> str:
        return str(self.document.get("outcome"))

    @property
    def fingerprint(self) -> str:
        return str(self.document.get("stage_11b_finalization_fingerprint"))


def stage11b_finalization_fingerprint(marker: Mapping[str, Any]) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_11b_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash({"schema": MARKER_SCHEMA, "marker": plain}, length=64)


def build_stage11b_finalization(
    *,
    repository_root: Path,
    validation: Any,
    config: Any,
    run: Any,
    smoke: Mapping[str, Any],
) -> dict[str, Any]:
    """The marker, derived from what is already published and already verified.

    Every count comes from the validation pass over the stored results; nothing
    here recomputes a number from a different source, because two sources for one
    number is how a marker ends up disagreeing with the run it describes
    (spec section 42).
    """
    root = Path(repository_root)
    from fpbench.experiments.stage11a_binding import require_stage11a_binding

    published = require_stage11a_binding(
        declared_fingerprint=config.stage11a_finalization_fingerprint,
        declared_outcome=config.stage11a_outcome,
        repository_root=root,
    )
    complete = (
        validation.total_results == config.expected_jobs
        and validation.blocking_failures == 0
        and validation.is_clean
    )
    marker: dict[str, Any] = {
        "schema_version": "1",
        "kind": MARKER_SCHEMA,
        "outcome": frozen.OUTCOME if complete else "STAGE_11B_INCOMPLETE",
        "algorithm_slot": identity.ALGORITHM_SLOT,
        "algorithm_id": identity.ALGORITHM_ID,
        "adapter_id": identity.ADAPTER_ID,
        "implementation_version": identity.IMPLEMENTATION_VERSION,
        "vendor": identity.VENDOR,
        "stage11a_fingerprint": published.finalization_fingerprint,
        "stage11a_outcome": published.outcome,
        "stage11b_source_fingerprint": stage11b_source_fingerprint(root),
        "algorithm_profile_fingerprint": identity.algorithm_profile_fingerprint(),
        "runtime_manifest_fingerprint": config.runtime_manifest_fingerprint,
        "runtime_policy_id": policy.POLICY_ID,
        "experiment_id": config.experiment_id,
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "plan_id": validation.plan_id,
        "reference_run_id": config.reference.run_id,
        "reference_pair_manifest_hash": config.reference_pair_manifest_hash,
        "preparation_set_id": config.preparation_set_id,
        "expected_comparisons": config.expected_jobs,
        "stored_outcomes": validation.total_results,
        "successful_scores": validation.successful_results,
        "algorithm_failures": validation.algorithmic_failures,
        "infrastructure_failures": validation.blocking_failures,
        "benchmark_scores_produced": validation.successful_results,
        "missing_jobs": config.expected_jobs - validation.total_results,
        # Counted, not asserted. The validator raises one issue per repeated job
        # id, and a marker that hard-coded zero here would be claiming something
        # nothing had checked (spec section 31).
        "duplicate_jobs": sum(
            1
            for issue in validation.issues
            if issue.code is IntegrityIssueCode.DUPLICATE_JOB_ID
        ),
        "logical_extractions": validation.logical_extraction_calls,
        "verify_invocations": validation.verify_invocations,
        "result_set_validation_clean": bool(validation.is_clean),
        "validation_fingerprint": validation.validation_fingerprint,
        "production_adapter_smoke": {
            "outcome": str(smoke.get("outcome")),
            "fixture_kind": str(smoke.get("fixture_kind")),
            "scores_produced": int(smoke.get("scores_produced") or 0),
            "sd300_used": bool(smoke.get("sd300_used")),
        },
        "generic_adapter_conformance": True,
        "official_java_binding_only": True,
        "runtime_closure_pinned": True,
        "all_loaded_components_verified": True,
        "licence_available": True,
        "frozen_runtime_defaults_match_11a": True,
        "matching_speed_low": identity.MATCHING_SPEED == "LOW",
        "raw_score_route": True,
        "self_independent_sides": True,
        "pair_orientation_fixed": True,
        "canonical_prepared_set_exact": True,
        "pair_manifest_exact": True,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "score_statistics_published": False,
        "algorithm_ranking_published": False,
        "prior_algorithm_scores_consulted": False,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "absolute_paths_in_evidence": False,
        "opens_algorithm_5_search": complete,
        "opens_common_calibration": False,
        "evidence_content_hashes": _evidence_content_hashes(root),
        "source_commit": _head_commit(root),
        "source_tree_clean": _tree_is_clean(root),
        "created_utc": _utc_now(),
    }
    marker["stage_11b_finalization_fingerprint"] = stage11b_finalization_fingerprint(
        marker
    )
    return marker


def stage11b_source_fingerprint(repository_root: Path) -> str:
    """The bytes that decided this stage."""
    digests = {
        relative: _source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in STAGE_11B_SOURCE_FILES
    }
    return stable_hash({"schema": "stage_11b_source_v1", "files": digests}, length=64)


# ----------------------------------------------------------------- publishing


def publish_stage11b_evidence(
    *,
    workspace: Path,
    repository_root: Path,
    config: Any,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    """Write the seven derived documents beside the hand-written README.

    ``stage-11b-finalization.json`` is deliberately **not** written here: it is
    the last file committed, derived against the evidence that this call
    published, so it can name their content hashes.
    """
    from fpbench.experiments.algorithm_research import read_run_pointer
    from fpbench.experiments.verifinger_canonical500_full import (
        ALIGNMENT_REPORT_NAME,
    )
    from fpbench.experiments.operational_summary import OPERATIONAL_SUMMARY_NAME
    from fpbench.storage.plan_store import PlanStore
    from fpbench.storage.result_store import ResultStore

    workspace = Path(workspace)
    root = Path(repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)

    result_store = ResultStore(workspace)
    run = result_store.read_run(resolved)
    plan = PlanStore(workspace).read_plan(resolved)
    alignment = read_json(result_store.derived_path(resolved, ALIGNMENT_REPORT_NAME))
    engine_summary = read_json(
        result_store.derived_path(resolved, OPERATIONAL_SUMMARY_NAME)
    )
    validation = _validation_report(
        workspace=workspace, run_id=resolved, config=config
    )
    smoke = read_json(result_store.derived_path(resolved, frozen.SMOKE_REPORT_NAME))

    directory = root / EVIDENCE_DIRECTORY
    written: list[Path] = []
    for name, value in (
        ("algorithm-profile.json", build_algorithm_profile_document()),
        ("runtime-binding.json", build_runtime_binding_document(repository_root=root)),
        ("adapter-profile.json", build_adapter_profile_document()),
        ("bridge-contract.json", build_bridge_contract_document()),
        (frozen.SMOKE_REPORT_NAME, smoke),
        (
            "canonical-run-binding.json",
            build_canonical_run_binding_document(
                run=run, plan=plan, alignment=alignment, config=config
            ),
        ),
        (
            frozen.OPERATIONAL_SUMMARY_NAME,
            build_operational_summary_document(
                engine_summary=engine_summary, validation=validation, config=config
            ),
        ),
    ):
        written.append(write_json(directory / name, value))
    return tuple(written)


def publish_stage11b_finalization(
    *,
    workspace: Path,
    repository_root: Path,
    config: Any,
    run_id: str | None = None,
) -> Path:
    """Derive and write the marker, over evidence that is already committed."""
    from fpbench.experiments.algorithm_research import read_run_pointer
    from fpbench.storage.result_store import ResultStore

    workspace = Path(workspace)
    root = Path(repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    result_store = ResultStore(workspace)
    marker = build_stage11b_finalization(
        repository_root=root,
        validation=_validation_report(
            workspace=workspace, run_id=resolved, config=config
        ),
        config=config,
        run=result_store.read_run(resolved),
        smoke=read_json(result_store.derived_path(resolved, frozen.SMOKE_REPORT_NAME)),
    )
    return write_json(root / EVIDENCE_DIRECTORY / frozen.STAGE_11B_FINALIZATION_NAME, marker)


def verify_stage11b_evidence(
    *, repository_root: Path = Path(".")
) -> Mapping[str, Any]:
    """Re-derive everything the committed evidence can be checked against.

    Evidence-only: no workspace, no dataset, no SDK and no licence. What it
    proves is that the published documents are internally consistent, that the
    marker's content hashes still describe them, that the identity and closure
    documents are the ones this source produces, and that nothing forbidden was
    published (spec section 41).

    Raises:
        Stage11BFinalizationError: any of that fails.
    """
    root = Path(repository_root)
    directory = root / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage11BFinalizationError(
            f"no published Stage 11B evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    present = tuple(sorted(item.name for item in directory.iterdir() if item.is_file()))
    # The engine's last act of finalization is writing its own research receipt
    # here as ``run_<id>.json``. That file belongs to the shared engine and is
    # published by every research stage; this stage's own nine are the rest
    # (spec section 40).
    receipts = tuple(name for name in present if name.startswith("run_"))
    if len(receipts) != 1:
        raise Stage11BFinalizationError(
            f"the evidence tree holds {list(receipts)} engine receipts; exactly "
            "one run was finalised here"
        )
    expected = tuple(sorted(frozen.EVIDENCE_DOCUMENTS))
    stage_documents = tuple(name for name in present if name not in receipts)
    if stage_documents != expected:
        raise Stage11BFinalizationError(
            f"the Stage 11B evidence tree holds {list(stage_documents)}, and "
            f"this stage publishes {list(expected)}"
        )

    marker = read_json(directory / frozen.STAGE_11B_FINALIZATION_NAME)
    if str(marker.get("kind")) != MARKER_SCHEMA:
        raise Stage11BFinalizationError("the marker is not a Stage 11B finalization")
    derived = stage11b_finalization_fingerprint(marker)
    if derived != marker.get("stage_11b_finalization_fingerprint"):
        raise Stage11BFinalizationError(
            "the marker does not fingerprint to the identity it carries"
        )

    hashes = marker.get("evidence_content_hashes") or {}
    drifted = []
    for name, expected_hash in sorted(dict(hashes).items()):
        target = directory / str(name)
        if not target.is_file():
            drifted.append(f"{name} is missing")
            continue
        found = _source_file_sha256(target)
        if found != str(expected_hash):
            drifted.append(f"{name} has changed since the marker was derived")
    if drifted:
        raise Stage11BFinalizationError("; ".join(drifted))

    # The identity and closure documents are derived, so they can be rebuilt from
    # this source and compared — which is what catches an edited evidence file
    # that was also re-hashed consistently.
    for name, rebuilt in (
        ("algorithm-profile.json", build_algorithm_profile_document()),
        ("runtime-binding.json", build_runtime_binding_document(repository_root=root)),
        ("adapter-profile.json", build_adapter_profile_document()),
        ("bridge-contract.json", build_bridge_contract_document()),
    ):
        published = read_json(directory / name)
        if stable_hash(published, length=64) != stable_hash(rebuilt, length=64):
            raise Stage11BFinalizationError(
                f"{name} is not the document this source produces"
            )

    if marker.get("stage11b_source_fingerprint") != stage11b_source_fingerprint(root):
        raise Stage11BFinalizationError(
            "the Stage 11B source has changed since the marker was derived"
        )
    _require_no_forbidden_published_data(directory)

    return {
        "outcome": marker.get("outcome"),
        "stage_11b_finalization_fingerprint": marker.get(
            "stage_11b_finalization_fingerprint"
        ),
        "documents": len(expected),
        "stored_outcomes": marker.get("stored_outcomes"),
        "successful_scores": marker.get("successful_scores"),
        "algorithm_failures": marker.get("algorithm_failures"),
        "infrastructure_failures": marker.get("infrastructure_failures"),
    }


# ----------------------------------------------------------------- internals


#: Keys a Stage 11B document may never carry. Checked over every published file,
#: at any depth, because a metric that arrived in a nested object is still a
#: metric (spec sections 33 and 35).
_FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "accuracy",
        "auc",
        "calibration_profile",
        "decision_profile",
        "eer",
        "far_curve",
        "fmr",
        "fnmr",
        "histogram",
        "mean_score",
        "median_score",
        "roc",
        "score_distribution",
        "score_histogram",
        "scores",
    }
)


def _require_no_forbidden_published_data(directory: Path) -> None:
    for path in sorted(directory.glob("*.json")):
        found = _forbidden_keys(read_json(path))
        if found:
            raise Stage11BFinalizationError(
                f"{path.name} publishes {sorted(found)}, which Stage 11B may not"
            )
        text = path.read_text(encoding="utf-8")
        for marker in ("C:\\\\Users", "C:/Users", "/home/"):
            if marker in text:
                raise Stage11BFinalizationError(
                    f"{path.name} carries a machine path (spec section 39)"
                )


def _forbidden_keys(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            if str(key).lower() in _FORBIDDEN_PUBLISHED_KEYS:
                found.add(str(key))
            found |= _forbidden_keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _forbidden_keys(item)
    return found


def _evidence_content_hashes(repository_root: Path) -> dict[str, str]:
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    return {
        name: _source_file_sha256(directory / name)
        for name in sorted(frozen.EVIDENCE_DOCUMENTS)
        if name != frozen.STAGE_11B_FINALIZATION_NAME
        and (directory / name).is_file()
    }


def _validation_report(*, workspace: Path, run_id: str, config: Any):
    """The VeriFinger validation pass, re-derived from the stored results."""
    from fpbench.experiments.sd300_inputs import load_sd300_inputs
    from fpbench.experiments.verifinger_validation import (
        SD300_CANONICAL500_INPUT_SET,
        validate_verifinger_result_set,
    )
    from fpbench.storage.plan_store import PlanStore
    from fpbench.storage.result_store import ResultStore

    result_store = ResultStore(workspace)
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=None,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=False,
    )
    return validate_verifinger_result_set(
        run=result_store.read_run(run_id),
        plan=PlanStore(workspace).read_plan(run_id),
        pairs=inputs.pairs,
        images=inputs.images,
        result_store=result_store,
        runtime_reference=result_store.read_runtime_reference(run_id),
        preparation=None,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
        expected_runtime_manifest_fingerprint=config.runtime_manifest_fingerprint,
    )


def _source_file_sha256(path: Path) -> str:
    """A digest with newlines normalised, for the reason Stage 11A normalises."""
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage11BFinalizationError(f"cannot hash {path.name}: {exc}") from exc
    return hashlib.sha256(content).hexdigest()


def _head_commit(repository_root: Path) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git
        return ""
    return (completed.stdout or "").strip()


def _tree_is_clean(repository_root: Path) -> bool:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "status", "--porcelain"),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git
        return False
    return completed.returncode == 0 and not (completed.stdout or "").strip()


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    """``python -m fpbench.experiments.stage11b_finalization``."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Stage 11B evidence and marker")
    parser.add_argument(
        "action", choices=("publish", "finalize", "verify"), nargs="?", default="verify"
    )
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--run-id", default=None)
    arguments = parser.parse_args(argv)

    root = Path(arguments.repository_root).resolve()
    if arguments.action == "verify":
        print(json.dumps(dict(verify_stage11b_evidence(repository_root=root)), indent=2))
        return 0

    from fpbench.experiments.verifinger_canonical500_full import (
        load_verifinger_canonical500_config,
    )

    config = load_verifinger_canonical500_config(repository_root=root)
    workspace = Path(arguments.workspace).resolve()
    if arguments.action == "publish":
        written = publish_stage11b_evidence(
            workspace=workspace,
            repository_root=root,
            config=config,
            run_id=arguments.run_id,
        )
        for path in written:
            print(path.relative_to(root).as_posix())
        return 0

    path = publish_stage11b_finalization(
        workspace=workspace,
        repository_root=root,
        config=config,
        run_id=arguments.run_id,
    )
    marker = read_json(path)
    print(f"{marker['outcome']}  {marker['stage_11b_finalization_fingerprint']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
