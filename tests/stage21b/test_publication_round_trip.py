"""The production publisher's success path without invoking an SD300 matcher.

Production has one finalization API.  It discovers and verifies six sealed raw
stores before it can write a PASS marker.  These tests replace those expensive
read boundaries with already-verified summaries, then exercise that same API
into a temporary evidence directory and read it back with the offline verifier.
There is deliberately no document-only publication seam.
"""

from __future__ import annotations

import json
import shutil
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

import fpbench.stage21b.evidence as stage21b_evidence
from fpbench.core.json_io import publish_evidence_document
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.bindings import load_stage21a_binding
from fpbench.stage21b.constants import (
    EXECUTION_POLICY_PATH,
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
    STAGE21B_MARKER,
)
from fpbench.stage21b.errors import Stage21BIntegrityError
from fpbench.stage21b.evidence import (
    publish_stage21b_evidence,
    verify_stage21b_evidence,
)
from fpbench.stage21b.models import FrozenRunSpec
from fpbench.stage21b.policy import load_execution_policy
from fpbench.stage21b.source_freeze import (
    execution_source_file_sha256s,
    source_file_sha256,
)
from .helpers import digest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.stage21b_contract

_ORCHESTRATOR_RUNTIME = {
    "python_implementation": "CPython",
    "python_version": "3.12.0",
    "python_executable_identity": "python.exe",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "sqlite_version": "3.45.1",
    "pyarrow_version": "16.0.0",
}

_PRIVATE_CONFIG = digest("private-adapter-config")


@lru_cache(maxsize=None)
def _closure_files(adapter_id: str, algorithm_config: str) -> dict[str, str]:
    return execution_source_file_sha256s(
        repository_root=ROOT,
        algorithm_config=ROOT / algorithm_config,
        include_flx=adapter_id == "flx_pytorch_subprocess",
    )


def _source_fingerprint(
    runtime_fingerprint: str, files: dict[str, str]
) -> str:
    return stable_hash(
        {
            "schema": "stage21b_execution_source_v1",
            "files": files,
            "private_adapter_config_sha256": _PRIVATE_CONFIG,
            "runtime_identity_fingerprint": runtime_fingerprint,
        },
        length=64,
    )


def _source_binding(spec: FrozenRunSpec, files: dict[str, str]) -> dict:
    return {
        "schema_version": "1",
        "stage": "21B",
        "run_id": spec.run_id,
        "run_spec_fingerprint": spec.run_spec_fingerprint,
        "execution_source_fingerprint": spec.execution_source_fingerprint,
        "execution_source_revision": spec.execution_source_revision,
        "file_sha256s": dict(files),
        "private_adapter_config_sha256": _PRIVATE_CONFIG,
        "runtime_identity_fingerprint": spec.runtime_identity_fingerprint,
        "preflight_environment_validation_ms": 12.5,
        "preflight_environment_validation_timing_definition": (
            "wall time for the certified adapter validate_environment call"
        ),
    }


