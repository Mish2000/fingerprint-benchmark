"""Stage 19A's evidence, and the verdict it will not reach on its own.

Five documents and a marker. The marker separates two questions that are easy to
run together and must not be:

* **the raw run completed** — arithmetic, decided here;
* **Algorithm 5 is established** — four conditions, three decided here and the
  fourth deliberately left to a human (see
  :mod:`fpbench.experiments.stage19a_identity`).

When the fourth is ``UNDETERMINED`` the marker publishes
``algorithm_5_established: null`` and ``opens_common_calibration: false``. Null is
not a placeholder for ``false``: it says nobody has judged it yet, which is a
different claim, and Stage 10B established the same distinction for
``research_use_opens_execution``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.adapters.openafis.adapter import PIPELINE_METADATA
from fpbench.adapters.openafis.translation import (
    ANGLE_CONVERSION,
    MINUTIA_TYPE_POLICY,
    OPENAFIS_MAXIMUM_MINUTIAE,
    OPENAFIS_MINIMUM_MINUTIAE,
    PLACEHOLDER_MINUTIA_TYPE,
)
from fpbench.core.serialization import read_json
from fpbench.experiments import stage19a_identity as frozen
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT
from fpbench.experiments.stage19_result_integrity import (
    OutcomeStoreIntegrity,
    Stage19ResultIntegrityError,
    canonical_source_sha256,
    verify_outcome_store_integrity,
)

__all__ = [
    "Stage19AFinalizationError",
    "build_algorithm_identity",
    "build_translation_contract",
    "build_canonical_run_binding",
    "build_matcher_comparison",
    "build_stage19a_finalization",
    "write_stage19a_documents",
    "main",
]


class Stage19AFinalizationError(RuntimeError):
    """The evidence does not support the document being asked for."""


_SOURCE_FILES = (
    "src/fpbench/adapters/openafis/__init__.py",
    "src/fpbench/adapters/openafis/adapter.py",
    "src/fpbench/adapters/openafis/config.py",
    "src/fpbench/adapters/openafis/failure_mapping.py",
    "src/fpbench/adapters/openafis/translation.py",
    "src/fpbench/experiments/stage19a_identity.py",
    "src/fpbench/experiments/stage19a_research.py",
    "src/fpbench/experiments/stage19a_validation.py",
    "src/fpbench/experiments/stage19a_diagnostics.py",
    "src/fpbench/experiments/stage19a_finalization.py",
    "src/fpbench/experiments/stage19_result_integrity.py",
    "configs/algorithms/nbis_mindtct_openafis_v1.yaml",
)

_PREDECESSORS = {
    "18A": (
        "evidence/stage18a-secugen-openafis-reference/stage-18a-finalization.json",
        "stage_18a_finalization_fingerprint",
    ),
    "17A": (
        "evidence/stage17a-fingerprintmatcher/stage-17a-finalization.json",
        "stage_17a_finalization_fingerprint",
    ),
    "8E": (
        "evidence/stage8e-research-only-policy/stage-8e-finalization.json",
        "stage_8e_finalization_fingerprint",
    ),
}


def _file_sha256(path: Path) -> str:
    """Hash a published evidence artifact byte-for-byte."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stage19a_source_fingerprint(repository_root: Path = REPOSITORY_ROOT) -> str:
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage19AFinalizationError(f"a Stage 19A source file is missing: {relative}")
        digests[relative] = canonical_source_sha256(path)
    return _stable_hash({"schema": "stage_19a_source_v1", "files": digests})


def _predecessor_markers(repository_root: Path) -> list[dict[str, Any]]:
    bound = []
    for entry in frozen.BOUND_MARKERS:
        stage = entry["stage"]
        relative, field = _PREDECESSORS[stage]
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage19AFinalizationError(f"predecessor marker for Stage {stage} is missing: {relative}")
        document = read_json(path)
        bound.append(
            {
                "stage": stage,
                "outcome": document.get("outcome"),
                "finalization_fingerprint": document[field],
                "why": entry["why"],
            }
        )
    return bound


# ------------------------------------------------------------------- documents


