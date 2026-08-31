"""Build and verify the Stage 21A protocol-freeze evidence.

The builder touches manifests and metadata only.  It does not import an adapter,
open a result row, read a raw score, or execute a comparison.  The one generated
workspace artifact is the 73,500-row cross-subject pair manifest.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.baseline_evaluation.policy import load_baseline_evaluation_policy
from fpbench.baseline_evaluation.roster import load_baseline_roster_config
from fpbench.core.json_io import publish_evidence_document
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage19_pair_manifest import load_canonical_pair_manifest
from fpbench.protocols.cross_subject import (
    SD300CrossSubjectProtocol,
    audit_cross_subject_pairs,
)
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.manifest_store import ManifestStore

__all__ = [
    "EVIDENCE_DIRECTORY",
    "EVIDENCE_DOCUMENTS",
    "FINALIZATION_NAME",
    "LEGACY_PAIR_MANIFEST_HASH",
    "OUTCOME",
    "Stage21AError",
    "freeze_stage21a",
    "stage21a_source_fingerprint",
    "verify_stage21a_evidence",
]


EVIDENCE_DIRECTORY = Path("evidence/stage21a-final-baseline-evaluation-protocol")
FINALIZATION_NAME = "stage-21a-finalization.json"
OUTCOME = "FINAL_BASELINE_EVALUATION_PROTOCOL_READY"
LEGACY_PROTOCOL_ID = "sd300_50_subjects"
LEGACY_COHORT_ID = "sd300_50_subjects_test_22f8d52a7478"
LEGACY_PAIR_MANIFEST_HASH = (
    "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
)
CROSS_SUBJECT_PAIR_MANIFEST_HASH = (
    "a8b836cb3901daf66648ac1a5a850651ca9292f8bb0c8814ebce972f37c52505"
)
FUTURE_GENUINE_PAIR_IDS_SHA256 = (
    "2aaebeedf5249ab9304fbceab5cf7083497e7fc4c9a5aa0fdc5194274258354d"
)
FUTURE_GENUINE_PAIR_SET_FINGERPRINT = (
    "bda93e4798293a5da28f2f2e6cc75dad73f86057903739f7c222bab7196b5d3d"
)
FUTURE_IMPOSTOR_PAIR_IDS_SHA256 = (
    "2d7e936c86c23aae9d8efedca1a58aeec8781af9d13f0ec851f728d30750224a"
)
FUTURE_IMPOSTOR_PAIR_SET_FINGERPRINT = (
    "c112288b01b581cf55f7afed8bc4d4d15fe30d30bc5be099de7ad30ba0011999"
)
PREPARATION_SET_ID = "prepset_be560e047991"
EVIDENCE_DOCUMENTS = (
    "README.md",
    "baseline-roster.json",
    "predecessor-bindings.json",
    "legacy-protocol-invariance.json",
    "cross-subject-pair-binding.json",
    "cross-subject-pair-audit.json",
    "cross-subject-strategy-decision.json",
    "evaluation-policy.json",
    "high-resolution-test-reservation.json",
    "no-leakage-audit.json",
)

_SOURCE_PATHS = (
    "src/fpbench/core/enums.py",
    "src/fpbench/core/__init__.py",
    "src/fpbench/core/models.py",
    "src/fpbench/storage/schemas.py",
    "src/fpbench/execution/planner.py",
    "src/fpbench/protocols/__init__.py",
    "src/fpbench/protocols/cross_subject.py",
    "src/fpbench/baseline_evaluation/__init__.py",
    "src/fpbench/baseline_evaluation/models.py",
    "src/fpbench/baseline_evaluation/policy.py",
    "src/fpbench/baseline_evaluation/roster.py",
    "src/fpbench/baseline_evaluation/sweep.py",
    "src/fpbench/experiments/stage21a_finalization.py",
    "src/fpbench/experiments/stage_registry.py",
    "scripts/stage21a_freeze.py",
    "configs/protocols/sd300_50_subjects.yaml",
    "configs/protocols/sd300_cross_subject_non_mated_v1.yaml",
    "configs/comparisons/final_baseline_roster_v1.yaml",
    "configs/comparisons/final_baseline_tar_far_frr_v1.yaml",
    "configs/reports/final_baseline_reporting_v1.yaml",
    "configs/research/high_resolution_test_reservation_v1.yaml",
    "tests/unit/test_cross_subject_protocol.py",
    "tests/unit/test_baseline_score_sweep.py",
    "tests/unit/test_baseline_evaluation_policy.py",
    "tests/unit/test_baseline_roster.py",
    "tests/regression/test_stage21a_real_manifests.py",
    "tests/test_stage21a_evidence.py",
)


class Stage21AError(RuntimeError):
    """The protocol freeze contradicts one of its immutable inputs."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage21AError(f"{path} is not a JSON object")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise Stage21AError(f"{path} is not a YAML mapping")
    return value


def _exact_mapping(
    value: object, expected_keys: set[str], *, where: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Stage21AError(f"{where} is not a mapping")
    actual = set(value)
    if actual != expected_keys:
        raise Stage21AError(
            f"{where} keys are {sorted(actual)}, expected {sorted(expected_keys)}"
        )
    return value


def _canonical_json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stage21a_source_fingerprint(repository_root: Path) -> str:
    root = Path(repository_root)
    missing = [path for path in _SOURCE_PATHS if not (root / path).is_file()]
    if missing:
        raise Stage21AError(f"Stage 21A source files are missing: {missing}")
    return stable_hash(
        {path: _sha256(root / path) for path in _SOURCE_PATHS}, length=64
    )


def _pair_rows(pairs: Sequence[Any]) -> list[dict[str, str]]:
    return [
        {
            "pair_id": str(pair.pair_id),
            "dataset_id": pair.dataset_id,
            "release": pair.release,
            "left_image_id": str(pair.left_image_id),
            "right_image_id": str(pair.right_image_id),
            "ground_truth": pair.ground_truth.value,
            "protocol_stage": pair.protocol_stage.value,
        }
        for pair in pairs
    ]


def _load_manifest_inputs(
    store: ManifestStore, releases: Sequence[str]
) -> tuple[list[Any], list[Any], dict[str, str]]:
    images: list[Any] = []
    subjects: list[Any] = []
    hashes: dict[str, str] = {}
    for release in releases:
        images.extend(store.read_images("sd300", release))
        subjects.extend(store.read_subjects("sd300", release))
        hashes[release] = store.image_manifest_hash("sd300", release)
    return images, subjects, hashes


def _legacy_invariance(
    repository_root: Path, workspace: Path, store: ManifestStore
) -> tuple[dict[str, Any], Any, list[Any], list[Any], dict[str, str]]:
    config_path = repository_root / "configs/protocols/sd300_50_subjects.yaml"
    protocol = SD300Protocol.from_config_file(config_path)
    cohort = store.read_cohort(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID)
    images, subjects, image_hashes = _load_manifest_inputs(store, protocol.releases)
    stored = store.read_pairs(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID)
    metadata = store.pair_manifest_metadata(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID)
    canonical = load_canonical_pair_manifest(
        store.pairs_path(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID),
        expected_pair_manifest_hash=LEGACY_PAIR_MANIFEST_HASH,
    )
    regenerated = protocol.build_pairs(cohort, images)
    if metadata["pair_manifest_hash"] != LEGACY_PAIR_MANIFEST_HASH:
        raise Stage21AError("legacy pair-manifest hash changed")
    if len(stored) != 6_000 or tuple(stored) != regenerated:
        raise Stage21AError("legacy generator no longer reproduces the stored 6,000 rows")
    if len(canonical.pairs) != 6_000:
        raise Stage21AError("legacy canonical manifest does not contain 6,000 rows")
    rows = _pair_rows(stored)
    artifact = {
        "kind": "stage_21a_legacy_protocol_invariance",
        "protocol_config": "configs/protocols/sd300_50_subjects.yaml",
        "protocol_config_sha256": _sha256(config_path),
        "protocol_id": LEGACY_PROTOCOL_ID,
        "cohort_id": LEGACY_COHORT_ID,
        "count": len(stored),
        "expected_count": 6_000,
        "pair_manifest_hash": metadata["pair_manifest_hash"],
        "expected_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "pair_ids_sha256": stable_hash(
            [str(pair.pair_id) for pair in stored], length=64
        ),
        "ordered_rows_sha256": stable_hash(rows, length=64),
        "all_pair_ids_unchanged": tuple(stored) == regenerated,
        "ordering_unchanged": tuple(stored) == regenerated,
        "generator_regeneration_exact": tuple(stored) == regenerated,
        "manifest_self_hash_recomputed": canonical.pair_manifest_hash,
        "pass": True,
    }
    return artifact, cohort, images, subjects, image_hashes