def _material(stage21a, policy):
    specs: dict[str, FrozenRunSpec] = {}
    verified: dict[str, dict] = {}
    source_bindings: dict[str, dict] = {}
    for index, algorithm in enumerate(stage21a.algorithms):
        route = policy.routes[algorithm.adapter_id]
        runtime_fingerprint = digest("runtime:" + algorithm.algorithm_id)
        source_files = _closure_files(
            algorithm.adapter_id, route.algorithm_config.as_posix()
        )
        spec = FrozenRunSpec.create(
            created_utc="2026-09-01T00:00:00+00:00",
            stage21a_finalization_fingerprint=stage21a.finalization_fingerprint,
            stage21a_source_fingerprint=stage21a.source_fingerprint,
            high_resolution_reservation_fingerprint=(
                stage21a.high_resolution_reservation_fingerprint
            ),
            roster_id=stage21a.roster_id,
            roster_fingerprint=stage21a.roster_fingerprint,
            algorithm_id=algorithm.algorithm_id,
            adapter_id=algorithm.adapter_id,
            integration_id=algorithm.integration_id,
            implementation_version=algorithm.implementation_version,
            adapter_descriptor_fingerprint=digest(
                "descriptor:" + algorithm.algorithm_id
            ),
            runtime_identity_fingerprint=runtime_fingerprint,
            runtime_binding={
                "assets": [
                    {"role": "bridge", "sha256": digest("asset"), "size_bytes": 4096}
                ],
                "orchestrator_runtime": dict(_ORCHESTRATOR_RUNTIME),
            },
            predecessor_finalization_fingerprint=(
                algorithm.predecessor_finalization_fingerprint
            ),
            score_direction=algorithm.score_direction,
            protocol_id=stage21a.pair_binding["protocol_id"],
            protocol_config_sha256=stage21a.protocol_config_sha256,
            pair_manifest_hash=stage21a.pair_manifest_hash,
            pair_ids_sha256=stage21a.pair_ids_sha256,
            planned_pair_input_fingerprint=digest("planned-pairs"),
            pair_count=EXPECTED_PAIRS_PER_METHOD,
            preparation_set_id=PREPARATION_SET_ID,
            preparation_set_fingerprint=digest("prep-set"),
            preparation_profile_id=PREPARATION_PROFILE_ID,
            preparation_profile_fingerprint=digest("prep-profile"),
            execution_source_fingerprint=_source_fingerprint(
                runtime_fingerprint, source_files
            ),
            execution_source_revision="0" * 40,
            algorithm_execution_config_sha256=source_file_sha256(
                ROOT / route.algorithm_config
            ),
            private_adapter_config_sha256=_PRIVATE_CONFIG,
            expected_attempts=EXPECTED_PAIRS_PER_METHOD,
            timeout_seconds=route.timeout_seconds,
            concurrency=1,
            execution_strategy=policy.execution_strategy,
            metrics_allowed=False,
            calibration_allowed=False,
            threshold_allowed=False,
            score_transform_allowed=False,
            orchestrator_algorithm_retries=0,
            infrastructure_resume_allowed=True,
        )
        # One method carries algorithm failures, because a Stage 21B PASS is
        # complete outcome coverage and not 100% score coverage.
        failures = 81 if index == 3 else 0
        specs[algorithm.algorithm_id] = spec
        source_bindings[algorithm.algorithm_id] = _source_binding(
            spec, source_files
        )
        verified[algorithm.algorithm_id] = {
            "algorithm_id": algorithm.algorithm_id,
            "run_id": spec.run_id,
            "result_set_id": spec.result_set_id,
            "run_spec_fingerprint": spec.run_spec_fingerprint,
            "result_set_fingerprint": digest("result-set:" + algorithm.algorithm_id),
            "pair_manifest_hash": spec.pair_manifest_hash,
            "pair_ids_sha256": spec.pair_ids_sha256,
            "planned_pair_input_fingerprint": spec.planned_pair_input_fingerprint,
            "preparation_set_id": spec.preparation_set_id,
            "preparation_set_fingerprint": spec.preparation_set_fingerprint,
            "preparation_profile_id": spec.preparation_profile_id,
            "planned_attempts": EXPECTED_PAIRS_PER_METHOD,
            "terminal_outcomes": EXPECTED_PAIRS_PER_METHOD,
            "score_bearing_outcomes": EXPECTED_PAIRS_PER_METHOD - failures,
            "algorithm_failures": failures,
            "failure_classifications": (
                {"template_extraction_failed": failures} if failures else {}
            ),
            "release_counts": {
                release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES
            },
            "attempt_records": EXPECTED_PAIRS_PER_METHOD,
            "infrastructure_gaps": 0,
            "infrastructure_events_before_completion": {},
            "timing": {"adapter_wall_time_total_ms": 1234.5},
            "outcomes_file_sha256": digest("outcomes:" + algorithm.algorithm_id),
            "attempts_file_sha256": digest("attempts:" + algorithm.algorithm_id),
            "result_set_manifest_sha256": digest("seal:" + algorithm.algorithm_id),
            "result_set_manifest_fingerprint": digest(
                "seal-fp:" + algorithm.algorithm_id
            ),
            "integrity_pass": True,
        }
    return specs, verified, source_bindings


