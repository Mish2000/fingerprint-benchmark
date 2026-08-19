"""Stage 20B's evidence, and the decisions the code is and is not allowed to make.

Section 25 lists what makes the raw run complete, and every one of its conditions
is machine-checkable:

.. code-block:: text

    1. Gate A PASS
    2. Gate B PASS
    3. 6000/6000 outcomes stored, none missing
    4. the route unchanged
    5. no systemic bridge defect
    6. no systemic translation defect
    7. no parameter selection, no calibration, no threshold selection

Section 26 froze the *reason* for preferring MCC before the run: the official
unmodified matcher route, not the prettier distribution. Section 33 says when the
code may act on it — all 6,000 score-bearing and no systemic defect — and when it
must stop and wait for a person instead. That is the one verdict this module
refuses to reach on its own, and
:data:`fpbench.experiments.stage20b_identity.FAILURE_REVIEW` is where a human
writes it down.

There is deliberately no failure-rate threshold anywhere here. A 90% or 95% rule
would be a number nobody chose in advance, applied to a run whose outcome it
decided.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.adapters.mcc import adapter as production
from fpbench.adapters.mcc import identity as route
from fpbench.core.serialization import read_json
from fpbench.experiments import stage20b_identity as frozen
from fpbench.experiments.stage20b_gates import GATE_A_PASS, GATE_B_PASS
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

__all__ = [
    "Stage20BFinalizationError",
    "SOURCE_FILES",
    "build_algorithm_identity",
    "build_runtime_binding",
    "build_canonical_run_binding",
    "build_result_integrity",
    "build_stage20b_finalization",
    "write_stage20b_documents",
    "stage20b_source_fingerprint",
    "main",
]


class Stage20BFinalizationError(RuntimeError):
    """The evidence does not support the document being asked for."""


#: Every file that decides what a Stage 20B score is. The marker carries their
#: combined digest, so a later edit to any of them is visible as a stage whose
#: source no longer matches its published evidence.
SOURCE_FILES: tuple[str, ...] = (
    "integrations/mcc-sdk-v2-bridge/Program.cs",
    "integrations/mcc-sdk-v2-bridge/README.md",
    "src/fpbench/adapters/mcc/__init__.py",
    "src/fpbench/adapters/mcc/adapter.py",
    "src/fpbench/adapters/mcc/config.py",
    "src/fpbench/adapters/mcc/failure_mapping.py",
    "src/fpbench/adapters/mcc/identity.py",
    "src/fpbench/adapters/mcc/interop.py",
    "src/fpbench/adapters/mcc/translation.py",
    "src/fpbench/experiments/stage20b_diagnostics.py",
    "src/fpbench/experiments/stage20b_finalization.py",
    "src/fpbench/experiments/stage20b_gates.py",
    "src/fpbench/experiments/stage20b_identity.py",
    "src/fpbench/experiments/stage20b_mcc_runtime.py",
    "src/fpbench/experiments/stage20b_run_support.py",
    "scripts/stage20b_canonical_run.py",
    "scripts/stage20b_gate_a.py",
    "scripts/stage20b_gate_b.py",
    "tests/test_stage20b_contract.py",
    "tests/test_stage20b_evidence.py",
)

_PREDECESSORS = {
    "20A": (
        "evidence/stage20a-mcc-sdk-preflight/stage-20a-finalization.json",
        "stage_20a_finalization_fingerprint",
    ),
    "19B": (
        "evidence/stage19b-openafis-capacity-extended/stage-19b-finalization.json",
        "stage_19b_finalization_fingerprint",
    ),
    "8E": (
        "evidence/stage8e-research-only-policy/stage-8e-finalization.json",
        "stage_8e_finalization_fingerprint",
    ),
}
_PREDECESSOR_WHY = {
    "20A": (
        "the stage that qualified this SDK, closed the route and fixed the score "
        "contract; its runtime smoke is what Gate A reproduces"
    ),
    "19B": (
        "the incumbent fifth method, which this route may displace for a reason "
        "frozen before either run's scores were read"
    ),
    "8E": (
        "the third-party research-use policy, under which a licence-restricted "
        "vendor artifact is used without being redistributed"
    ),
}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stage20b_source_fingerprint(repository_root: Path = REPOSITORY_ROOT) -> str:
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage20BFinalizationError(
                f"a Stage 20B source file is missing: {relative}"
            )
        digests[relative] = _file_sha256(path)
    return _stable_hash({"schema": "stage_20b_source_v1", "files": digests})


def _predecessor_markers(repository_root: Path) -> list[dict[str, Any]]:
    bound = []
    for stage, (relative, field) in _PREDECESSORS.items():
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage20BFinalizationError(
                f"predecessor marker for Stage {stage} is missing"
            )
        document = read_json(path)
        bound.append(
            {
                "stage": stage,
                "outcome": document.get("outcome"),
                "finalization_fingerprint": document[field],
                "why": _PREDECESSOR_WHY[stage],
            }
        )
    return bound


# ------------------------------------------------------------------- documents


def build_algorithm_identity() -> dict[str, Any]:
    """What this algorithm is, and what it is not claiming to be."""
    return {
        "kind": "stage_20b_algorithm_identity",
        "stage": "20B",
        "algorithm_id": frozen.ALGORITHM_ID,
        "adapter_id": frozen.ADAPTER_ID,
        "display_name": frozen.DISPLAY_NAME,
        "algorithm_slot": "fifth_method_candidate",
        "extractor": route.EXTRACTOR,
        "matcher": route.MATCHER,
        "variant": route.MCC_VARIANT,
        "why_the_extractor_is_in_the_name": (
            "the official MCC SDK contains no image extractor; it accepts minutiae. "
            "Calling this algorithm 'MCC' would claim an extractor Bologna never "
            "shipped and would hide that MINDTCT produced half of every score"
        ),
        "shares_extractor_with": route.SHARES_EXTRACTOR_WITH,
        "is_an_independent_fifth_system": False,
        "upstream_modified": route.UPSTREAM_MODIFIED,
        "official_mcc_artifact": True,
        "mcc_sdk_version": route.MCC_SDK_VERSION,
        "mcc_sdk_assembly": route.MCC_SDK_ASSEMBLY_FULL_NAME,
        "mcc_sdk_dll_sha256": route.MCC_SDK_DLL_SHA256,
        "template_api": route.TEMPLATE_API,
        "match_api": route.MATCH_API,
        "parameters": "SDK_OPTIMAL_DEFAULTS",
        "parameter_setters_called": False,
        "forbidden_route_operations": list(route.FORBIDDEN_ROUTE_OPERATIONS),
        "translation": {
            "x": "x_mcc = x_xyt",
            "y": "y_mcc = image_height - y_xyt",
            "direction": "direction_mcc = theta_xyt_degrees * pi / 180",
            "resolution": route.MCC_INPUT_RESOLUTION,
            "quality": "IGNORED_BY_MCC",
            "minutia_type": "IGNORED_BY_MCC",
            "finger_position": "IGNORED_BY_MCC",
            "order": "mindtct order preserved, every minutia retained",
            "authority": "frozen by Stage 20A from the two upstreams' published conventions",
        },
        "pipeline_metadata": dict(production.PIPELINE_METADATA),
        "supervisor_disclosure": frozen.SUPERVISOR_DISCLOSURE,
    }


def build_runtime_binding(
    *,
    environment: Mapping[str, str],
    runtime: Mapping[str, str],
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """The exact tools this run was carried out with, by digest.

    ``environment`` and ``runtime`` come straight from the adapter's own
    ``EnvironmentReport``, so the binding records what the run actually loaded
    rather than what a configuration file said it should.

    The last link in the chain is closed here rather than in the adapter: the
    bridge the run executed was built from a source whose digest its manifest
    recorded, and *this* is where the repository layout is known well enough to
    check that digest against the committed ``Program.cs``. Without it, "the
    bridge matches its manifest" would stop one step short of the reviewed source.
    """
    committed = Path(repository_root) / "integrations/mcc-sdk-v2-bridge/Program.cs"
    committed_digest = _file_sha256(committed) if committed.is_file() else None
    observed_source = runtime.get("mcc.bridge_source_sha256") or None
    if committed_digest is not None and observed_source is not None:
        if committed_digest != observed_source:
            raise Stage20BFinalizationError(
                "the bridge that produced this run was built from a different "
                "Program.cs than the one committed; the published source would not "
                "describe the process that ran"
            )
    return {
        "bridge_source": "integrations/mcc-sdk-v2-bridge/Program.cs",
        "bridge_source_sha256": committed_digest,
        "bridge_built_from_committed_source": (
            committed_digest is not None and committed_digest == observed_source
        ),
        "kind": "stage_20b_runtime_binding",
        "stage": "20B",
        "algorithm_id": frozen.ALGORITHM_ID,
        "nbis_version": frozen.NBIS_VERSION,
        "nbis_build_id": frozen.NBIS_BUILD_ID,
        "same_certified_build_as_algorithm_2": True,
        "mindtct_compiled_for_this_stage": False,
        "why_not_a_windows_mindtct": (
            "'Algorithms 2 and MCC use the same extractor' has to be literally true; "
            "compiling a second MINDTCT for the host that runs the SDK would make it "
            "a claim about two similar binaries instead"
        ),
        "execution_topology": [
            "fpbench and MINDTCT on the certified linux/x86_64 target under WSL",
            "the MCC bridge as a Windows .NET Framework process reached by interop",
            "one bridge process per comparison, no persistent worker, no shared state",
        ],
        "bridge_process_model": "one_process_per_comparison",
        "template_cache": "disabled",
        "template_persistence": "disabled",
        "dependencies": dict(sorted(runtime.items())),
        "environment": dict(sorted(environment.items())),
        "vendor_bytes_in_git": False,
        "official_artifact_cannot_be_redistributed_by_this_repository": True,
    }


def build_canonical_run_binding(
    diagnostics: Mapping[str, Any], *, stored: int, missing: int
) -> dict[str, Any]:
    """What was compared, and the arithmetic of whether all of it was."""
    return {
        "kind": "stage_20b_canonical_run_binding",
        "stage": "20B",
        "algorithm_id": frozen.ALGORITHM_ID,
        "run_id": frozen.RUN_ID,
        "preparation_set_id": frozen.REFERENCE_PREPARATION_SET_ID,
        "pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "nbis_build_id": frozen.NBIS_BUILD_ID,
        "pairs_regenerated": False,
        "pair_order_changed": False,
        "dataset_changed": False,
        "expected_outcomes": frozen.EXPECTED_OUTCOMES,
        "stored_outcomes": stored,
        "missing": missing,
        "protocol_stages": {
            row["protocol_stage"]: row["attempted"]
            for row in diagnostics.get("by_protocol_stage", [])
        },
        "outcome_counts": diagnostics.get("outcome_counts", {}),
        "failure_reasons": diagnostics.get("failure_reasons", {}),
        "score_bearing": diagnostics.get("overall", {}).get("score_bearing"),
        "score_bearing_fraction": diagnostics.get("overall", {}).get(
            "score_bearing_fraction"
        ),
        "score_type": "System.Double",
        "score_range": [route.SCORE_MINIMUM, route.SCORE_MAXIMUM],
        "score_direction": "HIGHER_MORE_SIMILAR",
        "score_transform": "NONE",
        "threshold_applied": None,
        "calibration_performed": False,
        "decisions_produced": 0,
        "metrics_produced": [],
    }


def build_result_integrity(
    outcomes: Sequence[Any], diagnostics: Mapping[str, Any]
) -> dict[str, Any]:
    """The checks that make the stored file trustworthy on its own terms.

    Not statistics: these are the properties a result file must have before any
    number in it is worth reading. Every pair appears exactly once, in the
    manifest's order; no score sits outside the frozen contract; no failure was
    stored as a zero and no zero was stored as a failure.
    """
    ordinals = [outcome.ordinal for outcome in outcomes]
    pair_ids = [outcome.pair_id for outcome in outcomes]
    scored = [outcome for outcome in outcomes if outcome.score_bearing]

    out_of_range = [
        outcome.pair_id
        for outcome in scored
        if not route.SCORE_MINIMUM <= float(outcome.raw_score) <= route.SCORE_MAXIMUM
    ]
    failures_with_a_score = [
        outcome.pair_id
        for outcome in outcomes
        if outcome.status != "OK" and outcome.raw_score is not None
    ]
    successes_without_a_score = [
        outcome.pair_id
        for outcome in outcomes
        if outcome.status == "OK" and outcome.raw_score is None
    ]

    return {
        "kind": "stage_20b_result_integrity",
        "stage": "20B",
        "algorithm_id": frozen.ALGORITHM_ID,
        "stored_outcomes": len(outcomes),
        "expected_outcomes": frozen.EXPECTED_OUTCOMES,
        "missing": frozen.EXPECTED_OUTCOMES - len(outcomes),
        "duplicate_pair_ids": len(pair_ids) - len(set(pair_ids)),
        "ordinals_are_the_manifest_order": ordinals == sorted(ordinals),
        "ordinals_are_complete": (
            len(set(ordinals)) == len(outcomes)
            and (not ordinals or (min(ordinals) == 0 and max(ordinals) == len(outcomes) - 1))
        ),
        "every_attempt_stored": len(outcomes) == frozen.EXPECTED_OUTCOMES,
        "score_bearing": len(scored),
        "scores_outside_contract": len(out_of_range),
        "first_scores_outside_contract": out_of_range[:20],
        "zero_scores": sum(1 for outcome in scored if float(outcome.raw_score) == 0.0),
        "zero_is_a_valid_similarity": True,
        "failures_recorded_as_zero": len(failures_with_a_score),
        "successes_recorded_without_a_score": len(successes_without_a_score),
        "invalid_scores_clamped": False,
        "invalid_scores_observed": diagnostics.get("invalid_scores_observed", []),
        "algorithm_ids_present": sorted({frozen.ALGORITHM_ID}),
    }


# ---------------------------------------------------------------------- marker


def build_stage20b_finalization(
    *,
    repository_root: Path,
    gate_a: Mapping[str, Any],
    gate_b: Mapping[str, Any],
    binding: Mapping[str, Any],
    integrity: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble the marker and derive section 25's conditions from the evidence."""
    stored = binding["stored_outcomes"]
    missing = binding["missing"]
    score_bearing = integrity["score_bearing"]
    counts = binding.get("outcome_counts", {})

    # A systemic defect is one of *ours*: the bridge failing to carry a payload,
    # a translation this route cannot represent, or the machine. An SDK that
    # declines a template or a match is the algorithm answering, not a defect.
    bridge_defects = counts.get("BRIDGE_FAILURE", 0)
    runtime_defects = counts.get("MCC_RUNTIME_FAILURE", 0) + counts.get(
        "INFRASTRUCTURE_FAILURE", 0
    )
    translation_defects = sum(
        value
        for key, value in diagnostics.get("failure_reasons", {}).items()
        if key
        in {
            "invalid_raster_dimensions",
            "minutia_outside_mindtct_raster",
            "invalid_mindtct_direction",
            "workspace_not_visible_to_windows",
        }
    )

    conditions = {
        "gate_a_bridge_reproduction": gate_a.get("outcome") == GATE_A_PASS
        and gate_a.get("mismatches") == 0,
        "gate_b_mindtct_parity": gate_b.get("outcome") == GATE_B_PASS
        and gate_b.get("mismatches") == 0,
        "canonical_run_complete": stored == frozen.EXPECTED_OUTCOMES and missing == 0,
        "route_unchanged": (
            binding["pairs_regenerated"] is False
            and binding["pair_order_changed"] is False
            and binding["dataset_changed"] is False
        ),
        "no_systemic_bridge_defect": bridge_defects == 0 and runtime_defects == 0,
        "no_systemic_translation_defect": translation_defects == 0,
        "no_parameter_selection": True,
        "no_calibration": binding["calibration_performed"] is False,
        "no_threshold_selection": binding["threshold_applied"] is None,
    }

    if not conditions["gate_a_bridge_reproduction"]:
        outcome = frozen.OUTCOME_GATE_A_FAIL
    elif not conditions["gate_b_mindtct_parity"]:
        outcome = frozen.OUTCOME_GATE_B_FAIL
    elif not conditions["canonical_run_complete"]:
        raise Stage20BFinalizationError(
            "the canonical run completes only on "
            f"{frozen.EXPECTED_OUTCOMES} stored outcomes with none missing; this run "
            f"stored {stored} with {missing} missing"
        )
    else:
        outcome = frozen.OUTCOME_COMPLETE

    complete = outcome == frozen.OUTCOME_COMPLETE
    full_coverage = complete and score_bearing == frozen.EXPECTED_OUTCOMES
    no_systemic_defect = (
        conditions["no_systemic_bridge_defect"]
        and conditions["no_systemic_translation_defect"]
    )

    # Section 33. Full coverage with no systemic defect meets the first branch
    # outright; anything else waits for one human reading of the failures rather
    # than for a failure-rate threshold nobody chose in advance.
    if full_coverage and no_systemic_defect:
        preferred: bool | None = True
        preference_basis = "SECTION_33_FULL_COVERAGE_NO_SYSTEMIC_DEFECT"
    elif frozen.FAILURE_REVIEW is None:
        preferred = None
        preference_basis = "AWAITING_HUMAN_FAILURE_REVIEW"
    else:
        preferred = frozen.FAILURE_REVIEW == "FAILURES_UNDERSTOOD_MCC_PREFERRED"
        preference_basis = frozen.FAILURE_REVIEW

    marker: dict[str, Any] = {
        "kind": "stage_20b_finalization",
        "schema_version": "1",
        "stage": "20B",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome,
        "algorithm_id": frozen.ALGORITHM_ID,
        "adapter_id": frozen.ADAPTER_ID,
        "display_name": frozen.DISPLAY_NAME,
        "official_mcc_artifact": True,
        "upstream_modified": route.UPSTREAM_MODIFIED,
        "extractor": route.EXTRACTOR,
        "matcher": route.MATCHER,
        "shares_extractor_with": route.SHARES_EXTRACTOR_WITH,
        "is_an_independent_fifth_system": False,
        "gate_a_bridge_reproduction": "PASS"
        if conditions["gate_a_bridge_reproduction"]
        else "FAIL",
        "gate_b_mindtct_parity": "PASS"
        if conditions["gate_b_mindtct_parity"]
        else "FAIL",
        "completion_conditions": conditions,
        "expected_outcomes": frozen.EXPECTED_OUTCOMES,
        "stored_outcomes": stored,
        "score_bearing": score_bearing,
        "missing": missing,
        "mcc_full_score_coverage": full_coverage,
        "failure_count": stored - score_bearing,
        "failure_reasons": diagnostics.get("failure_reasons", {}),
        "score_type": "System.Double",
        "score_range": [route.SCORE_MINIMUM, route.SCORE_MAXIMUM],
        "score_direction": "HIGHER_MORE_SIMILAR",
        "score_transform": "NONE",
        "threshold": None,
        "calibration_performed": False,
        "decision_profile_produced": False,
        "metrics_produced": False,
        "algorithm_ranking_published": False,
        "failures_recorded_as_zero": bool(integrity["failures_recorded_as_zero"]),
        "invalid_scores_clamped": False,
        "sd300_parameter_selection": False,
        "sd300_performance_selection": False,
        "preferred_final_fifth": preferred,
        "preference_reason": frozen.PREFERENCE_REASON,
        "preference_basis": preference_basis,
        "selection_based_on_sd300_accuracy": False,
        "openafis_capacity_extended_retained_as": (
            "additional experimentally evaluated method"
            if preferred
            else "algorithm_5"
        ),
        "publication_eligible": complete,
        "third_party_bytes_added_to_git": False,
        "preparation_set_id": frozen.REFERENCE_PREPARATION_SET_ID,
        "pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "nbis_build_id": frozen.NBIS_BUILD_ID,
        "supervisor_disclosure": frozen.SUPERVISOR_DISCLOSURE,
        "stage20b_source_fingerprint": stage20b_source_fingerprint(repository_root),
        "evidence_content_hashes": dict(sorted(evidence_hashes.items())),
        "bound_markers": _predecessor_markers(repository_root),
    }
    marker["stage_20b_finalization_fingerprint"] = _stable_hash(marker)
    return marker


