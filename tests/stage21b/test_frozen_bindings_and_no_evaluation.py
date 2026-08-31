from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from fpbench.stage21b.bindings import load_frozen_pairs, load_stage21a_binding
from fpbench.stage21b.bindings import _require_reissued_stage21a_contract
from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo
from fpbench.stage21b.adapters import (
    FailureDisposition,
    accepted_predecessor_digests,
    classifier_for,
)
from fpbench.stage21b.constants import (
    EXECUTION_POLICY_PATH,
    EXPECTED_PAIRS_PER_METHOD,
    LEGACY_PAIR_MANIFEST_HASH,
    PREPARATION_PROFILE_ID,
    PREPARATION_SET_ID,
)
from fpbench.stage21b.errors import Stage21BPreflightError
from fpbench.stage21b.evidence import _no_evaluation_document
from fpbench.stage21b.policy import load_execution_policy

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.stage21b_contract


def test_stage21a_final_marker_is_consumed_dynamically_and_all_six_routes_bind() -> None:
    binding = load_stage21a_binding(ROOT)
    marker = json.loads(
        (
            ROOT
            / "evidence/stage21a-final-baseline-evaluation-protocol/"
            "stage-21a-finalization.json"
        ).read_text(encoding="utf-8")
    )
    assert binding.finalization_fingerprint == marker[
        "stage_21a_finalization_fingerprint"
    ]
    assert binding.pair_count == EXPECTED_PAIRS_PER_METHOD
    assert len(binding.algorithms) == 6
    assert set(binding.algorithm_ids) == {
        "sourceafis_java",
        "nbis_mindtct_bozorth3",
        "flx_deepprint_texminu_512_without_localization",
        "verifinger_1to1",
        "nbis_mindtct_mcc_sdk_v2",
        "nbis_mindtct_openafis_capacity_extended",
    }
    assert binding.legacy_pair_manifest_hash == LEGACY_PAIR_MANIFEST_HASH
    assert set(binding.accepted_legacy_result_identities) == set(
        binding.algorithm_ids
    )
    assert len(binding.accepted_legacy_result_identities_fingerprint) == 64
    assert binding.strategy_decision["selected_without_score_values"] is True
    assert binding.future_challenger_binding["genuine"]["pair_count"] == 500
    assert binding.future_challenger_binding["impostor"]["pair_count"] == 24_500


@pytest.mark.parametrize("missing", ["strategy_condition", "future_population"])
def test_preflight_refuses_pre_reissue_stage21a_contract(missing: str) -> None:
    directory = ROOT / "evidence/stage21a-final-baseline-evaluation-protocol"
    marker = _read_json(directory / "stage-21a-finalization.json")
    strategy = _read_json(directory / "cross-subject-strategy-decision.json")
    reservation = _read_json(directory / "high-resolution-test-reservation.json")
    pair = _read_json(directory / "cross-subject-pair-binding.json")
    legacy = _read_json(directory / "legacy-protocol-invariance.json")
    if missing == "strategy_condition":
        marker["conditions"].pop("cross_subject_strategy_selected_and_justified")
    else:
        reservation["reservation"].pop("future_test_population")
    with pytest.raises(Stage21BPreflightError, match="strategy|future|re-issue"):
        _require_reissued_stage21a_contract(
            marker=marker,
            strategy=strategy,
            reservation=reservation,
            pair_binding=pair,
            legacy_binding=legacy,
        )


def test_local_predecessor_closure_carries_all_six_finalizations() -> None:
    local_finalization = (
        ROOT
        / "workspace/results/run_4c59fa02a6ab/research-finalization.json"
    )
    if not local_finalization.is_file():
        pytest.skip("local predecessor artifacts are absent")
    binding = load_stage21a_binding(ROOT, require_predecessor_files=True)
    for algorithm in binding.algorithms:
        assert algorithm.raw_result_identity
        route_digests = accepted_predecessor_digests(ROOT, binding=algorithm)
        assert algorithm.predecessor_finalization_fingerprint in route_digests


