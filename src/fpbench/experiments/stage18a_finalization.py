"""Stage 18A's evidence, and the one rule that decides whether a marker exists.

Four documents and a marker, and between them they carry **no score**. Section 18
is explicit that the repository holds bindings and the private root holds numbers,
and the split is enforced here rather than remembered: :func:`build_private_run_binding`
reads the run receipt, and the receipt has no score field to copy.

.. code-block:: text

    evidence/stage18a-secugen-openafis-reference/
        README.md                  what ran, what it means, and what it does not
        openafis-identity.json     the pinned commit and the files that fix the contract
        route-contract.json        the frozen extraction route and its recorded deviations
        private-run-binding.json   identifiers, counts and timings — never a score
        stage-18a-finalization.json

The marker is written when, and only when, the run stored 6,000 outcomes for 6,000
expected pairs with none missing. That is the whole completion criterion (section
12): coverage, score counts, variance and discrimination are all explicitly *not*
conditions, and there is no constant here for any of them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.serialization import read_json
from fpbench.experiments import stage18a_identity as frozen
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

__all__ = [
    "Stage18AFinalizationError",
    "build_openafis_identity",
    "build_route_contract",
    "build_private_run_binding",
    "build_stage18a_finalization",
    "write_stage18a_documents",
    "main",
]


class Stage18AFinalizationError(RuntimeError):
    """The evidence does not support the document being asked for."""


_SOURCE_FILES = (
    "src/fpbench/experiments/stage18a_identity.py",
    "src/fpbench/experiments/stage18a_inputs.py",
    "src/fpbench/experiments/stage18a_reference_run.py",
    "src/fpbench/experiments/stage18a_diagnostics.py",
    "src/fpbench/experiments/stage18a_finalization.py",
    "integrations/secugen/extract_batch.py",
    "integrations/openafis/src/fpbench_openafis_bridge.cpp",
    "integrations/openafis/src/fpbench_openafis_csv_instantiation.cpp",
    "integrations/openafis/Makefile",
)

_PREDECESSORS = {
    "17A": ("evidence/stage17a-fingerprintmatcher/stage-17a-finalization.json", "stage_17a_finalization_fingerprint"),
    "15A": ("evidence/stage15a-fingerprints-matching/stage-15a-finalization.json", "stage_15a_finalization_fingerprint"),
    "8E": ("evidence/stage8e-research-only-policy/stage-8e-finalization.json", "stage_8e_finalization_fingerprint"),
}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stage18a_source_fingerprint(repository_root: Path = REPOSITORY_ROOT) -> str:
    """The code that produced the run, hashed file by file."""
    root = Path(repository_root)
    digests: dict[str, str] = {}
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage18AFinalizationError(f"a Stage 18A source file is missing: {relative}")
        digests[relative] = _file_sha256(path)
    return _stable_hash({"schema": "stage_18a_source_v1", "files": digests})


def _predecessor_markers(repository_root: Path) -> list[dict[str, Any]]:
    """Read each predecessor's fingerprint out of its published document.

    Never written down as a literal here. Three of these have moved during the
    project — twice because history was rewritten and once because a predecessor
    was rebound — and a stale hash is worse than no hash.
    """
    bound = []
    for entry in frozen.BOUND_MARKERS:
        stage = entry["stage"]
        relative, field = _PREDECESSORS[stage]
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage18AFinalizationError(f"predecessor marker for Stage {stage} is missing: {relative}")
        document = read_json(path)
        if field not in document:
            raise Stage18AFinalizationError(f"predecessor marker for Stage {stage} has no {field}")
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


def build_openafis_identity() -> dict[str, Any]:
    """The matcher, pinned. One commit, one licence, and the files that fix the score."""
    return {
        "kind": "stage_18a_openafis_identity",
        "stage": frozen.STAGE,
        "repository": frozen.OPENAFIS_REPOSITORY,
        "commit": frozen.OPENAFIS_COMMIT,
        "tree": frozen.OPENAFIS_TREE,
        "license": frozen.OPENAFIS_LICENSE,
        "license_sha256": frozen.OPENAFIS_LICENSE_SHA256,
        "contract_files": dict(sorted(frozen.OPENAFIS_CONTRACT_FILES.items())),
        "score_contract": {
            "native_type": frozen.SCORE_NATIVE_TYPE,
            "direction": frozen.SCORE_DIRECTION,
            "transform": frozen.SCORE_TRANSFORM,
            "threshold": frozen.SCORE_THRESHOLD,
            "formula": frozen.SCORE_FORMULA,
            "formula_source": "lib/Match.cpp, read from the pinned tree and not from the README",
            "assigned_only_when": "maxMatched > Param::MinimumMinutiae (4)",
            "zero_is_a_valid_score": frozen.ZERO_IS_A_VALID_SCORE,
            "observed_maximum_exceeds_100": True,
            "why_maximum_exceeds_100": (
                "the formula is an unclamped integer ratio, so a comparison whose matched "
                "structure exceeds the product of the two minutiae counts can land above 100. "
                "Observed in this run. Left exactly as upstream computes it"
            ),
        },
        "template_formats": {
            "primary": "ISO/IEC 19794-2:2005",
            "fallback": "CSV (upstream calls it debug-only and instantiates it for no id type)",
            "csv_layout": list(frozen.CSV_LAYOUT),
        },
        "load_limits": {
            "minimum_minutiae": 2,
            "maximum_minutiae": 128,
            "why_it_matters": "a template outside these bounds fails to load and is a documented per-pair status, not a score",
        },
        "build": {
            "compiler": "g++ 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1)",
            "flags": "-std=c++17 -O3 -march=native -mtune=native -fstrict-aliasing",
            "deviations_from_upstream_cmake": [
                {
                    "dropped": "-Werror",
                    "why": "upstream pairs it with -Wall -Wextra -Wshadow -pedantic-errors and a 2021 tree does not compile clean under gcc 13; the stage is execution-first",
                },
                {
                    "dropped": "-fno-exceptions",
                    "why": "delaunator-cpp throws on degenerate minutiae; with exceptions off one bad template aborts the process and takes the rest of the run with it",
                },
            ],
            "nothing_that_could_move_a_score_was_changed": True,
        },
    }


def build_route_contract(identity_probe: Mapping[str, Any]) -> dict[str, Any]:
    """The extraction route, and every place the machine forced a deviation."""
    return {
        "kind": "stage_18a_route_contract",
        "stage": frozen.STAGE,
        "purpose": frozen.PURPOSE,
        "transcribed_from": "neilharan/openafis data/extract.py at the pinned commit",
        "route": list(frozen.EXTRACTION_ROUTE),
        "resize": {
            "width": frozen.SENSOR_WIDTH,
            "height": frozen.SENSOR_HEIGHT,
            "resample": frozen.RESAMPLING_FILTER,
            "aspect_ratio_preserved": frozen.ASPECT_RATIO_PRESERVED,
            "why_not_corrected": (
                "Stage 18A is a reference for the route the OpenAFIS author published, not for "
                "the SecuGen pipeline fpbench would have designed. The distortion is upstream's "
                "and is kept"
            ),
        },
        "impression_type": {
            "value": frozen.SECUGEN_FINGER_INFO["ImpressionType"],
            "applies_to_rolled_prints_too": True,
            "why_not_corrected": "same reason: it is upstream's declaration, not ours",
        },
        "frozen_against_change": list(frozen.FROZEN_AGAINST_CHANGE),
        "permitted_compatibility_fixes": list(frozen.PERMITTED_COMPATIBILITY_FIXES),
        "recorded_deviations": [
            {
                "deviation": "SGFPM_Init(SG_DEV_FDU05) returns 6 (SGFDX_ERROR_DLLLOAD_FAILED_DRV) and extraction proceeds anyway",
                "why": (
                    "the per-device driver module sgfdu05x64.dll ships with SecuGen's device "
                    "driver package rather than with the SDK, and no SecuGen reader is attached "
                    "to this machine. The library extracts on its built-in 300x400 @ 500 dpi "
                    "geometry, which is the FDU05 geometry upstream selected by name"
                ),
                "how_it_is_verified": (
                    "every template is parsed back and its declared width, height and resolution "
                    "checked against 300x400 @ 197 ppcm before it is written; a template "
                    "describing any other geometry is recorded as a failure and never stored"
                ),
                "corroboration": (
                    "extracting upstream's own FVC image fvc2002/DB1_B/101_1.tif through this route "
                    "reproduces the template upstream ships beside it to 179 of 180 bytes, with an "
                    "identical header (300x400, 197 ppcm, 25 minutiae) and a single angle byte "
                    "differing by one — consistent with a Pillow LANCZOS revision difference "
                    "between 2020 and 12.3.0"
                ),
            },
            {
                "deviation": "SGFPM_InitEx and SGFPM_InitEx2 were probed and not used",
                "why": (
                    "in FDx SDK Pro v4.21 SGFPM_InitEx answers 8 (SGFDX_ERROR_NO_LONGER_SUPPORTED) "
                    "and its successor SGFPM_InitEx2 answers 501 (SGFDX_ERROR_LICENSE_LOAD) without "
                    "a SecuGen-issued licence file. No licence check was circumvented; the route "
                    "used is the device-name one upstream wrote"
                ),
            },
            {
                "deviation": "the SDK directory is made the working directory before the first call",
                "why": (
                    "sgfplib loads its companions with a plain LoadLibrary by name, which searches "
                    "the working directory. Upstream's own instruction is 'copy the DLLs into the "
                    "current directory'; this reaches the same arrangement without copying vendor "
                    "binaries around"
                ),
            },
            {
                "deviation": "one process extracts many images instead of one process per image",
                "why": "upstream's extract.bat spawns an interpreter per image; the SDK handle is still created, initialised and terminated once per image, so nothing is carried between them",
            },
        ],
        "extractor_runtime": dict(identity_probe),
        "determinism": {
            "probe": "each image extracted twice and the two templates compared byte for byte",
            "result": "identical",
            "consequence": "one template per image, per section 10; no separate LEFT and RIGHT caches",
        },
        "pair_orientation": dict(frozen.PAIR_ORIENTATION),
        "template_fallback_order": list(frozen.TEMPLATE_FALLBACK_ORDER),
        "fallback_used": "A",
        "forbidden_csv_steps": list(frozen.FORBIDDEN_CSV_STEPS),
    }


def build_private_run_binding(receipt: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    """Point at the private run without importing any of its numbers.

    Counts, coverage and timings describe *the run*; scores describe *the
    fingerprints*. Only the first kind crosses into the repository.
    """
    matching = receipt.get("matching", {})
    extraction = receipt.get("extraction", {})
    return {
        "kind": "stage_18a_private_run_binding",
        "stage": frozen.STAGE,
        "purpose": frozen.PURPOSE,
        "publication_eligible": frozen.PUBLICATION_ELIGIBLE,
        "algorithm_5_established": frozen.ALGORITHM_5_ESTABLISHED,
        "opens_common_calibration": frozen.OPENS_COMMON_CALIBRATION,
        "experiment_id": frozen.EXPERIMENT_ID,
        "created_utc": receipt.get("created_utc"),
        "inputs": receipt.get("inputs", {}),
        "private_root_env_var": frozen.PRIVATE_ROOT_ENV_VAR,
        "private_subdirectories": list(frozen.PRIVATE_SUBDIRECTORIES),
        "scores_are_not_published_here": True,
        # Section 2 of the requirements: the one boundary that is not methodological.
        # It is recorded rather than resolved, because it was not resolved.
        "extractor_usage_authorization": {
            "vendor_terms_reviewed": "SecuGen SDK License Agreement, secugen.com/sdk-license-agreement, read 2026-08-17",
            "clause_3a": "prohibits using the SDK to process fingerprint images obtained from devices other than SecuGen devices",
            "clause_3e": "prohibits competitive benchmarking",
            "sd300_capture_devices_are_secugen": False,
            "research_or_evaluation_exemption_found": False,
            "eula_shipped_with_the_package": False,
            "authorization_obtained_from_vendor": False,
            "status": "OWNER_RISK_ACCEPTED",
            "accepted_by": "the repository owner, explicitly and on the record, 2026-08-17",
            "why_it_was_accepted": (
                "the run is a private reference that will not be published, and waiting for a "
                "vendor response was judged incompatible with the project's schedule"
            ),
            "consequence": (
                "this is the primary reason publication_eligible is false. These numbers must not "
                "appear in the supervisor comparison table or in any published result; Stage 19A "
                "(MINDTCT + OpenAFIS) carries no vendor terms and is the publishable route"
            ),
            "no_licence_or_protection_measure_was_circumvented": True,
        },
        "extraction": {
            "images_attempted": extraction.get("images_attempted"),
            "templates_produced": extraction.get("templates_produced"),
            "extraction_failures": extraction.get("extraction_failures"),
            "coverage": diagnostics.get("extraction_coverage", {}).get("coverage"),
            "wall_seconds": extraction.get("wall_seconds"),
        },
        "matching": {
            "expected_pair_outcomes": matching.get("expected_pair_outcomes"),
            "stored_pair_outcomes": matching.get("stored_pair_outcomes"),
            "missing": matching.get("missing"),
            "status_counts": matching.get("status_counts", {}),
            "wall_seconds": matching.get("wall_seconds"),
        },
        "timings_ms": {
            "extraction": diagnostics.get("extraction_timing_ms", {}),
            "match": diagnostics.get("match_timing_ms", {}),
        },
        "orientation_probe": diagnostics.get("orientation_probe"),
        "diagnostics_permitted": list(frozen.DIAGNOSTICS_PERMITTED),
        "diagnostics_forbidden": list(frozen.DIAGNOSTICS_FORBIDDEN),
        "forbidden_stage19_uses": list(frozen.FORBIDDEN_STAGE19_USES),
    }


# ---------------------------------------------------------------------- marker


def build_stage18a_finalization(
    *,
    repository_root: Path,
    binding_document: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble the marker, and refuse one the run does not support."""
    matching = binding_document.get("matching", {})
    expected = matching.get("expected_pair_outcomes")
    stored = matching.get("stored_pair_outcomes")
    missing = matching.get("missing")

    complete = expected == frozen.EXPECTED_PAIR_OUTCOMES and stored == expected and missing == 0
    if not complete:
        raise Stage18AFinalizationError(
            f"Stage 18A completes only on {frozen.EXPECTED_PAIR_OUTCOMES} stored outcomes with none "
            f"missing; this run stored {stored} of {expected} with {missing} missing"
        )

    marker: dict[str, Any] = {
        "kind": "stage_18a_finalization",
        "schema_version": "1",
        "stage": frozen.STAGE,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": frozen.OUTCOME_COMPLETE,
        "purpose": frozen.PURPOSE,
        # Published as constants, so no run can promote itself by succeeding.
        "algorithm_5_established": frozen.ALGORITHM_5_ESTABLISHED,
        "opens_common_calibration": frozen.OPENS_COMMON_CALIBRATION,
        "publication_eligible": frozen.PUBLICATION_ELIGIBLE,
        "algorithm_slot": "algorithm_5",
        "algorithm_ranking_published": False,
        "calibration_performed": False,
        "decision_profile_produced": False,
        "metrics_produced": False,
        "threshold_applied": False,
        "score_statistics_published": False,
        "production_adapter_built": False,
        "registry_integration": False,
        "experiment_id": frozen.EXPERIMENT_ID,
        "expected_pair_outcomes": expected,
        "stored_pair_outcomes": stored,
        "missing": missing,
        "completion_criterion": "stored == expected == 6000 and missing == 0; nothing else",
        "minimum_coverage_criterion": None,
        "minimum_score_count_criterion": None,
        "failures_recorded_as_zero": False,
        "zero_is_a_valid_raw_score": frozen.ZERO_IS_A_VALID_SCORE,
        "fpbench_score_transformation": frozen.SCORE_TRANSFORM,
        "pair_orientation_fixed": True,
        "openafis_repository": frozen.OPENAFIS_REPOSITORY,
        "openafis_commit": frozen.OPENAFIS_COMMIT,
        "openafis_license": frozen.OPENAFIS_LICENSE,
        "reference_preparation_set_id": frozen.REFERENCE_PREPARATION_SET_ID,
        "reference_pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "canonical_input_pixels_identical_to_other_algorithms": False,
        "why_input_pixels_differ": (
            "the frozen route resizes every image to 300x400 without preserving the aspect ratio, "
            "because that is the sensor geometry upstream's helper declares. SourceAFIS, NBIS, flx "
            "and VeriFinger all consumed the canonical 500 ppi images at their native dimensions. "
            "The pair manifest, its ordering, the probe side, the raw-integer storage and the "
            "failure/score split are identical; the pixels are not"
        ),
        "absolute_paths_in_evidence": False,
        "scores_in_evidence": False,
        "vendor_binaries_in_git": False,
        "stage18a_source_fingerprint": stage18a_source_fingerprint(repository_root),
        "evidence_content_hashes": dict(sorted(evidence_hashes.items())),
        "bound_markers": _predecessor_markers(repository_root),
        "forbidden_stage19_uses": list(frozen.FORBIDDEN_STAGE19_USES),
        "not_requirements": list(frozen.NOT_REQUIREMENTS),
    }
    marker["stage_18a_finalization_fingerprint"] = _stable_hash(marker)
    return marker