def write_stage20b_documents(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    gate_a: Mapping[str, Any],
    gate_b: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    outcomes: Sequence[Any],
    environment: Mapping[str, str],
    runtime: Mapping[str, str],
    readme: str,
) -> dict[str, Path]:
    directory = Path(repository_root) / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write(name: str, payload: Any) -> None:
        path = directory / name
        path.write_bytes(
            (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
        )
        written[name] = path

    stored = len(outcomes)
    missing = frozen.EXPECTED_OUTCOMES - stored

    _write("algorithm-identity.json", build_algorithm_identity())
    _write(
        "runtime-binding.json",
        build_runtime_binding(
            environment=environment, runtime=runtime, repository_root=repository_root
        ),
    )
    _write("gate-a-bridge-reproduction.json", dict(gate_a))
    _write("gate-b-mindtct-parity.json", dict(gate_b))
    binding = build_canonical_run_binding(diagnostics, stored=stored, missing=missing)
    _write("canonical-run-binding.json", binding)
    integrity = build_result_integrity(outcomes, diagnostics)
    _write("result-integrity.json", integrity)
    _write("diagnostic-report.json", dict(diagnostics))

    readme_path = directory / "README.md"
    readme_path.write_bytes(readme.encode("utf-8"))
    written["README.md"] = readme_path

    hashes = {name: _file_sha256(path) for name, path in written.items()}
    marker = build_stage20b_finalization(
        repository_root=repository_root,
        gate_a=gate_a,
        gate_b=gate_b,
        binding=binding,
        integrity=integrity,
        diagnostics=diagnostics,
        evidence_hashes=hashes,
    )
    marker_path = directory / frozen.STAGE_20B_FINALIZATION_NAME
    marker_path.write_bytes(
        (json.dumps(marker, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    written[frozen.STAGE_20B_FINALIZATION_NAME] = marker_path
    return written


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from fpbench.experiments.stage20b_diagnostics import read_outcomes

    parser = argparse.ArgumentParser(description="Stage 20B evidence publisher")
    parser.add_argument("--gate-a", type=Path, required=True)
    parser.add_argument("--gate-b", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    args = parser.parse_args(argv)

    readme_path = Path(REPOSITORY_ROOT) / frozen.EVIDENCE_DIRECTORY / "README.md"
    if not readme_path.is_file():
        raise Stage20BFinalizationError(f"write the README first: {readme_path}")

    recorded = read_json(args.environment)
    written = write_stage20b_documents(
        gate_a=read_json(args.gate_a),
        gate_b=read_json(args.gate_b),
        diagnostics=read_json(args.diagnostics),
        outcomes=read_outcomes(args.outcomes),
        environment=recorded.get("runtime", {}),
        runtime=recorded.get("dependencies", {}),
        readme=readme_path.read_text(encoding="utf-8"),
    )
    for name, path in sorted(written.items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