def _alignment(stage21a, specs, verified) -> dict:
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_cross_method_alignment",
        "method_count": 6,
        "pair_count_per_method": EXPECTED_PAIRS_PER_METHOD,
        "release_counts_per_method": {
            release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES
        },
        "future_sd300b_pair_count": EXPECTED_PAIRS_PER_RELEASE,
        "pair_manifest_hash": stage21a.pair_manifest_hash,
        "pair_ids_sha256": stage21a.pair_ids_sha256,
        "ordered_pair_input_identity_sha256": digest("ordered-identity"),
        "preparation_set_id": PREPARATION_SET_ID,
        "preparation_set_fingerprint": digest("prep-set"),
        "preparation_profile_id": PREPARATION_PROFILE_ID,
        "future_sd300b_pair_ids_sha256": stage21a.future_challenger_binding[
            "impostor"
        ]["pair_ids_sha256"],
        "methods": [
            {
                "algorithm_id": algorithm_id,
                "run_id": specs[algorithm_id].run_id,
                "result_set_id": specs[algorithm_id].result_set_id,
                "result_set_fingerprint": verified[algorithm_id][
                    "result_set_fingerprint"
                ],
            }
            for algorithm_id in sorted(specs)
        ],
        "gates": {
            "all_pair_manifest_hashes_identical": True,
            "all_pair_sets_and_order_identical": True,
            "all_left_right_image_identities_identical": True,
            "all_preparation_entry_identities_identical": True,
            "no_method_specific_filtering": True,
        },
        "raw_score_column_loaded": False,
        "common_score_population_computed": False,
        "alignment_pass": True,
    }


def _legacy(stage21a) -> dict:
    return {
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
    }


_ATTESTATION = {
    "schema_version": "1",
    "stage": "21B",
    "kind": "stage_21b_contract_test_attestation",
    "command": ["python", "-m", "pytest", "tests/stage21b", "-q"],
    "synthetic_only": True,
    "sd300_matcher_attempts": 0,
    "vendor_sdk_required": False,
    "contract_tests_pass": True,
    "regression_tests_pass": True,
    "completed_utc": "2026-09-01T00:00:00+00:00",
}


def _publish(directory: Path, monkeypatch: pytest.MonkeyPatch):
    stage21a = load_stage21a_binding(ROOT)
    policy = load_execution_policy(ROOT / EXECUTION_POLICY_PATH)
    policy.require_roster_adapters(stage21a.adapter_ids)
    specs, verified, source_bindings = _material(stage21a, policy)
    workspace = directory.parent / "workspace"
    run_dirs = {
        algorithm_id: workspace / "stage21b" / algorithm_id / spec.run_id
        for algorithm_id, spec in specs.items()
    }
    directory_by_algorithm = {
        path.resolve(): algorithm_id for algorithm_id, path in run_dirs.items()
    }
    for algorithm_id, run_dir in run_dirs.items():
        publish_evidence_document(
            run_dir / "execution-source-binding.json",
            source_bindings[algorithm_id],
        )
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "evidence/stage21b-cross-subject-baseline-expansion/README.md",
        directory / "README.md",
    )
    # Patch only the raw-store/read boundaries.  The public publisher still
    # owns discovery, binding checks, receipt construction, pre-marker
    # validation, marker publication, and its final offline verification.
    with monkeypatch.context() as patched:
        patched.setattr(
            stage21b_evidence,
            "load_stage21a_binding",
            lambda _root, **_kwargs: stage21a,
        )
        patched.setattr(
            stage21b_evidence,
            "discover_authoritative_run_directories",
            lambda _workspace, _algorithm_ids: run_dirs,
        )
        patched.setattr(
            stage21b_evidence,
            "load_frozen_pairs",
            lambda **_kwargs: SimpleNamespace(pairs=()),
        )
        patched.setattr(
            stage21b_evidence,
            "verify_legacy_manifest_unchanged",
            lambda **_kwargs: _legacy(stage21a),
        )
        patched.setattr(
            stage21b_evidence,
            "run_contract_suite",
            lambda _root: dict(_ATTESTATION),
        )

        def verified_run(run_dir: Path, **_kwargs):
            algorithm_id = directory_by_algorithm[Path(run_dir).resolve()]
            return {
                **verified[algorithm_id],
                "spec": specs[algorithm_id],
                "seal": {"sealed": True},
            }

        patched.setattr(
            stage21b_evidence, "verify_sealed_run_directory", verified_run
        )
        patched.setattr(
            stage21b_evidence,
            "audit_cross_method_alignment",
            lambda *_args, **_kwargs: _alignment(stage21a, specs, verified),
        )
        marker = publish_stage21b_evidence(
            repository_root=ROOT,
            workspace=workspace,
            evidence_directory=directory,
        )
    return stage21a, specs, verified, marker