def build_algorithm_identity() -> dict[str, Any]:
    return {
        "kind": "stage_19a_algorithm_identity",
        "stage": frozen.STAGE,
        "algorithm_id": frozen.ALGORITHM_ID,
        "adapter_id": frozen.ADAPTER_ID,
        "algorithm_slot": "algorithm_5",
        "extractor": {
            "id": "mindtct",
            "version": frozen.NBIS_VERSION,
            "build_id": frozen.NBIS_BUILD_ID,
            "license": "public domain (NIST)",
            "flags": "none — no -b, no -m1, no quality cutoff",
        },
        "matcher": {
            "id": "openafis",
            "commit": frozen.OPENAFIS_COMMIT,
            "license": "BSD-2-Clause",
            "template_format": "csv",
            "threshold": None,
            "score_transform": "NONE",
            "score_native_type": "uint8_t",
            "score_direction": "HIGHER_MORE_SIMILAR",
        },
        # The single most important sentence in this document.
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "differs_from_algorithm_2_only_in": "the matcher",
        "is_an_independent_fifth_system": False,
        "why_that_matters": (
            "Algorithms 2 and 5 run the same MINDTCT binary from the same certified build over "
            "the same canonical images with the same flags. The pair is a controlled matcher "
            "comparison, which is interesting in itself, and it must never be presented as two "
            "independent systems"
        ),
        "composition_is_ours": (
            "OpenAFIS's README states the library does not extract minutiae, and the extractor "
            "its author demonstrated is a SecuGen one. Pairing it with MINDTCT is fpbench's own "
            "composition; neither upstream project publishes this route"
        ),
        "pipeline_metadata": dict(sorted(PIPELINE_METADATA.items())),
    }


def build_translation_contract() -> dict[str, Any]:
    """The four rules, each with the source that settled it."""
    return {
        "kind": "stage_19a_translation_contract",
        "stage": frozen.STAGE,
        "settled_from": "upstream sources only",
        "secugen_reference_used_for_parameter_selection": False,
        "angle": {
            "rule": ANGLE_CONVERSION,
            "inversion": "none",
            "rotation": "none",
            "mindtct_authority": (
                "NBIS 5.0.0 mindtct/src/lib/mindtct/xytreps.c — XYT without -m1 is NIST internal "
                "representation: origin bottom-left, degrees 0..360, 0 pointing east, increasing "
                "counter clockwise; results.c selects NIST_INTERNAL_XYT_REP when -m1 is absent"
            ),
            "openafis_authority": (
                "lib/TripletScalar.cpp relates a minutia's angle to rotateAngle(angle, atan2(dy, dx)) "
                "over the stored coordinates, so it requires counter-clockwise from +x in the same "
                "plane as the stored y — which MINDTCT's representation already is"
            ),
            "verification": (
                "decoding an OpenAFIS ISO template the way its own ISO parser does, including its "
                "360-minus-angle step, and re-emitting it through this CSV path reproduces the ISO "
                "route's score exactly on twelve pairs"
            ),
        },
        "coordinates": {
            "rule": "carried over exactly, never scaled",
            "csv_header": "the prepared image's real width and height",
            "why": (
                "OpenAFIS's MinutiaPoint normalises by 256/width and 256/height itself, so any "
                "normalisation here would be applied twice"
            ),
        },
        "minutia_type": {
            "policy": MINUTIA_TYPE_POLICY,
            "value": PLACEHOLDER_MINUTIA_TYPE,
            "why": (
                "OpenAFIS's MinutiaPoint is built from x, y and angle only and the triplets are "
                "built from MinutiaPoint, so the type never reaches the similarity computation"
            ),
            "proved_by": "scoring the same minutiae all-RidgeEnding and all-RidgeBifurcation and requiring the identical result",
        },
        "quality": {
            "transferred": False,
            "used_to_filter": False,
            "why": "OpenAFIS has nowhere to put it, and filtering on it would be a minutiae-selection rule fpbench invented",
        },
        "ordering": {"rule": "MINDTCT order preserved", "sorting": "none", "deduplication": "none"},
        "bounds": {
            "minimum": OPENAFIS_MINIMUM_MINUTIAE,
            "maximum": OPENAFIS_MAXIMUM_MINUTIAE,
            "authority": "lib/Template.h; Template::load refuses anything outside them",
            "over_maximum_policy": "record_template_failure_never_truncate",
            "top_n_rule_refused": True,
            "why_refused": (
                "choosing which minutiae survive is a selection rule neither upstream project "
                "publishes, and the resulting score would be fpbench's rather than what MINDTCT "
                "and OpenAFIS produce between them"
            ),
            "classification": "ALGORITHMIC, not BLOCKING — a real limit of a real matcher meeting a real property of real rolled prints",
        },
    }


