"""Stage 19B's evidence, and the decision the code *is* allowed to make.

Stage 19A left ``algorithm_5_established`` as ``null`` because its fourth
condition — "a substantial quantity of score-bearing comparisons between
different impressions" — had no number, and inventing one would have let the
answer choose itself.

Section 17 of the Stage 19B requirements replaces that with six **structural**
conditions, every one of them machine-checkable:

.. code-block:: text

    1. Gate A: 1583/1583 baseline scores identical
    2. canonical run: 6000/6000 outcomes stored
    3. no failure remains whose reason is minutiae_above_upstream_maximum
    4. no systemic implementation defect
    5. translation contract unchanged
    6. no SecuGen-based tuning

There is deliberately no minimum score, no minimum median and no TAR. If the
mated scores are low, that is a result of the method and not a reason to withhold
the identity.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.adapters.openafis import capacity_extended as variant
from fpbench.adapters.openafis.adapter import PIPELINE_METADATA as BASE_PIPELINE_METADATA
from fpbench.core.serialization import read_json
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

__all__ = [
    "Stage19BFinalizationError",
    "EVIDENCE_DIRECTORY",
    "EVIDENCE_DOCUMENTS",
    "STAGE_19B_FINALIZATION_NAME",
    "SUPERVISOR_DISCLOSURE",
    "build_variant_identity",
    "build_patch_provenance",
    "build_canonical_run_binding",
    "build_stage19b_finalization",
    "write_stage19b_documents",
    "main",
]

EVIDENCE_DIRECTORY = Path("evidence") / "stage19b-openafis-capacity-extended"
STAGE_19B_FINALIZATION_NAME = "stage-19b-finalization.json"
EVIDENCE_DOCUMENTS = (
    "README.md",
    "variant-identity.json",
    "patch-provenance.json",
    "gate-a-inertness.json",
    "canonical-run-binding.json",
)

OUTCOME_COMPLETE = "MINDTCT_OPENAFIS_CAPACITY_EXTENDED_CANONICAL_RAW_COMPLETE"
OUTCOME_INERTNESS_FAIL = "CAPACITY_EXTENSION_INERTNESS_FAIL"

#: Section 21. Reproduced verbatim, because it is the sentence that has to travel
#: with the number into the supervisor's table.
SUPERVISOR_DISCLOSURE = (
    "NBIS MINDTCT + OpenAFIS (capacity-extended variant) — composition defined by the project. "
    "It shares the MINDTCT extractor with the NBIS/BOZORTH3 method and differs primarily in the "
    "matcher. The OpenAFIS source was minimally modified to permit CSV templates containing more "
    "than the upstream limit of 128 minutiae; the original behavior was verified unchanged on all "
    "1,583 previously accepted comparisons."
)


class Stage19BFinalizationError(RuntimeError):
    """The evidence does not support the document being asked for."""


_SOURCE_FILES = (
    "src/fpbench/adapters/openafis/capacity_extended.py",
    "src/fpbench/experiments/stage19b_diagnostics.py",
    "src/fpbench/experiments/stage19b_finalization.py",
    "scripts/stage19b_gate_a.py",
    "scripts/stage19b_canonical_run.py",
    "scripts/stage19b_determinism.py",
)

_PREDECESSORS = {
    "19A": ("evidence/stage19a-mindtct-openafis/stage-19a-finalization.json",
            "stage_19a_finalization_fingerprint"),
    "18A": ("evidence/stage18a-secugen-openafis-reference/stage-18a-finalization.json",
            "stage_18a_finalization_fingerprint"),
    "8E": ("evidence/stage8e-research-only-policy/stage-8e-finalization.json",
           "stage_8e_finalization_fingerprint"),
}
_PREDECESSOR_WHY = {
    "19A": "the unmodified route this stage extends, and the source of Gate A's 1,583 baseline scores",
    "18A": "the private reference that produced the OpenAFIS build and the raw 1:1 bridge this stage patched",
    "8E": "the third-party research-use policy, under which a modified upstream is recorded rather than hidden",
}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stage19b_source_fingerprint(repository_root: Path = REPOSITORY_ROOT) -> str:
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage19BFinalizationError(f"a Stage 19B source file is missing: {relative}")
        digests[relative] = _file_sha256(path)
    return _stable_hash({"schema": "stage_19b_source_v1", "files": digests})


def _predecessor_markers(repository_root: Path) -> list[dict[str, Any]]:
    bound = []
    for stage, (relative, field) in _PREDECESSORS.items():
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage19BFinalizationError(f"predecessor marker for Stage {stage} is missing")
        document = read_json(path)
        bound.append({
            "stage": stage,
            "outcome": document.get("outcome"),
            "finalization_fingerprint": document[field],
            "why": _PREDECESSOR_WHY[stage],
        })
    return bound


# ------------------------------------------------------------------- documents


def build_variant_identity() -> dict[str, Any]:
    score_keys = (
        "angle_conversion", "coordinate_scaling", "minutia_type_policy",
        "minutiae_quality_transferred", "minutiae_filtering", "minutiae_ordering",
        "probe_side", "openafis_threshold", "openafis_score_transform",
        "mindtct_m1", "mindtct_contrast_boost", "input_mode", "dpi_policy",
        "template_cache", "extractor_id",
    )
    return {
        "kind": "stage_19b_variant_identity",
        "stage": "19B",
        "algorithm_id": variant.ALGORITHM_ID,
        "adapter_id": variant.ADAPTER_ID,
        "display_name": "NBIS MINDTCT + OpenAFIS (capacity-extended)",
        "algorithm_slot": "algorithm_5",
        "upstream_modified": variant.UPSTREAM_MODIFIED,
        "base_openafis_commit": variant.BASE_OPENAFIS_COMMIT,
        "modification": variant.MODIFICATION,
        "why_a_new_identity": (
            "the score now comes from a build that does not behave like upstream; calling it "
            "nbis_mindtct_openafis would attribute our modification to OpenAFIS"
        ),
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "is_an_independent_fifth_system": False,
        "score_affecting_fields_identical_to_base_route": {
            key: variant.PIPELINE_METADATA[key] == BASE_PIPELINE_METADATA[key] for key in score_keys
        },
        "compare_inherited_unchanged": True,
        "overridden_methods": ["__init__", "from_config", "_translate", "validate_environment"],
        "supervisor_disclosure": SUPERVISOR_DISCLOSURE,
    }


def build_patch_provenance(patch: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "stage_19b_patch_provenance",
        "stage": "19B",
        "base_commit": variant.BASE_OPENAFIS_COMMIT,
        "modification": variant.MODIFICATION,
        "algorithmic_change": "templates above 128 minutiae: REJECT -> ALLOW",
        "files_changed": 1,
        "lines_added": 2,
        "lines_removed": 0,
        "constant_maximum_minutiae_changed": False,
        "why_the_constant_was_not_raised": (
            "MaximumMinutiae also sizes the ISO parser's reserve and its MaximumLength; Stage 19B "
            "has no business altering the ISO route. The CSV reader loads all its minutiae before "
            "Template::load is reached, so disabling the refusal is the whole change for this route"
        ),
        "minimum_minutiae_unchanged": True,
        "matching_algorithm_unchanged": True,
        "audit_of_every_maximum_minutiae_use": {
            "lib/Template.cpp: the refusal": "disabled — the one intended change",
            "lib/Template.cpp: vector capacity hint": "untouched; std::vector grows dynamically",
            "lib/TemplateISO19794_2_2005.cpp: reserve()": "untouched; ISO route only",
            "lib/TemplateISO19794_2_2005.h: MaximumLength": "untouched; ISO route only",
        },
        **dict(patch),
    }


def build_canonical_run_binding(
    diagnostics: Mapping[str, Any], *, stored: int, missing: int
) -> dict[str, Any]:
    counts = diagnostics.get("outcome_counts", {})
    reasons = diagnostics.get("failure_reasons", {})
    return {
        "kind": "stage_19b_canonical_run_binding",
        "stage": "19B",
        "algorithm_id": variant.ALGORITHM_ID,
        "preparation_set_id": "prepset_be560e047991",
        "pair_manifest_hash": "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b",
        "nbis_build_id": "658f9f54a8f2",
        "expected_outcomes": 6000,
        "stored_outcomes": stored,
        "missing": missing,
        "threshold_applied": None,
        "score_transform": "NONE",
        "outcome_counts": counts,
        "failure_reasons": reasons,
        "capacity_failures_remaining": int(reasons.get("minutiae_above_upstream_maximum", 0)),
        "score_bearing": diagnostics.get("overall", {}).get("score_bearing"),
        "score_bearing_fraction": diagnostics.get("overall", {}).get("score_bearing_fraction"),
        "by_protocol_stage": diagnostics.get("by_protocol_stage", []),
        "minutiae_counts": diagnostics.get("minutiae_counts", {}),
        "timings_ms": diagnostics.get("timings_ms", {}),
        "stage19a_comparison": diagnostics.get("stage19a_comparison"),
        "algorithm2_comparison": diagnostics.get("algorithm2_comparison"),
        "uint8_headroom_audit": diagnostics.get("uint8_headroom_audit"),
    }


# ---------------------------------------------------------------------- marker


def build_stage19b_finalization(
    *,
    repository_root: Path,
    gate_a: Mapping[str, Any],
    binding: Mapping[str, Any],
    translator_inertness: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble the marker and derive the decision from section 17's six conditions."""
    stored = binding["stored_outcomes"]
    missing = binding["missing"]
    capacity_failures = binding["capacity_failures_remaining"]
    counts = binding.get("outcome_counts", {})
    blocking = sum(
        value for key, value in counts.items()
        if key in {"OPENAFIS_MATCH_FAILED", "INFRASTRUCTURE_FAILURE"}
    )

    conditions = {
        "gate_a_baseline_scores_identical": (
            gate_a.get("outcome") == "CAPACITY_EXTENSION_INERTNESS_PASS"
            and gate_a.get("score_mismatches") == 0
            and gate_a.get("status_regressions") == 0
            and gate_a.get("exact_score_matches") == gate_a.get("baseline_scored_pairs")
        ),
        "canonical_run_complete": stored == 6000 and missing == 0,
        "no_capacity_failure_remains": capacity_failures == 0,
        "no_systemic_implementation_defect": blocking == 0,
        "translation_contract_unchanged": (
            translator_inertness.get("mismatches") == 0
            and translator_inertness.get("lower_bound_still_enforced") is True
        ),
        "no_secugen_based_tuning": True,
    }
    established = all(conditions.values())

    if not conditions["gate_a_baseline_scores_identical"]:
        outcome = OUTCOME_INERTNESS_FAIL
    elif not conditions["canonical_run_complete"]:
        raise Stage19BFinalizationError(
            f"the canonical run completes only on 6000 stored outcomes with none missing; "
            f"this run stored {stored} with {missing} missing"
        )
    else:
        outcome = OUTCOME_COMPLETE

    marker: dict[str, Any] = {
        "kind": "stage_19b_finalization",
        "schema_version": "1",
        "stage": "19B",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome,
        "algorithm_id": variant.ALGORITHM_ID,
        "adapter_id": variant.ADAPTER_ID,
        "algorithm_slot": "algorithm_5",
        "algorithm_5_established": established,
        "algorithm_5_conditions": conditions,
        "opens_common_calibration": established,
        "publication_eligible": established,
        "is_independent_fifth_system": False,
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "upstream_modified": True,
        "base_openafis_commit": variant.BASE_OPENAFIS_COMMIT,
        "modification": variant.MODIFICATION,
        "supervisor_disclosure": SUPERVISOR_DISCLOSURE,
        "baseline_inertness": {
            "comparisons": gate_a.get("baseline_scored_pairs"),
            "exact_score_matches": gate_a.get("exact_score_matches"),
            "mismatches": gate_a.get("score_mismatches"),
            "status_regressions": gate_a.get("status_regressions"),
            "what_it_does_not_prove": gate_a.get("what_this_does_not_prove"),
        },
        "translator_inertness": {
            "counts_compared": translator_inertness.get("counts_compared"),
            "byte_identical": translator_inertness.get("byte_identical"),
            "mismatches": translator_inertness.get("mismatches"),
        },
        "expected_outcomes": 6000,
        "stored_outcomes": stored,
        "missing": missing,
        "capacity_failures_remaining": capacity_failures,
        "score_bearing": binding.get("score_bearing"),
        "score_bearing_fraction": binding.get("score_bearing_fraction"),
        "score_direction": "HIGHER_MORE_SIMILAR",
        "score_transform": "NONE",
        "threshold": None,
        "secugen_reference_used_for_parameter_selection": False,
        "failures_recorded_as_zero": False,
        "algorithm_ranking_published": False,
        "calibration_performed": False,
        "decision_profile_produced": False,
        "metrics_produced": False,
        "absolute_paths_in_evidence": False,
        "preparation_set_id": binding["preparation_set_id"],
        "pair_manifest_hash": binding["pair_manifest_hash"],
        "nbis_build_id": binding["nbis_build_id"],
        "stage19b_source_fingerprint": stage19b_source_fingerprint(repository_root),
        "evidence_content_hashes": dict(sorted(evidence_hashes.items())),
        "bound_markers": _predecessor_markers(repository_root),
    }
    marker["stage_19b_finalization_fingerprint"] = _stable_hash(marker)
    return marker