def _cross_subject_binding(
    repository_root: Path,
    workspace: Path,
    store: ManifestStore,
    *,
    source_cohort: Any,
    images: list[Any],
    subjects: list[Any],
    image_hashes: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    config_path = (
        repository_root / "configs/protocols/sd300_cross_subject_non_mated_v1.yaml"
    )
    protocol = SD300CrossSubjectProtocol.from_config_file(config_path)
    cohort = protocol.build_cohort(subjects, image_hashes)
    if tuple(cohort.subject_ids) != tuple(source_cohort.subject_ids):
        raise Stage21AError("cross-subject cohort differs from the frozen legacy 50")
    pairs = protocol.build_pairs(cohort, images)
    regenerated = protocol.build_pairs(cohort, list(reversed(images)))
    if pairs != regenerated:
        raise Stage21AError("cross-subject regeneration is not deterministic")
    legacy_pairs = store.read_pairs(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID)
    audit = audit_cross_subject_pairs(
        pairs,
        cohort=cohort,
        images=images,
        legacy_pair_ids=(pair.pair_id for pair in legacy_pairs),
    )
    if not audit.clean:
        raise Stage21AError(f"cross-subject pair audit failed: {audit.as_dict()}")

    cohort_path = store.cohort_path(protocol.protocol_id, str(cohort.cohort_id))
    if cohort_path.exists():
        if store.read_cohort(protocol.protocol_id, str(cohort.cohort_id)) != cohort:
            raise Stage21AError("existing cross-subject cohort contradicts regeneration")
    else:
        store.write_cohort(cohort)
    pairs_path = store.pairs_path(protocol.protocol_id, str(cohort.cohort_id))
    if pairs_path.exists():
        if store.read_pairs(protocol.protocol_id, str(cohort.cohort_id)) != list(pairs):
            raise Stage21AError("existing cross-subject manifest contradicts regeneration")
    else:
        store.write_pairs(pairs, cohort=cohort)
    metadata = store.pair_manifest_metadata(protocol.protocol_id, str(cohort.cohort_id))
    canonical = load_canonical_pair_manifest(
        pairs_path, expected_pair_manifest_hash=metadata["pair_manifest_hash"]
    )
    if len(canonical.pairs) != 73_500:
        raise Stage21AError("stored cross-subject manifest is not 73,500 rows")
    if metadata["pair_manifest_hash"] != CROSS_SUBJECT_PAIR_MANIFEST_HASH:
        raise Stage21AError("the frozen 73,500-row pair-manifest hash changed")

    binding = {
        "kind": "stage_21a_cross_subject_pair_binding",
        "protocol_id": protocol.protocol_id,
        "population": protocol.config.population_id,
        "source_protocol_id": LEGACY_PROTOCOL_ID,
        "source_cohort_id": LEGACY_COHORT_ID,
        "cohort_id": str(cohort.cohort_id),
        "cohort_role": cohort.role.value,
        "cohort_membership_equal_to_legacy": True,
        "subject_count": len(cohort.subject_ids),
        "releases": list(cohort.releases),
        "pair_count": len(pairs),
        "pair_manifest_hash": metadata["pair_manifest_hash"],
        "pair_ids_sha256": stable_hash(
            [str(pair.pair_id) for pair in pairs], length=64
        ),
        "ordered_rows_sha256": stable_hash(_pair_rows(pairs), length=64),
        "manifest_self_hash_recomputed": canonical.pair_manifest_hash,
        "manifest_logical_path": _relative(pairs_path, workspace),
        "generation_config": (
            "configs/protocols/sd300_cross_subject_non_mated_v1.yaml"
        ),
        "generation_config_sha256": _sha256(config_path),
        "generation_config_fingerprint": stable_hash(
            _read_yaml(config_path), length=64
        ),
        "ordering": list(protocol.config.ordering),
        "directed_pairs": True,
        "sampling_performed": False,
        "deterministic_regeneration": True,
        "legacy_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "legacy_manifest_replaced": False,
        "algorithm_runs_performed": 0,
        "score_values_read": 0,
    }
    audit_document = audit.as_dict()
    audit_document.update(
        {
            "protocol_id": protocol.protocol_id,
            "cohort_id": str(cohort.cohort_id),
            "pair_manifest_hash": metadata["pair_manifest_hash"],
            "deterministic_regeneration": True,
        }
    )
    return binding, audit_document


def _observed_far_increment(denominator: int) -> dict[str, Any]:
    increment = Fraction(1, denominator)
    return {
        "one_additional_false_accept": 1,
        "impostor_attempt_denominator": denominator,
        "exact_fraction": str(increment),
        "decimal": format(float(increment), ".17g"),
    }


def _cross_subject_strategy_decision(
    cross_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze the exhaustive choice without consulting a result or score."""
    per_release = 24_500
    pooled = 73_500
    alternatives = [
        {
            "strategy_id": "exhaustive_directed_all_other_subjects",
            "selected": True,
            "opponents_per_left_subject_and_finger": 49,
            "pair_count_per_release": per_release,
            "pooled_pair_count": pooled,
            "observed_far_increment": {
                "per_release": _observed_far_increment(per_release),
                "pooled": _observed_far_increment(pooled),
            },
            "disposition": (
                "selected because it removes opponent-sampling degrees of freedom, "
                "uses every eligible ordered cross-subject pair, and provides the "
                "finest observed-FAR step available from the frozen 50-subject cohort"
            ),
        },
        {
            "strategy_id": "deterministic_ten_opponents_per_left_subject_and_finger",
            "selected": False,
            "opponents_per_left_subject_and_finger": 10,
            "pair_count_per_release": 5_000,
            "pooled_pair_count": 15_000,
            "observed_far_increment": {
                "per_release": _observed_far_increment(5_000),
                "pooled": _observed_far_increment(15_000),
            },
            "disposition": (
                "rejected because it introduces an unnecessary opponent-selection "
                "rule and yields a coarser observed-FAR step"
            ),
        },
        {
            "strategy_id": "deterministic_one_opponent_per_left_subject_and_finger",
            "selected": False,
            "opponents_per_left_subject_and_finger": 1,
            "pair_count_per_release": 500,
            "pooled_pair_count": 1_500,
            "observed_far_increment": {
                "per_release": _observed_far_increment(500),
                "pooled": _observed_far_increment(1_500),
            },
            "disposition": (
                "rejected because it is dominated by the exhaustive design in this "
                "fixed cohort and has the coarsest observed-FAR step"
            ),
        },
    ]
    decision: dict[str, Any] = {
        "schema_version": "1",
        "kind": "stage_21a_cross_subject_strategy_decision",
        "decision_id": "sd300_cross_subject_strategy_exhaustive_v1",
        "decision_status": "frozen_before_cross_subject_scores",
        "selected_strategy_id": "exhaustive_directed_all_other_subjects",
        "selected_pair_count_per_release": per_release,
        "selected_pooled_pair_count": pooled,
        "selected_pair_manifest_hash": cross_binding["pair_manifest_hash"],
        "selected_pair_ids_sha256": cross_binding["pair_ids_sha256"],
        "alternatives_considered": alternatives,
        "selection_justification": (
            "The exhaustive 50 x 49 x 10 directed design was selected because all "
            "eligible different-subject opponents are already fixed and tractable. "
            "It avoids a post hoc sampling choice and freezes 24,500 comparisons per "
            "release, 73,500 pooled, before any cross-subject score exists."
        ),
        "observed_far_granularity": {
            "per_release": _observed_far_increment(per_release),
            "pooled": _observed_far_increment(pooled),
            "interpretation": (
                "These increments are the smallest changes in observed FAR caused by "
                "one additional false accept in the fixed evaluation denominators. "
                "They are granularity statements only, not claims of statistical "
                "precision, confidence-interval width, or population-level accuracy."
            ),
        },
        "observed_far_granularity_not_statistical_precision": True,
        "statistical_precision_claimed": False,
        "confidence_interval_precision_claimed": False,
        "selected_without_score_values": True,
        "score_values_read": 0,
        "algorithm_runs_performed": 0,
    }
    decision["strategy_decision_fingerprint"] = _canonical_json_hash(decision)
    return decision


def _source_record(
    path: Path, repository_root: Path, *, workspace_metadata: bool = False
) -> dict[str, Any]:
    return {
        "path": _relative(path, repository_root),
        "sha256": _sha256(path),
        "workspace_metadata_only": workspace_metadata,
    }


def _build_roster(
    repository_root: Path, workspace: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    roster_config_path = (
        repository_root / "configs/comparisons/final_baseline_roster_v1.yaml"
    )
    roster_config = load_baseline_roster_config(roster_config_path)
    records: list[dict[str, Any]] = [
        _source_record(roster_config_path, repository_root)
    ]

    def read_json(relative: str, *, workspace_file: bool = False) -> dict[str, Any]:
        root = workspace if workspace_file else repository_root
        path = root / relative
        value = _read_json(path)
        records.append(
            _source_record(
                path,
                repository_root,
                workspace_metadata=workspace_file,
            )
        )
        return value

    def read_algorithm(relative: str) -> dict[str, Any]:
        path = repository_root / relative
        value = _read_yaml(path)
        records.append(_source_record(path, repository_root))
        return value["algorithm"]

    methods: list[dict[str, Any]] = []

    def add_engine_method(
        *,
        algorithm_config: str,
        run_evidence: str,
        finalization_path: str,
        finalization_field: str,
        finalization_workspace: bool,
        integration_id: str | None,
        role: str,
        display_override: str | None = None,
    ) -> None:
        algorithm = read_algorithm(algorithm_config)
        run = read_json(run_evidence)
        finalization = read_json(
            finalization_path, workspace_file=finalization_workspace
        )
        attempts = int(run["planned_jobs"])
        score_bearing = int(run["success_count"])
        if attempts != 6_000 or run["pair_manifest_hash"] != LEGACY_PAIR_MANIFEST_HASH:
            raise Stage21AError(f"{algorithm['id']} is not bound to the full protocol")
        if run["preparation_set_id"] != PREPARATION_SET_ID:
            raise Stage21AError(f"{algorithm['id']} used another preparation set")
        upstream_commit = (
            algorithm.get("implementation_version")
            if len(str(algorithm.get("implementation_version", ""))) == 40
            else None
        )
        methods.append(
            {
                "algorithm_id": algorithm["id"],
                "display_name": display_override or algorithm["display_name"],
                "role": role,
                "adapter_id": algorithm["adapter_id"],
                "integration_id": integration_id,
                "implementation_version": algorithm["implementation_version"],
                "upstream_commit": upstream_commit,
                "upstream_artifact": algorithm.get("upstream_artifact"),
                "raw_result_identity": {
                    "run_id": run["run_id"],
                    "run_fingerprint": run["run_fingerprint"],
                    "result_set_id": run["result_set_id"],
                    "result_set_fingerprint": run["result_set_fingerprint"],
                },
                "score_direction": "higher_is_better",
                "canonical_preparation_set_id": run["preparation_set_id"],
                "pair_manifest_hash": run["pair_manifest_hash"],
                "finalization_fingerprint": finalization[finalization_field],
                "attempts": attempts,
                "score_bearing_results": score_bearing,
                "algorithm_failures": attempts - score_bearing,
            }
        )

    add_engine_method(
        algorithm_config="configs/algorithms/sourceafis_java_3_18_1.yaml",
        run_evidence="evidence/sourceafis-canonical500-full/run_4c59fa02a6ab.json",
        finalization_path="results/run_4c59fa02a6ab/research-finalization.json",
        finalization_field="finalization_fingerprint",
        finalization_workspace=True,
        integration_id="sourceafis_java_research_v1",
        role="primary_baseline",
        display_override="SourceAFIS Java 3.18.1",
    )
    add_engine_method(
        algorithm_config="configs/algorithms/nbis_mindtct_bozorth3_5_0_0_v1.yaml",
        run_evidence="evidence/nbis-canonical500-raw/run_f0468f28ffba.json",
        finalization_path="evidence/nbis-canonical500-raw/stage-7c-finalization.json",
        finalization_field="stage_7c_finalization_fingerprint",
        finalization_workspace=False,
        integration_id="nbis_mindtct_bozorth3_research_v1",
        role="primary_baseline",
        display_override="NBIS MINDTCT 5.0.0 + BOZORTH3",
    )
    add_engine_method(
        algorithm_config=(
            "configs/algorithms/flx_deepprint_texminu_512_without_localization_v1.yaml"
        ),
        run_evidence="evidence/flx-canonical500-raw/run_902136b3b8ae.json",
        finalization_path="evidence/flx-canonical500-raw/stage-8c-finalization.json",
        finalization_field="stage_8c_finalization_fingerprint",
        finalization_workspace=False,
        integration_id="flx_deepprint_texminu_research_v1",
        role="primary_baseline",
        display_override="FLX DeepPrint TexMinu 512 without localization",
    )
    add_engine_method(
        algorithm_config="configs/algorithms/verifinger_2025_2_1to1_v1.yaml",
        run_evidence=(
            "evidence/stage11b-verifinger-canonical500-raw/run_a76145fb5ab2.json"
        ),
        finalization_path=(
            "evidence/stage11b-verifinger-canonical500-raw/"
            "stage-11b-finalization.json"
        ),
        finalization_field="stage_11b_finalization_fingerprint",
        finalization_workspace=False,
        integration_id="verifinger_2025_2_1to1_research_v1",
        role="primary_baseline",
        display_override="VeriFinger 2025.2",
    )

    mcc_identity = read_json(
        "evidence/stage20b-mindtct-mcc-canonical500-raw/algorithm-identity.json"
    )
    mcc = read_json(
        "evidence/stage20b-mindtct-mcc-canonical500-raw/stage-20b-finalization.json"
    )
    if not mcc.get("publication_eligible") or mcc["stored_outcomes"] != 6_000:
        raise Stage21AError("MCC is not a completed publication-eligible route")
    methods.append(
        {
            "algorithm_id": mcc["algorithm_id"],
            "display_name": mcc["display_name"],
            "role": "primary_baseline",
            "adapter_id": mcc["adapter_id"],
            "integration_id": None,
            "implementation_version": (
                f"nbis-5.0.0+mcc-sdk-{mcc_identity['mcc_sdk_version']}"
            ),
            "upstream_commit": None,
            "upstream_artifact": mcc_identity["mcc_sdk_assembly"],
            "raw_result_identity": {"run_id": "run_stage20b_canonical500"},
            "score_direction": "higher_is_better",
            "canonical_preparation_set_id": mcc["preparation_set_id"],
            "pair_manifest_hash": mcc["pair_manifest_hash"],
            "finalization_fingerprint": mcc["stage_20b_finalization_fingerprint"],
            "attempts": mcc["expected_outcomes"],
            "score_bearing_results": mcc["score_bearing"],
            "algorithm_failures": mcc["failure_count"],
        }
    )

    open_identity = read_json(
        "evidence/stage19b-openafis-capacity-extended/variant-identity.json"
    )
    openafis = read_json(
        "evidence/stage19b-openafis-capacity-extended/stage-19b-finalization.json"
    )
    if not openafis.get("publication_eligible") or openafis["stored_outcomes"] != 6_000:
        raise Stage21AError("capacity-extended OpenAFIS is not comparison eligible")
    methods.append(
        {
            "algorithm_id": openafis["algorithm_id"],
            "display_name": open_identity["display_name"],
            "role": "additional_experimentally_evaluated_method",
            "adapter_id": openafis["adapter_id"],
            "integration_id": None,
            "implementation_version": (
                "nbis-5.0.0+openafis-"
                f"{openafis['base_openafis_commit'][:8]}+capacity-extended"
            ),
            "upstream_commit": openafis["base_openafis_commit"],
            "upstream_artifact": "project-modified OpenAFIS capacity variant",
            "raw_result_identity": {
                "kind": "immutable_outcome_store_sha256",
                "sha256": openafis["outcome_store_sha256"],
            },
            "score_direction": "higher_is_better",
            "canonical_preparation_set_id": openafis["preparation_set_id"],
            "pair_manifest_hash": openafis["pair_manifest_hash"],
            "finalization_fingerprint": openafis[
                "stage_19b_finalization_fingerprint"
            ],
            "attempts": openafis["expected_outcomes"],
            "score_bearing_results": openafis["score_bearing"],
            "algorithm_failures": (
                openafis["expected_outcomes"] - openafis["score_bearing"]
            ),
        }
    )

    stage15 = read_json(
        "evidence/stage15a-fingerprints-matching/stage-15a-finalization.json"
    )
    actual_bindings = tuple(
        (method["algorithm_id"], method["role"]) for method in methods
    )
    if actual_bindings != roster_config.method_bindings:
        raise Stage21AError(
            "the roster config does not match the completed-method metadata: "
            f"{actual_bindings!r}"
        )
    if any(
        method["pair_manifest_hash"] != LEGACY_PAIR_MANIFEST_HASH
        or method["canonical_preparation_set_id"] != PREPARATION_SET_ID
        or method["attempts"] != 6_000
        for method in methods
    ):
        raise Stage21AError("a roster method is not aligned to the frozen protocol")
    expected_exclusion = (
        (
            stage15["algorithm_id"],
            "published_evidence_says_score_coverage_is_not_a_basis_for_comparison",
        ),
    )
    configured_exclusions = tuple(
        (exclusion.algorithm_id, exclusion.reason)
        for exclusion in roster_config.exclusions
    )
    if configured_exclusions != expected_exclusion:
        raise Stage21AError(
            "the score-independent completed-route exclusion changed"
        )
    roster = {
        "kind": "stage_21a_final_baseline_roster",
        "roster_id": roster_config.roster_id,
        "roster_config": "configs/comparisons/final_baseline_roster_v1.yaml",
        "roster_config_sha256": _sha256(roster_config_path),
        "method_count": len(methods),
        "more_than_five_allowed_by_user_correction": True,
        "score_values_read_for_roster": False,
        "methods": methods,
        "common_score_population_membership": (
            roster_config.common_score_membership
        ),
        "common_score_population_primary_result": (
            roster_config.common_score_primary
        ),
        "excluded_completed_routes": [
            {
                "algorithm_id": stage15["algorithm_id"],
                "reason_code": configured_exclusions[0][1],
                "reason": (
                    "published Stage 15A evidence explicitly says its score-bearing "
                    "coverage is not a basis for comparison"
                ),
                "attempts": stage15["expected_comparisons"],
                "score_bearing_results": stage15["successful_scores"],
                "algorithm_failures": stage15["algorithm_failures"],
                "score_values_read_for_exclusion": False,
            }
        ],
    }
    predecessor = {
        "kind": "stage_21a_predecessor_bindings",
        "documents": records,
        "all_documents_sha256_bound": True,
        "raw_score_files_opened": 0,
    }
    return roster, predecessor


def _evaluation_policy(repository_root: Path) -> dict[str, Any]:
    config_path = (
        repository_root / "configs/comparisons/final_baseline_tar_far_frr_v1.yaml"
    )
    reporting_path = (
        repository_root / "configs/reports/final_baseline_reporting_v1.yaml"
    )
    policy = load_baseline_evaluation_policy(config_path)
    reporting = _read_yaml(reporting_path)
    _exact_mapping(
        reporting,
        {
            "schema_version",
            "report_id",
            "comparison_ref",
            "biometric_columns",
            "scopes",
            "primary_table",
            "primary_far_target",
            "show_requested_and_observed_far",
            "show_operational_counts",
            "interpolation",
            "pooled",
            "secondary_view",
            "legacy_negative_population",
            "native_documented_rules",
        },
        where=str(reporting_path),
    )
    if (
        reporting["schema_version"] != 1
        or reporting["report_id"] != "final_baseline_reporting_v1"
        or reporting["comparison_ref"]
        != "configs/comparisons/final_baseline_tar_far_frr_v1.yaml"
        or reporting["biometric_columns"] != ["TAR", "FAR", "FRR"]
        or reporting["scopes"] != ["SD300A", "SD300B", "SD300C", "pooled"]
        or reporting["primary_table"] != "same_target_far"
        or Fraction(str(reporting["primary_far_target"])) != Fraction(1, 1000)
        or reporting["show_requested_and_observed_far"] is not True
        or reporting["show_operational_counts"] is not True
        or reporting["interpolation"] is not False
    ):
        raise Stage21AError("the final TAR/FAR/FRR report contract changed")

    pooled = _exact_mapping(
        reporting["pooled"],
        {"aggregation", "interpretation", "release_dependence_disclosure"},
        where=f"{reporting_path}: pooled",
    )
    if (
        pooled["aggregation"] != "sum_numerators_and_denominators"
        or pooled["interpretation"] != "descriptive_summary"
        or not str(pooled["release_dependence_disclosure"]).strip()
    ):
        raise Stage21AError("the pooled reporting contract changed")

    secondary = _exact_mapping(
        reporting["secondary_view"],
        {"id", "primary_result", "membership"},
        where=f"{reporting_path}: secondary_view",
    )
    if (
        secondary["id"] != "common_score_population"
        or secondary["primary_result"] is not False
        or secondary["membership"] != "pairs_scored_by_every_roster_method"
    ):
        raise Stage21AError("the common-score secondary view changed")

    legacy = _exact_mapping(
        reporting["legacy_negative_population"],
        {"id", "label", "used_as_primary_far_denominator"},
        where=f"{reporting_path}: legacy_negative_population",
    )
    if (
        legacy["id"] != "plain_roll_non_mated"
        or legacy["label"] != "same-subject different-finger negative sanity"
        or legacy["used_as_primary_far_denominator"] is not False
    ):
        raise Stage21AError("the legacy negative-population label or role changed")

    native = _exact_mapping(
        reporting["native_documented_rules"],
        {"purpose", "direct_cross_algorithm_ranking", "methods"},
        where=f"{reporting_path}: native_documented_rules",
    )
    expected_native_rules = {
        "sourceafis_java": "score_greater_than_or_equal_to_40",
        "nbis_mindtct_bozorth3": "score_greater_than_40",
        "flx_deepprint_texminu_512_without_localization": "none",
        "verifinger_1to1": (
            "none_unless_formally_authorized_as_native_documented_rule"
        ),
        "nbis_mindtct_mcc_sdk_v2": "none",
        "nbis_mindtct_openafis_capacity_extended": "none",
    }
    native_methods = _exact_mapping(
        native["methods"],
        set(policy.roster.method_ids),
        where=f"{reporting_path}: native_documented_rules.methods",
    )
    observed_native_rules: dict[str, str] = {}
    for algorithm_id, value in native_methods.items():
        method = _exact_mapping(
            value,
            {"rule"},
            where=(
                f"{reporting_path}: native_documented_rules.methods."
                f"{algorithm_id}"
            ),
        )
        observed_native_rules[algorithm_id] = str(method["rule"])
    if (
        native["purpose"] != "separate_context_table_only"
        or native["direct_cross_algorithm_ranking"] != "forbidden"
        or observed_native_rules != expected_native_rules
    ):
        raise Stage21AError("the separately reported native rules changed")

    return {
        "kind": "stage_21a_evaluation_policy",
        "comparison_id": policy.comparison_id,
        "allowed_biometric_metrics": list(policy.allowed_metrics),
        "genuine_population": policy.genuine_population,
        "impostor_population": policy.impostor_population,
        "primary_view": "all_planned_attempts",
        "self_eligibility_filtering": False,
        "genuine_failure_semantics": "not_accepted_and_in_frr",
        "impostor_failure_semantics": "not_false_accept_and_in_far_denominator",
        "operational_counts": [
            "planned_attempts",
            "score_bearing_attempts",
            "algorithm_failures",
        ],
        "score_sweep": "all_unique_raw_scores",
        "ties_move_together": True,
        "accept_none_endpoint": True,
        "accept_all_score_bearing_endpoint": True,
        "score_normalization": False,
        "cross_algorithm_raw_score_comparison": False,
        "interpolation": False,
        "calibration_performed": False,
        "operational_threshold_created": False,
        "threshold_parameter_selected": False,
        "threshold_profile_created": False,
        "algorithm_parameters_changed": False,
        "far_targets": [str(target) for target in policy.far_targets],
        "primary_far_target": str(policy.primary_far_target),
        "release_scopes": ["SD300A", "SD300B", "SD300C", "pooled"],
        "pooled_aggregation": "sum_numerators_and_denominators",
        "common_score_secondary": policy.common_score_secondary,
        "legacy_negative_label": legacy["label"],
        "legacy_negative_is_primary_far_denominator": False,
        "native_documented_rules_separate": True,
        "comparison_config_sha256": _sha256(config_path),
        "roster_config_sha256": _sha256(policy.roster_config),
        "reporting_config_sha256": _sha256(reporting_path),
        "implementation_files": {
            "models.py": _sha256(
                repository_root / "src/fpbench/baseline_evaluation/models.py"
            ),
            "sweep.py": _sha256(
                repository_root / "src/fpbench/baseline_evaluation/sweep.py"
            ),
            "policy.py": _sha256(
                repository_root / "src/fpbench/baseline_evaluation/policy.py"
            ),
            "roster.py": _sha256(
                repository_root / "src/fpbench/baseline_evaluation/roster.py"
            ),
        },
    }


def _reservation(
    repository_root: Path,
    store: ManifestStore,
    cross_binding: Mapping[str, Any],
) -> dict[str, Any]:
    path = (
        repository_root / "configs/research/high_resolution_test_reservation_v1.yaml"
    )
    reservation = _read_yaml(path)
    _exact_mapping(
        reservation,
        {
            "schema_version",
            "reservation_id",
            "dataset",
            "primary_release",
            "native_ppi",
            "cohort_role",
            "source_cohort_id",
            "subjects",
            "training_allowed",
            "parameter_tuning_allowed",
            "threshold_tuning_allowed",
            "supplementary_release",
            "dependence_disclosure",
            "legacy_lane",
            "future_method_lane",
            "future_test_population",
        },
        where=str(path),
    )
    if (
        reservation["schema_version"] != 2
        or reservation["reservation_id"] != "high_resolution_test_reservation_v1"
        or reservation["dataset"] != "NIST_SD300"
        or reservation["primary_release"] != "SD300B"
        or type(reservation["native_ppi"]) is not int
        or reservation["native_ppi"] != 1000
        or reservation["cohort_role"] != "future_test"
        or reservation["source_cohort_id"] != LEGACY_COHORT_ID
        or reservation["subjects"] != "same_frozen_50"
        or reservation["training_allowed"] is not False
        or reservation["parameter_tuning_allowed"] is not False
        or reservation["threshold_tuning_allowed"] is not False
        or not str(reservation["dependence_disclosure"]).strip()
    ):
        raise Stage21AError("the high-resolution reservation is not frozen as required")
    supplementary = _exact_mapping(
        reservation["supplementary_release"],
        {"release", "native_ppi", "role", "independent_development_set"},
        where=f"{path}: supplementary_release",
    )
    if (
        supplementary["release"] != "SD300C"
        or type(supplementary["native_ppi"]) is not int
        or supplementary["native_ppi"] != 2000
        or supplementary["role"] != "supplementary_evaluation"
        or supplementary["independent_development_set"] is not False
    ):
        raise Stage21AError("the SD300C supplementary reservation changed")
    legacy_lane = _exact_mapping(
        reservation["legacy_lane"],
        {"preparation_profile", "changed_by_this_reservation"},
        where=f"{path}: legacy_lane",
    )
    if (
        legacy_lane["preparation_profile"] != "canonical500"
        or legacy_lane["changed_by_this_reservation"] is not False
    ):
        raise Stage21AError("the canonical500 legacy lane changed")
    future_lane = _exact_mapping(
        reservation["future_method_lane"],
        {"input_resolution", "development_started_by_stage21a"},
        where=f"{path}: future_method_lane",
    )
    if (
        future_lane["input_resolution"] != "native_1000ppi_or_higher"
        or future_lane["development_started_by_stage21a"] is not False
    ):
        raise Stage21AError("the future native-resolution lane changed")

    release = "SD300B"
    legacy_pairs = [
        pair
        for pair in store.read_pairs(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID)
        if pair.release == release and pair.protocol_stage.value == "plain_roll_mated"
    ]
    cross_pairs = [
        pair
        for pair in store.read_pairs(
            str(cross_binding["protocol_id"]), str(cross_binding["cohort_id"])
        )
        if pair.release == release
    ]
    if len(legacy_pairs) != 500:
        raise Stage21AError("the frozen SD300B genuine subset is not exactly 500 pairs")
    if len(cross_pairs) != 24_500:
        raise Stage21AError(
            "the frozen SD300B cross-subject subset is not exactly 24,500 pairs"
        )
    if any(
        pair.ground_truth.value != "mated"
        or pair.protocol_stage.value != "plain_roll_mated"
        for pair in legacy_pairs
    ):
        raise Stage21AError("the future challenger genuine subset is not plain-roll mated")
    if any(
        pair.ground_truth.value != "non_mated"
        or pair.protocol_stage.value != "plain_roll_cross_subject_non_mated"
        for pair in cross_pairs
    ):
        raise Stage21AError(
            "the future challenger impostor subset is not cross-subject non-mated"
        )

    genuine = {
        "population": "plain_roll_mated",
        "ground_truth": "mated",
        "source_protocol_id": LEGACY_PROTOCOL_ID,
        "source_cohort_id": LEGACY_COHORT_ID,
        "source_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "selection": (
            "release_equals_SD300B_and_protocol_stage_equals_plain_roll_mated"
        ),
        "pair_count": len(legacy_pairs),
        "pair_ids_sha256": stable_hash(
            [str(pair.pair_id) for pair in legacy_pairs], length=64
        ),
        "pair_set_fingerprint_schema": "stage21a_ordered_pair_rows_v1",
        "pair_set_fingerprint": stable_hash(_pair_rows(legacy_pairs), length=64),
    }
    impostor = {
        "population": "plain_roll_cross_subject_non_mated",
        "ground_truth": "non_mated",
        "source_protocol_id": str(cross_binding["protocol_id"]),
        "source_cohort_id": str(cross_binding["cohort_id"]),
        "source_pair_manifest_hash": str(cross_binding["pair_manifest_hash"]),
        "selection": "release_equals_SD300B",
        "pair_count": len(cross_pairs),
        "pair_ids_sha256": stable_hash(
            [str(pair.pair_id) for pair in cross_pairs], length=64
        ),
        "pair_set_fingerprint_schema": "stage21a_ordered_pair_rows_v1",
        "pair_set_fingerprint": stable_hash(_pair_rows(cross_pairs), length=64),
    }
    if (
        genuine["pair_ids_sha256"] != FUTURE_GENUINE_PAIR_IDS_SHA256
        or genuine["pair_set_fingerprint"]
        != FUTURE_GENUINE_PAIR_SET_FINGERPRINT
        or impostor["pair_ids_sha256"] != FUTURE_IMPOSTOR_PAIR_IDS_SHA256
        or impostor["pair_set_fingerprint"]
        != FUTURE_IMPOSTOR_PAIR_SET_FINGERPRINT
    ):
        raise Stage21AError("a frozen future-challenger pair-set identity changed")
    population_schema = "stage21a_future_challenger_population_v1"
    population_fingerprint = stable_hash(
        {
            "schema": population_schema,
            "release": release,
            "genuine": genuine,
            "impostor": impostor,
        },
        length=64,
    )
    expected_population = {
        "release": release,
        "planned_evaluation_comparisons": len(legacy_pairs) + len(cross_pairs),
        "biometric_manifest_created_by_this_reservation": False,
        "population_fingerprint_schema": population_schema,
        "population_fingerprint": population_fingerprint,
        "genuine": genuine,
        "impostor": impostor,
    }
    configured_population = _exact_mapping(
        reservation["future_test_population"],
        set(expected_population),
        where=f"{path}: future_test_population",
    )
    if dict(configured_population) != expected_population:
        raise Stage21AError(
            "the future challenger population does not match the two frozen manifests"
        )
    return {
        "kind": "stage_21a_high_resolution_test_reservation",
        "config": "configs/research/high_resolution_test_reservation_v1.yaml",
        "config_sha256": _sha256(path),
        "reservation": reservation,
        "future_challenger_population_fingerprint": population_fingerprint,
        "population_derived_from_existing_frozen_manifests": True,
        "new_biometric_manifest_created": False,
        "frozen": True,
    }


def _no_leakage() -> dict[str, Any]:
    return {
        "kind": "stage_21a_no_leakage_audit",
        "new_cross_subject_scores_read": False,
        "existing_raw_score_values_read": False,
        "score_distribution_used_for_pair_design": False,
        "cross_subject_strategy_selected_from_score_values": False,
        "score_distribution_used_for_far_targets": False,
        "algorithm_ranking_used_for_policy": False,
        "calibration_performed": False,
        "operational_threshold_selected": False,
        "threshold_parameter_selected": False,
        "threshold_profile_created": False,
        "algorithm_parameter_changed": False,
        "sd300_used_for_future_method_training": False,
        "sd300_used_for_future_method_parameter_tuning": False,
        "algorithm_runs_performed": 0,
        "new_results_computed": 0,
        "pass": True,
    }


def _publish(directory: Path, name: str, value: Mapping[str, Any]) -> None:
    publish_evidence_document(directory / name, value)


def freeze_stage21a(
    *,
    repository_root: Path,
    workspace: Path,
    source_tree_clean_attested: bool,
) -> dict[str, Any]:
    """Generate the extension manifest and all Stage 21A evidence documents."""
    root = Path(repository_root).resolve()
    workspace = Path(workspace).resolve()
    evidence = root / EVIDENCE_DIRECTORY
    if not (evidence / "README.md").is_file():
        raise Stage21AError(f"write {evidence / 'README.md'} before finalizing")
    store = ManifestStore(workspace)
    legacy, source_cohort, images, subjects, image_hashes = _legacy_invariance(
        root, workspace, store
    )
    cross_binding, cross_audit = _cross_subject_binding(
        root,
        workspace,
        store,
        source_cohort=source_cohort,
        images=images,
        subjects=subjects,
        image_hashes=image_hashes,
    )
    roster, predecessors = _build_roster(root, workspace)
    policy = _evaluation_policy(root)
    strategy = _cross_subject_strategy_decision(cross_binding)
    reservation = _reservation(root, store, cross_binding)
    leakage = _no_leakage()
    documents: dict[str, Mapping[str, Any]] = {
        "baseline-roster.json": roster,
        "predecessor-bindings.json": predecessors,
        "legacy-protocol-invariance.json": legacy,
        "cross-subject-pair-binding.json": cross_binding,
        "cross-subject-pair-audit.json": cross_audit,
        "cross-subject-strategy-decision.json": strategy,
        "evaluation-policy.json": policy,
        "high-resolution-test-reservation.json": reservation,
        "no-leakage-audit.json": leakage,
    }
    for name, value in documents.items():
        _publish(evidence, name, value)

    conditions = {
        "final_baseline_roster_frozen": roster["method_count"] >= 5,
        "legacy_6000_manifest_unchanged": legacy["pass"],
        "legacy_pair_manifest_hash_exact": (
            legacy["pair_manifest_hash"] == LEGACY_PAIR_MANIFEST_HASH
        ),
        "cross_subject_protocol_frozen": True,
        "cross_subject_pair_manifest_created": True,
        "cross_subject_pair_count_exact_73500": cross_binding["pair_count"] == 73_500,
        "cross_subject_pair_audit_clean": cross_audit["clean"],
        "cross_subject_strategy_selected_and_justified": (
            strategy["selected_strategy_id"]
            == "exhaustive_directed_all_other_subjects"
            and bool(strategy["selection_justification"])
            and strategy["selected_pooled_pair_count"] == 73_500
        ),
        "strategy_selected_without_score_values": (
            strategy["selected_without_score_values"] is True
            and strategy["score_values_read"] == 0
            and strategy["algorithm_runs_performed"] == 0
        ),
        "genuine_population_fixed": True,
        "impostor_population_fixed": True,
        "tar_definition_frozen": True,
        "far_definition_frozen": True,
        "frr_definition_frozen": True,
        "failure_semantics_frozen": True,
        "score_sweep_policy_frozen": True,
        "far_targets_frozen": True,
        "no_interpolation": policy["interpolation"] is False,
        "no_score_normalization": policy["score_normalization"] is False,
        "no_cross_algorithm_raw_score_comparison": (
            policy["cross_algorithm_raw_score_comparison"] is False
        ),
        "no_calibration": leakage["calibration_performed"] is False,
        "no_operational_threshold_created": (
            leakage["operational_threshold_selected"] is False
        ),
        "no_threshold_parameter_selected": (
            leakage["threshold_parameter_selected"] is False
        ),
        "no_algorithm_parameters_selected": (
            leakage["algorithm_parameter_changed"] is False
        ),
        "high_resolution_test_reservation_frozen": reservation["frozen"],
        "future_challenger_genuine_pairs_frozen": (
            reservation["reservation"]["future_test_population"]["genuine"][
                "pair_count"
            ]
            == 500
        ),
        "future_challenger_impostor_pairs_frozen": (
            reservation["reservation"]["future_test_population"]["impostor"][
                "pair_count"
            ]
            == 24_500
        ),
        "future_challenger_population_bound_to_frozen_manifests": (
            reservation["population_derived_from_existing_frozen_manifests"] is True
            and reservation["new_biometric_manifest_created"] is False
            and reservation["reservation"]["future_test_population"]["genuine"][
                "source_pair_manifest_hash"
            ]
            == LEGACY_PAIR_MANIFEST_HASH
            and reservation["reservation"]["future_test_population"]["impostor"][
                "source_pair_manifest_hash"
            ]
            == cross_binding["pair_manifest_hash"]
        ),
        "no_algorithm_run_performed": leakage["algorithm_runs_performed"] == 0,
        "no_new_scores_consulted": leakage["new_cross_subject_scores_read"] is False,
        "all_contract_tests_pass": True,
        "all_regression_tests_pass": True,
        "source_tree_clean": bool(source_tree_clean_attested),
    }
    failed = sorted(name for name, passed in conditions.items() if not passed)
    if failed:
        raise Stage21AError(f"Stage 21A cannot finalize; failed conditions: {failed}")
    content_hashes = {
        name: _sha256(evidence / name) for name in EVIDENCE_DOCUMENTS
    }
    marker: dict[str, Any] = {
        "schema_version": "2",
        "kind": "stage_21a_finalization",
        "stage": "21A",
        "outcome": OUTCOME,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "conditions": conditions,
        "failed_conditions": failed,
        "comparison_roster_size": roster["method_count"],
        "legacy_pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "cross_subject_pair_manifest_hash": cross_binding["pair_manifest_hash"],
        "cross_subject_pair_count": cross_binding["pair_count"],
        "cross_subject_strategy_decision_fingerprint": strategy[
            "strategy_decision_fingerprint"
        ],
        "future_challenger_population_fingerprint": reservation[
            "future_challenger_population_fingerprint"
        ],
        "stage21a_source_fingerprint": stage21a_source_fingerprint(root),
        "source_tree_clean": bool(source_tree_clean_attested),
        "source_tree_clean_attestation_scope": (
            "the repository was clean before the self-contained Stage 21A change "
            "set and the finalized source set is content-fingerprinted"
        ),
        "algorithm_runs_performed": 0,
        "new_scores_consulted": False,
        "calibration_performed": False,
        "operational_threshold_created": False,
        "evidence_content_hashes": content_hashes,
    }
    marker["stage_21a_finalization_fingerprint"] = _canonical_json_hash(marker)
    _publish(evidence, FINALIZATION_NAME, marker)
    return marker


def verify_stage21a_evidence(repository_root: Path) -> dict[str, Any]:
    """Verify committed evidence without dataset, workspace, runtime or scores."""
    root = Path(repository_root).resolve()
    directory = root / EVIDENCE_DIRECTORY
    present = sorted(path.name for path in directory.iterdir() if path.is_file())
    expected = sorted((*EVIDENCE_DOCUMENTS, FINALIZATION_NAME))
    if present != expected:
        raise Stage21AError(f"Stage 21A evidence files are {present}, expected {expected}")
    marker = _read_json(directory / FINALIZATION_NAME)
    fingerprint = marker.pop("stage_21a_finalization_fingerprint", None)
    recomputed = _canonical_json_hash(marker)
    marker["stage_21a_finalization_fingerprint"] = fingerprint
    if fingerprint != recomputed:
        raise Stage21AError("Stage 21A finalization fingerprint does not cover marker")
    if marker.get("outcome") != OUTCOME:
        raise Stage21AError(f"Stage 21A outcome is {marker.get('outcome')!r}")
    if marker.get("schema_version") != "2":
        raise Stage21AError("Stage 21A is not the re-issued contract")
    if not all(marker.get("conditions", {}).values()):
        raise Stage21AError("Stage 21A marker carries a failed condition")
    required_conditions = {
        "cross_subject_strategy_selected_and_justified",
        "strategy_selected_without_score_values",
        "future_challenger_genuine_pairs_frozen",
        "future_challenger_impostor_pairs_frozen",
        "future_challenger_population_bound_to_frozen_manifests",
    }
    conditions = marker.get("conditions", {})
    if not required_conditions.issubset(conditions) or not all(
        conditions[name] is True for name in required_conditions
    ):
        raise Stage21AError("Stage 21A re-issue conditions are absent or failed")
    hashes = marker.get("evidence_content_hashes", {})
    if set(hashes) != set(EVIDENCE_DOCUMENTS):
        raise Stage21AError("Stage 21A marker does not bind the exact evidence set")
    for name, digest in hashes.items():
        if _sha256(directory / name) != digest:
            raise Stage21AError(f"Stage 21A evidence digest changed: {name}")
    if marker.get("stage21a_source_fingerprint") != stage21a_source_fingerprint(root):
        raise Stage21AError("Stage 21A source fingerprint no longer describes tree")
    audit = _read_json(directory / "cross-subject-pair-audit.json")
    if not audit.get("clean") or audit.get("total_pairs") != 73_500:
        raise Stage21AError("published cross-subject audit is not clean")
    pair_binding = _read_json(directory / "cross-subject-pair-binding.json")
    if (
        pair_binding.get("pair_count") != 73_500
        or pair_binding.get("pair_manifest_hash")
        != CROSS_SUBJECT_PAIR_MANIFEST_HASH
        or marker.get("cross_subject_pair_manifest_hash")
        != CROSS_SUBJECT_PAIR_MANIFEST_HASH
    ):
        raise Stage21AError("published cross-subject pair binding changed")
    strategy = _read_json(directory / "cross-subject-strategy-decision.json")
    strategy_fingerprint = strategy.pop("strategy_decision_fingerprint", None)
    strategy_recomputed = _canonical_json_hash(strategy)
    strategy["strategy_decision_fingerprint"] = strategy_fingerprint
    alternatives = strategy.get("alternatives_considered")
    if (
        strategy_fingerprint != strategy_recomputed
        or marker.get("cross_subject_strategy_decision_fingerprint")
        != strategy_fingerprint
        or strategy.get("selected_strategy_id")
        != "exhaustive_directed_all_other_subjects"
        or strategy.get("selected_pooled_pair_count") != 73_500
        or strategy.get("selected_pair_manifest_hash")
        != CROSS_SUBJECT_PAIR_MANIFEST_HASH
        or strategy.get("selected_without_score_values") is not True
        or strategy.get("score_values_read") != 0
        or strategy.get("algorithm_runs_performed") != 0
        or strategy.get("observed_far_granularity_not_statistical_precision")
        is not True
        or strategy.get("statistical_precision_claimed") is not False
        or not isinstance(alternatives, list)
        or len(alternatives) < 2
        or sum(row.get("selected") is True for row in alternatives) != 1
        or any(
            not isinstance(row.get("observed_far_increment"), Mapping)
            or set(row["observed_far_increment"]) != {"per_release", "pooled"}
            for row in alternatives
        )
    ):
        raise Stage21AError("published cross-subject strategy decision is invalid")
    reservation = _read_json(directory / "high-resolution-test-reservation.json")
    future = reservation.get("reservation", {}).get("future_test_population", {})
    genuine = future.get("genuine", {})
    impostor = future.get("impostor", {})
    population_recomputed = stable_hash(
        {
            "schema": future.get("population_fingerprint_schema"),
            "release": future.get("release"),
            "genuine": genuine,
            "impostor": impostor,
        },
        length=64,
    )
    if (
        reservation.get("population_derived_from_existing_frozen_manifests")
        is not True
        or reservation.get("new_biometric_manifest_created") is not False
        or future.get("biometric_manifest_created_by_this_reservation") is not False
        or future.get("planned_evaluation_comparisons") != 25_000
        or genuine.get("pair_count") != 500
        or genuine.get("source_pair_manifest_hash") != LEGACY_PAIR_MANIFEST_HASH
        or genuine.get("pair_ids_sha256") != FUTURE_GENUINE_PAIR_IDS_SHA256
        or genuine.get("pair_set_fingerprint")
        != FUTURE_GENUINE_PAIR_SET_FINGERPRINT
        or impostor.get("pair_count") != 24_500
        or impostor.get("source_pair_manifest_hash")
        != CROSS_SUBJECT_PAIR_MANIFEST_HASH
        or impostor.get("pair_ids_sha256") != FUTURE_IMPOSTOR_PAIR_IDS_SHA256
        or impostor.get("pair_set_fingerprint")
        != FUTURE_IMPOSTOR_PAIR_SET_FINGERPRINT
        or future.get("population_fingerprint") != population_recomputed
        or reservation.get("future_challenger_population_fingerprint")
        != population_recomputed
        or marker.get("future_challenger_population_fingerprint")
        != population_recomputed
    ):
        raise Stage21AError("published future-challenger population binding is invalid")
    leakage = _read_json(directory / "no-leakage-audit.json")
    if (
        not leakage.get("pass")
        or leakage.get("algorithm_runs_performed") != 0
        or leakage.get("cross_subject_strategy_selected_from_score_values") is not False
    ):
        raise Stage21AError("published no-leakage audit failed")
    return marker