def _outcome_integrity(
    outcomes: Path, diagnostics: Mapping[str, Any]
) -> OutcomeStoreIntegrity:
    try:
        return verify_outcome_store_integrity(
            outcomes,
            diagnostics,
            expected_outcomes=frozen.EXPECTED_OUTCOMES,
        )
    except Stage19ResultIntegrityError as exc:
        raise Stage19AFinalizationError(str(exc)) from None


def build_canonical_run_binding(
    diagnostics: Mapping[str, Any], *, outcomes: Path
) -> dict[str, Any]:
    integrity = _outcome_integrity(outcomes, diagnostics)
    overall = diagnostics.get("overall", {})
    per_stage = {row["label"]: row for row in diagnostics.get("by_protocol_stage", [])}
    cross = {
        stage: {
            "comparisons": per_stage.get(stage, {}).get("comparisons"),
            "score_bearing": per_stage.get(stage, {}).get("score_bearing"),
            "score_bearing_fraction": per_stage.get(stage, {}).get("score_bearing_fraction"),
        }
        for stage in frozen.CROSS_IMPRESSION_STAGES
    }
    return {
        "kind": "stage_19a_canonical_run_binding",
        "stage": frozen.STAGE,
        "algorithm_id": frozen.ALGORITHM_ID,
        "experiment_id": frozen.EXPERIMENT_ID,
        "preparation_set_id": frozen.REFERENCE_PREPARATION_SET_ID,
        "pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "nbis_build_id": frozen.NBIS_BUILD_ID,
        "openafis_commit": frozen.OPENAFIS_COMMIT,
        **integrity.describe(),
        "threshold_applied": None,
        "score_transform": "NONE",
        "decisions_produced": False,
        "calibration_performed": False,
        "outcome_counts": diagnostics.get("outcome_counts", {}),
        "failure_reasons": diagnostics.get("failure_reasons", {}),
        "score_bearing": overall.get("score_bearing"),
        "score_bearing_fraction": overall.get("score_bearing_fraction"),
        "cross_impression": cross,
        "minutiae_counts": diagnostics.get("minutiae_counts", {}),
        "timings_ms": diagnostics.get("timings_ms", {}),
    }