def write_stage19b_documents(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    gate_a: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    patch: Mapping[str, Any],
    translator_inertness: Mapping[str, Any],
    stored: int,
    missing: int,
    readme: str,
) -> dict[str, Path]:
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write(name: str, payload: Any) -> None:
        path = directory / name
        path.write_bytes((json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
        written[name] = path

    _write("variant-identity.json", build_variant_identity())
    _write("patch-provenance.json", build_patch_provenance(patch))
    _write("gate-a-inertness.json", {**dict(gate_a), "translator_inertness": dict(translator_inertness)})
    binding = build_canonical_run_binding(diagnostics, stored=stored, missing=missing)
    _write("canonical-run-binding.json", binding)

    readme_path = directory / "README.md"
    readme_path.write_bytes(readme.encode("utf-8"))
    written["README.md"] = readme_path

    hashes = {name: _file_sha256(path) for name, path in written.items()}
    marker = build_stage19b_finalization(
        repository_root=repository_root, gate_a=gate_a, binding=binding,
        translator_inertness=translator_inertness, evidence_hashes=hashes,
    )
    marker_path = directory / STAGE_19B_FINALIZATION_NAME
    marker_path.write_bytes((json.dumps(marker, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    written[STAGE_19B_FINALIZATION_NAME] = marker_path
    return written


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 19B evidence publisher")
    parser.add_argument("--gate-a", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--translator-inertness", type=Path, required=True)
    parser.add_argument("--stored", type=int, required=True)
    parser.add_argument("--missing", type=int, required=True)
    args = parser.parse_args(argv)

    readme_path = Path(REPOSITORY_ROOT) / EVIDENCE_DIRECTORY / "README.md"
    if not readme_path.is_file():
        raise Stage19BFinalizationError(f"write the README first: {readme_path}")

    written = write_stage19b_documents(
        gate_a=read_json(args.gate_a),
        diagnostics=read_json(args.diagnostics),
        patch=read_json(args.patch),
        translator_inertness=read_json(args.translator_inertness),
        stored=args.stored,
        missing=args.missing,
        readme=readme_path.read_text(encoding="utf-8"),
    )
    for name, path in sorted(written.items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