def test_frozen_execution_policy_exactly_covers_stage21a_roster() -> None:
    binding = load_stage21a_binding(ROOT)
    policy = load_execution_policy(ROOT / EXECUTION_POLICY_PATH)
    policy.require_roster_adapters(binding.adapter_ids)
    assert policy.preparation_set_id == PREPARATION_SET_ID
    assert policy.preparation_profile_id == PREPARATION_PROFILE_ID
    assert policy.concurrency == 1
    assert policy.orchestrator_algorithm_retries == 0
    assert policy.optimizations_enabled is False
    with pytest.raises(Stage21BPreflightError):
        policy.require_roster_adapters(binding.adapter_ids[:-1])


def test_local_cross_subject_manifest_is_exact_and_wrong_binding_is_refused() -> None:
    binding = load_stage21a_binding(ROOT)
    workspace = ROOT / "workspace"
    manifest = (
        workspace
        / "manifests/protocols/sd300_cross_subject_non_mated_v1/cohorts"
        / binding.cohort_id
        / "pairs.parquet"
    )
    if not manifest.is_file():
        pytest.skip("local cross-subject manifest is absent")
    snapshot = load_frozen_pairs(workspace=workspace, binding=binding)
    assert len(snapshot.pairs) == 73_500
    assert snapshot.pair_manifest_hash == binding.pair_manifest_hash
    assert all(pair.ground_truth.value == "non_mated" for pair in snapshot.pairs)
    wrong = dataclasses.replace(binding, pair_manifest_hash="0" * 64)
    with pytest.raises(Stage21BPreflightError, match="does not match"):
        load_frozen_pairs(workspace=workspace, binding=wrong)


def test_stage21b_has_no_import_edge_to_evaluation_or_calibration() -> None:
    audit = _no_evaluation_document(ROOT)
    assert audit["forbidden_evaluation_imports"] == []
    assert audit["new_raw_scores_generated"] is True
    assert audit["tar_computed"] is False
    for path in (ROOT / "src/fpbench/stage21b").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not any(name.startswith("fpbench.baseline_evaluation") for name in imported)
        assert not any("calibration" in name.lower() for name in imported)


def test_composed_route_failure_split_preserves_predecessor_semantics() -> None:
    openafis = classifier_for("openafis_stage19b_certified_v1")
    mcc = classifier_for("mcc_stage20b_certified_v1")

    def failure(*, status_key: str, status: str, reason: str = "vendor_refusal"):
        return FailureInfo(
            code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
            stage=FailureStage.EXTRACTION,
            message="synthetic frozen-route failure",
            details={status_key: status, "reason": reason},
        )

    assert openafis(
        failure(
            status_key="stage19_status",
            status="OPENAFIS_TEMPLATE_FAILED_LEFT",
        )
    ) is FailureDisposition.ALGORITHM
    assert openafis(
        failure(status_key="stage19_status", status="OPENAFIS_MATCH_FAILED")
    ) is FailureDisposition.INFRASTRUCTURE

    assert mcc(
        failure(status_key="stage20b_status", status="MCC_TEMPLATE_REFUSAL_LEFT")
    ) is FailureDisposition.ALGORITHM
    assert mcc(
        failure(
            status_key="stage20b_status",
            status="MCC_TEMPLATE_REFUSAL_LEFT",
            reason="invalid_raster_dimensions",
        )
    ) is FailureDisposition.INFRASTRUCTURE
    assert mcc(
        failure(status_key="stage20b_status", status="MCC_INVALID_SCORE")
    ) is FailureDisposition.ALGORITHM
    assert mcc(
        failure(status_key="stage20b_status", status="MCC_RUNTIME_FAILURE")
    ) is FailureDisposition.INFRASTRUCTURE


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