def build_matcher_comparison(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    comparison = diagnostics.get("algorithm2_comparison")
    return {
        "kind": "stage_19a_matcher_comparison",
        "stage": frozen.STAGE,
        "what_this_is": (
            "the same MINDTCT minutiae fed to two different matchers over the same 6,000 pairs — "
            "a controlled matcher comparison"
        ),
        "what_this_is_not": (
            "a statement that either matcher is better. The two scales are unrelated, no common "
            "operating point has been chosen, and no threshold is applied anywhere"
        ),
        "comparison": dict(comparison) if comparison else None,
    }


# ---------------------------------------------------------------------- marker


def build_stage19a_finalization(
    *,
    repository_root: Path,
    binding: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
    no_systemic_defect: bool,
    failures_are_upstream_limits: bool,
) -> dict[str, Any]:
    """Assemble the marker. Refuses one the run does not support."""
    stored = binding["stored_outcomes"]
    missing = binding["missing"]
    count_fields = (
        binding.get("unique_pair_ids"),
        binding.get("unique_ordinals"),
        binding.get("diagnostic_comparisons"),
        stored,
        binding.get("expected_outcomes"),
    )
    complete = (
        all(value == frozen.EXPECTED_OUTCOMES for value in count_fields)
        and missing == 0
    )
    if not complete:
        raise Stage19AFinalizationError(
            f"the raw run completes only on {frozen.EXPECTED_OUTCOMES} stored outcomes with none "
            f"missing; this run stored {stored} with {missing} missing"
        )

    sufficiency = frozen.CROSS_IMPRESSION_SUFFICIENCY
    if sufficiency not in frozen.SUFFICIENCY_STATES:
        raise Stage19AFinalizationError(f"unknown cross-impression sufficiency {sufficiency!r}")

    # Three conditions the code may judge, one it may not.
    conditions = {
        "translation_settled_from_sources_not_tuning": True,
        "no_systemic_implementation_defect": bool(no_systemic_defect),
        "failures_are_upstream_limits_not_the_bridge": bool(failures_are_upstream_limits),
        "substantial_cross_impression_score_bearing": (
            None if sufficiency == "UNDETERMINED" else sufficiency == "SUFFICIENT"
        ),
    }
    if sufficiency == "UNDETERMINED":
        established: bool | None = None
    else:
        established = all(bool(value) for value in conditions.values())

    marker: dict[str, Any] = {
        "kind": "stage_19a_finalization",
        "schema_version": "1",
        "stage": frozen.STAGE,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": frozen.OUTCOME_COMPLETE,
        "algorithm_id": frozen.ALGORITHM_ID,
        "adapter_id": frozen.ADAPTER_ID,
        "algorithm_slot": "algorithm_5",
        "canonical_run_executed": True,
        "expected_outcomes": frozen.EXPECTED_OUTCOMES,
        "stored_outcomes": stored,
        "unique_pair_ids": binding["unique_pair_ids"],
        "unique_ordinals": binding["unique_ordinals"],
        "diagnostic_comparisons": binding["diagnostic_comparisons"],
        "missing": missing,
        "outcome_store_sha256": binding["outcome_store_sha256"],
        "score_direction": "HIGHER_MORE_SIMILAR",
        "threshold": None,
        "score_transform": "NONE",
        "secugen_reference_used_for_parameter_selection": False,
        # null, not false: nobody has judged it. See stage19a_identity.
        "algorithm_5_established": established,
        "algorithm_5_conditions": conditions,
        "cross_impression_sufficiency": sufficiency,
        "cross_impression_sufficiency_is_a_human_determination": True,
        "cross_impression": binding.get("cross_impression", {}),
        "opens_common_calibration": bool(established) if established is not None else False,
        "publication_eligible": bool(established) if established is not None else False,
        "algorithm_ranking_published": False,
        "calibration_performed": False,
        "decision_profile_produced": False,
        "metrics_produced": False,
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "is_an_independent_fifth_system": False,
        "nbis_build_id": frozen.NBIS_BUILD_ID,
        "openafis_commit": frozen.OPENAFIS_COMMIT,
        "preparation_set_id": frozen.REFERENCE_PREPARATION_SET_ID,
        "pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "score_bearing": binding.get("score_bearing"),
        "score_bearing_fraction": binding.get("score_bearing_fraction"),
        "failures_recorded_as_zero": False,
        "absolute_paths_in_evidence": False,
        "stage19a_source_fingerprint": stage19a_source_fingerprint(repository_root),
        "evidence_content_hashes": dict(sorted(evidence_hashes.items())),
        "bound_markers": _predecessor_markers(repository_root),
    }
    marker["stage_19a_finalization_fingerprint"] = _stable_hash(marker)
    return marker


def write_stage19a_documents(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    diagnostics: Mapping[str, Any],
    outcomes: Path,
    readme: str,
    no_systemic_defect: bool,
    failures_are_upstream_limits: bool,
) -> dict[str, Path]:
    directory = Path(repository_root) / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write(name: str, payload: Any) -> None:
        path = directory / name
        path.write_bytes((json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
        written[name] = path

    _write("algorithm-identity.json", build_algorithm_identity())
    _write("translation-contract.json", build_translation_contract())
    binding = build_canonical_run_binding(diagnostics, outcomes=outcomes)
    _write("canonical-run-binding.json", binding)
    _write("matcher-comparison.json", build_matcher_comparison(diagnostics))

    readme_path = directory / "README.md"
    readme_path.write_bytes(readme.encode("utf-8"))
    written["README.md"] = readme_path

    hashes = {name: _file_sha256(path) for name, path in written.items()}
    marker = build_stage19a_finalization(
        repository_root=repository_root,
        binding=binding,
        diagnostics=diagnostics,
        evidence_hashes=hashes,
        no_systemic_defect=no_systemic_defect,
        failures_are_upstream_limits=failures_are_upstream_limits,
    )
    marker_path = directory / frozen.STAGE_19A_FINALIZATION_NAME
    marker_path.write_bytes((json.dumps(marker, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    written[frozen.STAGE_19A_FINALIZATION_NAME] = marker_path
    return written


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 19A evidence publisher")
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    args = parser.parse_args(argv)

    diagnostics = read_json(args.diagnostics)
    readme_path = Path(REPOSITORY_ROOT) / frozen.EVIDENCE_DIRECTORY / "README.md"
    if not readme_path.is_file():
        raise Stage19AFinalizationError(f"write the README first: {readme_path}")

    counts = diagnostics.get("outcome_counts", {})
    blocking = sum(v for k, v in counts.items() if k in {"OPENAFIS_MATCH_FAILED", "INFRASTRUCTURE_FAILURE"})
    written = write_stage19a_documents(
        diagnostics=diagnostics,
        outcomes=args.outcomes,
        readme=readme_path.read_text(encoding="utf-8"),
        no_systemic_defect=blocking == 0,
        failures_are_upstream_limits=blocking == 0,
    )
    for name, path in sorted(written.items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