def test_the_published_receipts_verify_offline_and_carry_no_score(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "evidence"
    stage21a, _specs, _verified, marker = _publish(directory, monkeypatch)

    read_back = verify_stage21b_evidence(ROOT, evidence_directory=directory)
    assert read_back == marker
    assert read_back["outcome"] == OUTCOME
    assert read_back["roster_size"] == 6
    assert read_back["planned_pairs_per_method"] == EXPECTED_PAIRS_PER_METHOD
    assert read_back["planned_total_attempts"] == EXPECTED_TOTAL_ATTEMPTS
    assert read_back["cross_subject_manifest_hash"] == stage21a.pair_manifest_hash
    assert read_back["legacy_pair_manifest_hash"] == LEGACY_PAIR_MANIFEST_HASH
    assert all(read_back["conditions"].values())
    assert read_back["failed_conditions"] == []

    published = sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    )
    assert published == sorted(
        [
            "README.md",
            STAGE21B_MARKER,
            "contract-test-attestation.json",
            "cross-method-alignment.json",
            "execution-policy.json",
            "execution-roster.json",
            "future-challenger-binding.json",
            "no-evaluation-audit.json",
            "pair-manifest-binding.json",
            "prepared-input-binding.json",
            "result-integrity.json",
            "runtime-bindings.json",
            "stage21a-binding.json",
            *(
                "method-runs/" + algorithm_id + ".json"
                for algorithm_id in stage21a.algorithm_ids
            ),
        ]
    )
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(directory.rglob("*.json"))
    )
    # ``raw_score_column_loaded: false`` is an attestation, not a score, so the
    # check is for a stored value rather than for the bare substring.
    for forbidden in (
        '"raw_score":',
        '"raw_score_hex":',
        '"score_values"',
        '"percentile',
        '"histogram',
        '"mean_score"',
        '"median_score"',
        '"min_score"',
        '"max_score"',
    ):
        assert forbidden not in rendered


def test_the_published_receipts_keep_failures_without_inventing_scores(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "evidence"
    stage21a, _specs, _verified, _marker = _publish(directory, monkeypatch)
    receipts = {
        algorithm_id: json.loads(
            (directory / ("method-runs/" + algorithm_id + ".json")).read_text(
                encoding="utf-8"
            )
        )
        for algorithm_id in stage21a.algorithm_ids
    }
    for receipt in receipts.values():
        assert (
            receipt["score_bearing_outcomes"] + receipt["algorithm_failures"]
            == EXPECTED_PAIRS_PER_METHOD
        )
        assert receipt["terminal_outcomes"] == EXPECTED_PAIRS_PER_METHOD
        assert receipt["infrastructure_gaps"] == 0
    with_failures = [
        algorithm_id
        for algorithm_id, receipt in receipts.items()
        if receipt["algorithm_failures"]
    ]
    assert len(with_failures) == 1
    assert receipts[with_failures[0]]["algorithm_failures"] == 81

    future = json.loads(
        (directory / "future-challenger-binding.json").read_text(encoding="utf-8")
    )
    assert future["release"] == FUTURE_TEST_RELEASE
    assert future["pair_count"] == EXPECTED_PAIRS_PER_RELEASE
    assert future["planned_evaluation_comparisons"] == 25_000
    assert future["genuine_pair_count"] == 500
    assert future["impostor_pair_count"] == EXPECTED_PAIRS_PER_RELEASE
    assert future["genuine"] == stage21a.future_challenger_binding["genuine"]
    assert future["impostor"] == stage21a.future_challenger_binding["impostor"]
    assert future["derived_from_existing_frozen_manifests"] is True
    assert future["new_biometric_manifest_created"] is False
    assert future["future_method_development_started"] is False


def test_a_tampered_receipt_is_refused_by_the_offline_verifier(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "evidence"
    stage21a, _specs, _verified, _marker = _publish(directory, monkeypatch)
    verify_stage21b_evidence(ROOT, evidence_directory=directory)

    target = directory / ("method-runs/" + stage21a.algorithm_ids[0] + ".json")
    receipt = json.loads(target.read_text(encoding="utf-8"))
    receipt["algorithm_failures"] = 0
    receipt["score_bearing_outcomes"] = EXPECTED_PAIRS_PER_METHOD
    target.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    with pytest.raises(Stage21BIntegrityError, match="evidence changed"):
        verify_stage21b_evidence(ROOT, evidence_directory=directory)


def test_an_unbound_extra_file_in_the_evidence_tree_is_refused(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "evidence"
    _publish(directory, monkeypatch)
    (directory / "notes.json").write_text('{"note": "stray"}', encoding="utf-8")
    with pytest.raises(Stage21BIntegrityError, match="unbound file"):
        verify_stage21b_evidence(ROOT, evidence_directory=directory)


def test_there_is_no_document_only_finalization_writer() -> None:
    assert not hasattr(stage21b_evidence, "publish_stage21b_documents")