# ------------------------------------------------------------------- publishing


def write_stage18a_documents(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    receipt: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    identity_probe: Mapping[str, Any],
    readme: str,
) -> dict[str, Path]:
    """Write the four documents and the marker, in that order."""
    directory = Path(repository_root) / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    def _write(name: str, payload: Any) -> None:
        path = directory / name
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path.write_bytes(text.encode("utf-8"))
        written[name] = path

    _write("openafis-identity.json", build_openafis_identity())
    _write("route-contract.json", build_route_contract(identity_probe))
    binding = build_private_run_binding(receipt, diagnostics)
    _write("private-run-binding.json", binding)

    readme_path = directory / "README.md"
    readme_path.write_bytes(readme.encode("utf-8"))
    written["README.md"] = readme_path

    hashes = {name: _file_sha256(path) for name, path in written.items()}
    marker = build_stage18a_finalization(
        repository_root=repository_root, binding_document=binding, evidence_hashes=hashes
    )
    marker_path = directory / frozen.STAGE_18A_FINALIZATION_NAME
    marker_path.write_bytes((json.dumps(marker, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    written[frozen.STAGE_18A_FINALIZATION_NAME] = marker_path
    return written


def main(argv: list[str] | None = None) -> int:
    import argparse

    from fpbench.experiments.stage18a_reference_run import load_stage18a_config

    parser = argparse.ArgumentParser(description="Stage 18A evidence publisher")
    parser.add_argument("command", choices=("documents", "verify"))
    args = parser.parse_args(argv)

    config = load_stage18a_config()
    receipt = read_json(config.stage_root / "run-receipt.json")
    diagnostics = read_json(config.stage_root / "diagnostic-report.json")
    probe = read_json(config.stage_root / "extractor-identity.json")

    if args.command == "verify":
        binding = build_private_run_binding(receipt, diagnostics)
        marker = build_stage18a_finalization(
            repository_root=REPOSITORY_ROOT, binding_document=binding, evidence_hashes={}
        )
        print(json.dumps({"outcome": marker["outcome"], "complete": True}, indent=2))
        return 0

    readme_path = Path(REPOSITORY_ROOT) / frozen.EVIDENCE_DIRECTORY / "README.md"
    if not readme_path.is_file():
        raise Stage18AFinalizationError(f"write the README first: {readme_path}")
    written = write_stage18a_documents(
        receipt=receipt, diagnostics=diagnostics, identity_probe=probe, readme=readme_path.read_text(encoding="utf-8")
    )
    for name, path in sorted(written.items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
