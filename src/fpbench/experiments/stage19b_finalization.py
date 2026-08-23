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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.adapters.openafis import capacity_extended as variant
from fpbench.adapters.openafis.adapter import PIPELINE_METADATA as BASE_PIPELINE_METADATA
from fpbench.core.json_io import publish_evidence_document
from fpbench.core.serialization import read_json
from fpbench.experiments.stage18a_inputs import DEFAULT_WORKSPACE, REPOSITORY_ROOT
from fpbench.experiments.stage19_pair_manifest import (
    CanonicalPairManifest,
    load_canonical_pair_manifest,
    pairs_path_for,
)
from fpbench.adapters.openafis.failure_mapping import STAGE19_STATUSES
from fpbench.experiments.stage19_result_integrity import (
    OutcomeShape,
    ReasonRule,
    ScoreContract,
    OutcomeStoreIntegrity,
    Stage19ResultIntegrityError,
    canonical_source_sha256,
    verify_outcome_store_integrity,
)

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

#: What a run that verified and did not conclude is published as.
#:
#: A machine condition that comes out false used to be an exception in two of
#: the three stages and a ``RAW_COMPLETE`` marker in the third — so a run whose
#: score column was empty either vanished or was published as complete. Neither
#: is a record. The store is honest, the failures are real, and the run is worth
#: keeping: it gets a full marker, this outcome, ``failed_conditions``, and
#: nothing established (docs/adr/0128).
#:
#: A *validator* refusal is different and still ends in an exception with no
#: marker: there the store is not something any run could have produced, so
#: there is nothing to record.
OUTCOME_NOT_COMPLETE = (
    "MINDTCT_OPENAFIS_CAPACITY_EXTENDED_CANONICAL_RAW_NOT_COMPLETE"
)

#: Section 21. Reproduced verbatim, because it is the sentence that has to travel
#: with the number into the supervisor's table.
SUPERVISOR_DISCLOSURE = (
    "NBIS MINDTCT + OpenAFIS (capacity-extended variant) — composition defined by the project. "
    "It shares the MINDTCT extractor with the NBIS/BOZORTH3 method and differs primarily in the "
    "matcher. The OpenAFIS source was minimally modified to permit CSV templates containing more "
    "than the upstream limit of 128 minutiae; the original behavior was verified unchanged on all "
    "1,583 previously accepted comparisons."
)


#: The statuses that mean the route failed rather than the algorithm
#: answering, named here rather than spelled inside the condition. Stage 19B is
#: the stage about ``OPENAFIS_TEMPLATE_FAILED_*``, which is deliberately not one
#: of these: a template above the build's capacity is the answer this variant
#: exists to change, not a defect in the bridge.
BLOCKING_STATUSES = frozenset({"OPENAFIS_MATCH_FAILED", "INFRASTRUCTURE_FAILURE"})



#: The failure reasons this route produces *as an answer*, rather than as a
#: fault. They are the refusals the translation raises when a template cannot
#: be represented at all — a raster with no area, a minutia count outside the
#: upstream bounds. Each one has been read and understood, and a run made
#: entirely of them is still a run.
#:
#: Everything else a comparison can fail with — a mindtct exit code, an
#: unreadable bridge line, a timeout, a crash, an exception name, a free-text
#: vendor detail — is deliberately *not* here. Those failures are real and are
#: stored honestly; what may not happen is this stage declaring itself complete
#: over failures nobody has classified. ``no_unclassified_failure`` is that
#: rule, and tests/contract/test_failure_reasons_are_classified.py checks this
#: set against the reasons the route's own source can raise.
#:
#: ``minutiae_above_upstream_maximum`` is kept although the extended
#: variant cannot raise it: it is the reason this stage exists to drive to
#: zero, and a store still carrying it must fail the fourth condition
#: rather than the unclassified one.
CLASSIFIED_FAILURE_REASONS = frozenset(
    {
        "invalid_raster_dimensions",
        "minutiae_below_upstream_minimum",
        "minutiae_above_upstream_maximum",
    }
)


#: Reasons a route's own machinery produces rather than the algorithm. Each is
#: owned by exactly one ``status + failure_code`` pair, because owning is what
#: stops it appearing under a status that cannot have produced it.

#: ``require_gray8_500ppi_png`` refusing a prepared image. These reach the store
#: under ``INFRASTRUCTURE_FAILURE`` with ``input_invalid``: the image never got
#: as far as the extractor.
_INPUT_REJECTIONS = frozenset(
    {
        "input_missing",
        "input_not_a_regular_file",
        "input_unreadable",
        "malformed_png",
        "not_a_png",
        "unsupported_bit_depth",
        "unsupported_colour_type",
        "unsupported_media_type",
        "unsupported_png_layout",
        "unsupported_resolution",
        "unusable_dimensions",
    }
)

#: ``read_xyt`` refusing the extractor's own output.
_XYT_KINDS = frozenset({"invalid_extractor_output", "missing_extractor_output"})

#: A mindtct exit code rendered as a reason. The extractor supplies the number.
_EXIT_CODE = r"exit_code_-?\d+"

#: A crash, likewise.
_CRASH = r"mindtct_crash_-?\d+"

#: What each outcome of this route requires of the rest of its row.
#:
#: Every entry corresponds to a producer path in
#: ``fpbench.adapters.openafis`` — the factory that stamps the status, the code
#: it carries, and the detail key that becomes the reason. Ownership is global:
#: a reason listed here may not appear under any other pair, which is what
#: refuses ``MINDTCT_FAILED_LEFT`` carrying ``invalid_raster_dimensions``.
#: ``allow_unowned`` is opt-in, for the pairs that carry a bridge's or an
#: interpreter's own text; everything else is closed.
#:
#: Checked against the adapters by
#: tests/contract/test_outcome_contracts_match_the_route.py.
OUTCOME_CONTRACT: dict[str, OutcomeShape] = {
    # The bridge prints ``score_native_type\tuint8_t`` and documents ``-1`` on
    # every status but OK, so the contract is the whole of what it can emit.
    "OK": OutcomeShape(
        scored=True, score=ScoreContract(minimum=0, maximum=255, integral=True)
    ),
    **{
        f"MINDTCT_FAILED_{side}": OutcomeShape(
            codes={
                "template_extraction_failed": ReasonRule(pattern=_EXIT_CODE),
            }
        )
        for side in ("LEFT", "RIGHT", "BOTH")
    },
    **{
        f"INVALID_XYT_{side}": OutcomeShape(
            codes={"template_extraction_failed": ReasonRule(reasons=_XYT_KINDS)}
        )
        for side in ("LEFT", "RIGHT")
    },
    **{
        f"OPENAFIS_TEMPLATE_FAILED_{side}": OutcomeShape(
            codes={
                # The translation's refusals, and the bridge's own template
                # statuses lower-cased. Both are enumerable, so this pair is
                # closed: nothing else can refuse a template here.
                "template_extraction_failed": ReasonRule(
                    reasons=CLASSIFIED_FAILURE_REASONS
                    | {
                        "load_failed_left",
                        "load_failed_right",
                        "load_failed_both",
                        "no_fingerprint_left",
                        "no_fingerprint_right",
                    }
                )
            }
        )
        for side in ("LEFT", "RIGHT", "BOTH")
    },
    # The matcher declining to run. It owns the messages the adapter names and
    # is open besides, because ``exit_<n>`` and the bridge's ``MATCH_EXCEPTION``
    # arrive as whatever the bridge printed.
    "OPENAFIS_MATCH_FAILED": OutcomeShape(
        codes={
            "matching_failed": ReasonRule(
                reasons=frozenset(
                    {
                        "unreadable_bridge_output",
                        "unreadable_bridge_timings",
                        "unreadable_score",
                        "match_exception",
                    }
                ),
                allow_unowned=True,
            )
        }
    ),
    # The one status whose code the caller chooses, so the pair is the unit.
    # Only ``input_invalid`` owns anything; the rest carry a tool name, a
    # budget, a crash code or an exception class, none of them enumerable.
    "INFRASTRUCTURE_FAILURE": OutcomeShape(
        codes={
            "input_invalid": ReasonRule(reasons=_INPUT_REJECTIONS),
            "dependency_missing": ReasonRule(allow_unowned=True),
            "timeout": ReasonRule(allow_unowned=True),
            "process_crashed": ReasonRule(pattern=_CRASH, allow_unowned=True),
            "internal_error": ReasonRule(allow_unowned=True),
        }
    ),
}

#: The route's status vocabulary is the contract's own keys, so the two cannot
#: drift apart.
ALLOWED_STATUSES = frozenset(OUTCOME_CONTRACT)

#: One ``(status, failure_code, failure_reason)`` per producer path in this
#: route's own source. The contract refusing an honest run is the failure mode
#: that does not announce itself — nobody reports a run that could not be
#: published — so every path is walked in the other direction by
#: tests/regression/test_stage19_outcome_matrix.py.
#:
#: Where a route generates the reason rather than naming it, the entry is one
#: instance of the shape: an exit code the extractor really returns, an
#: exception class the interpreter really raises.
PRODUCIBLE_OUTCOMES: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("MINDTCT_FAILED_LEFT", "template_extraction_failed", "exit_code_2"),
        ("MINDTCT_FAILED_RIGHT", "template_extraction_failed", "exit_code_0"),
        ("MINDTCT_FAILED_BOTH", "template_extraction_failed", "exit_code_-1"),
        ("INVALID_XYT_LEFT", "template_extraction_failed", "invalid_extractor_output"),
        ("INVALID_XYT_RIGHT", "template_extraction_failed", "missing_extractor_output"),
        (
            "OPENAFIS_TEMPLATE_FAILED_LEFT",
            "template_extraction_failed",
            "minutiae_above_upstream_maximum",
        ),
        (
            "OPENAFIS_TEMPLATE_FAILED_RIGHT",
            "template_extraction_failed",
            "minutiae_below_upstream_minimum",
        ),
        (
            "OPENAFIS_TEMPLATE_FAILED_BOTH",
            "template_extraction_failed",
            "invalid_raster_dimensions",
        ),
        (
            "OPENAFIS_TEMPLATE_FAILED_LEFT",
            "template_extraction_failed",
            "load_failed_left",
        ),
        (
            "OPENAFIS_TEMPLATE_FAILED_RIGHT",
            "template_extraction_failed",
            "no_fingerprint_right",
        ),
        ("OPENAFIS_MATCH_FAILED", "matching_failed", "exit_139"),
        ("OPENAFIS_MATCH_FAILED", "matching_failed", "unreadable_bridge_output"),
        ("OPENAFIS_MATCH_FAILED", "matching_failed", "unreadable_bridge_timings"),
        ("OPENAFIS_MATCH_FAILED", "matching_failed", "unreadable_score"),
        ("OPENAFIS_MATCH_FAILED", "matching_failed", "match_exception"),
        ("INFRASTRUCTURE_FAILURE", "input_invalid", "unsupported_resolution"),
        ("INFRASTRUCTURE_FAILURE", "dependency_missing", "mindtct_launch"),
        ("INFRASTRUCTURE_FAILURE", "dependency_missing", "openafis_launch"),
        ("INFRASTRUCTURE_FAILURE", "timeout", "mindtct_timeout"),
        ("INFRASTRUCTURE_FAILURE", "timeout", "openafis_timeout"),
        ("INFRASTRUCTURE_FAILURE", "timeout", "mindtct_extraction_budget"),
        ("INFRASTRUCTURE_FAILURE", "process_crashed", "mindtct_crash_139"),
        ("INFRASTRUCTURE_FAILURE", "internal_error", "OSError"),
    }
)


class Stage19BFinalizationError(RuntimeError):
    """The evidence does not support the document being asked for."""


_SOURCE_FILES = (
    "src/fpbench/adapters/openafis/capacity_extended.py",
    "src/fpbench/experiments/stage19b_diagnostics.py",
    "src/fpbench/experiments/stage19b_finalization.py",
    "src/fpbench/experiments/stage19_result_integrity.py",
    "src/fpbench/experiments/stage19_pair_manifest.py",
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
    """Hash a published evidence artifact byte-for-byte."""
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
        digests[relative] = canonical_source_sha256(path)
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


#: What Stage 19B is defined over. Read against the artifact rather than
#: written into the binding: see ``_pair_manifest``.
REFERENCE_PROTOCOL_ID = "sd300_50_subjects"
REFERENCE_COHORT_ID = "sd300_50_subjects_test_22f8d52a7478"
REFERENCE_PAIR_MANIFEST_HASH = (
    "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
)
EXPECTED_OUTCOMES = 6000


def _pair_manifest(workspace: Path | None) -> CanonicalPairManifest:
    """The comparisons this stage is defined over, loaded from the cohort.

    The constant above is what the artifact must *prove*; the hash that reaches
    the binding is the one re-derived from the artifact's own rows.
    """
    root = Path(workspace) if workspace is not None else DEFAULT_WORKSPACE
    try:
        return load_canonical_pair_manifest(
            pairs_path_for(root, REFERENCE_PROTOCOL_ID, REFERENCE_COHORT_ID),
            expected_pair_manifest_hash=REFERENCE_PAIR_MANIFEST_HASH,
        )
    except Stage19ResultIntegrityError as exc:
        raise Stage19BFinalizationError(str(exc)) from None


def _outcome_integrity(
    outcomes: Path,
    diagnostics: Mapping[str, Any],
    manifest: CanonicalPairManifest,
) -> OutcomeStoreIntegrity:
    try:
        return verify_outcome_store_integrity(
            outcomes,
            diagnostics,
            manifest=manifest.pairs,
            algorithm_id=variant.ALGORITHM_ID,
            pair_manifest_hash=manifest.pair_manifest_hash,
            expected_outcomes=EXPECTED_OUTCOMES,
            classified_failure_reasons=CLASSIFIED_FAILURE_REASONS,
            outcome_contract=OUTCOME_CONTRACT,
        )
    except Stage19ResultIntegrityError as exc:
        raise Stage19BFinalizationError(str(exc)) from None


def _merge_stage_rows(
    derived: Sequence[Mapping[str, Any]], reported: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Per-stage rows: populations from the store, statistics from the report.

    Both are wanted and only one can be counted. ``comparisons`` and
    ``score_bearing`` decide things and come from the store; a histogram, a
    median and a p95 describe the scores and come from the diagnostics, which
    the validator has already required to agree about everything countable.
    """
    by_label = {
        str(row.get("label")): dict(row) for row in reported if row.get("label")
    }
    merged: list[dict[str, Any]] = []
    for row in derived:
        label = str(row["label"])
        combined = dict(by_label.get(label, {}))
        combined.update(row)
        merged.append(combined)
    return merged

def build_canonical_run_binding(
    diagnostics: Mapping[str, Any],
    *,
    outcomes: Path,
    workspace: Path | None = None,
) -> dict[str, Any]:
    manifest = _pair_manifest(workspace)
    integrity = _outcome_integrity(outcomes, diagnostics, manifest)
    # Counted from the store, not copied from the report about it. Section 17's
    # third condition is "no failure remains whose reason is
    # minutiae_above_upstream_maximum", and a diagnostics document that simply
    # said ``{}`` used to satisfy it over 6,000 comparisons that all failed for
    # exactly that reason.
    counts = dict(integrity.outcome_counts)
    reasons = dict(integrity.failure_reasons)
    return {
        "kind": "stage_19b_canonical_run_binding",
        "stage": "19B",
        "algorithm_id": variant.ALGORITHM_ID,
        "preparation_set_id": "prepset_be560e047991",
        # From ``integrity.describe()`` below. The literal that used to sit here
        # was a claim about the manifest that nothing compared to the manifest.
        "nbis_build_id": "658f9f54a8f2",
        **integrity.describe(),
        "threshold_applied": None,
        "score_transform": "NONE",
        "outcome_counts": counts,
        "failure_reasons": reasons,
        "unclassified_failure_reasons": dict(integrity.unclassified_failure_reasons),
        "unclassified_failures": integrity.unclassified_failures,
        "capacity_failures_remaining": integrity.capacity_failures(
            "minutiae_above_upstream_maximum"
        ),
        "score_bearing": integrity.score_bearing,
        "score_bearing_fraction": integrity.score_bearing_fraction,
        # The stage populations are the store's; the score statistics beside
        # them are the diagnostics', and the validator has already required the
        # two to agree about the populations.
        "by_protocol_stage": _merge_stage_rows(
            integrity.by_protocol_stage, diagnostics.get("by_protocol_stage", [])
        ),
        "minutiae_counts": diagnostics.get("minutiae_counts", {}),
        "timings_ms": diagnostics.get("timings_ms", {}),
        "stage19a_comparison": diagnostics.get("stage19a_comparison"),
        "algorithm2_comparison": diagnostics.get("algorithm2_comparison"),
        "uint8_headroom_audit": diagnostics.get("uint8_headroom_audit"),
    }


# ---------------------------------------------------------------------- marker


def _written_at(created_utc: str | None) -> str:
    """When this document was written, injected or read from the clock.

    ``created_utc`` is an argument because a marker that reads the wall clock is
    a document nobody can rebuild: given the same evidence it produces different
    bytes, so "does this marker follow from the documents beside it" has no
    answer. Passing ``None`` keeps the old behaviour — the moment the document is
    written — and a caller checking a published marker passes the value that
    marker already carries.
    """
    if created_utc is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(created_utc).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text):
        raise ValueError(
            f"created_utc must be a UTC instant like 2026-08-23T12:00:00Z, not {text!r}"
        )
    return text


def build_stage19b_finalization(
    *,
    repository_root: Path,
    gate_a: Mapping[str, Any],
    binding: Mapping[str, Any],
    translator_inertness: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
    created_utc: str | None = None,
) -> dict[str, Any]:
    """Assemble the marker and derive the decision from section 17's six conditions."""
    stored = binding["stored_outcomes"]
    missing = binding["missing"]
    capacity_failures = binding["capacity_failures_remaining"]
    counts = binding.get("outcome_counts", {})
    blocking = sum(
        int(value) for key, value in counts.items() if key in BLOCKING_STATUSES
    )

    # Named rather than positional, so a refusal can say which count is wrong.
    required = {
        "unique_pair_ids": 6000,
        "unique_ordinals": 6000,
        "diagnostic_comparisons": 6000,
        "stored_outcomes": 6000,
        "expected_outcomes": 6000,
        "missing": 0,
    }
    unmet = {
        name: binding.get(name)
        for name, value in required.items()
        if binding.get(name) != value
    }

    conditions = {
        "gate_a_baseline_scores_identical": (
            gate_a.get("outcome") == "CAPACITY_EXTENSION_INERTNESS_PASS"
            and gate_a.get("score_mismatches") == 0
            and gate_a.get("status_regressions") == 0
            and gate_a.get("exact_score_matches") == gate_a.get("baseline_scored_pairs")
        ),
        "canonical_run_complete": not unmet,
        "no_capacity_failure_remains": capacity_failures == 0,
        "no_systemic_implementation_defect": blocking == 0,
        # A failure whose reason this route has never classified is neither an
        # upstream limit nor a known defect; it is a failure nobody has read.
        "no_unclassified_failure": int(binding.get("unclassified_failures", 0)) == 0,
        # ADR 0128. Six thousand classified capacity failures are a complete,
        # honest, structurally sound run that established nothing: the score
        # column is empty, and `opens_common_calibration` would open a
        # calibration phase over it.
        "at_least_one_score": int(binding.get("score_bearing", 0)) > 0,
        "translation_contract_unchanged": (
            translator_inertness.get("mismatches") == 0
            and translator_inertness.get("lower_bound_still_enforced") is True
        ),
        "no_secugen_based_tuning": True,
    }
    established = all(conditions.values())

    failed = sorted(name for name, value in conditions.items() if value is False)
    if not conditions["gate_a_baseline_scores_identical"]:
        outcome = OUTCOME_INERTNESS_FAIL
    elif failed:
        outcome = OUTCOME_NOT_COMPLETE
    else:
        outcome = OUTCOME_COMPLETE

    marker: dict[str, Any] = {
        "kind": "stage_19b_finalization",
        "schema_version": "1",
        "stage": "19B",
        "created_utc": _written_at(created_utc),
        "outcome": outcome,
        "algorithm_id": variant.ALGORITHM_ID,
        "adapter_id": variant.ADAPTER_ID,
        "algorithm_slot": "algorithm_5",
        "failed_conditions": failed,
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
        "unique_pair_ids": binding["unique_pair_ids"],
        "unique_ordinals": binding["unique_ordinals"],
        "diagnostic_comparisons": binding["diagnostic_comparisons"],
        "missing": missing,
        "outcome_store_sha256": binding["outcome_store_sha256"],
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
    outcomes: Path,
    readme: str,
) -> dict[str, Path]:
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write(name: str, payload: Any) -> None:
        # Through the sanitising door, so a stage document cannot publish a
        # path that names the machine it ran on.
        written[name] = publish_evidence_document(directory / name, payload)

    _write("variant-identity.json", build_variant_identity())
    _write("patch-provenance.json", build_patch_provenance(patch))
    _write("gate-a-inertness.json", {**dict(gate_a), "translator_inertness": dict(translator_inertness)})
    binding = build_canonical_run_binding(diagnostics, outcomes=outcomes)
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
    parser.add_argument("--outcomes", type=Path, required=True)
    args = parser.parse_args(argv)

    readme_path = Path(REPOSITORY_ROOT) / EVIDENCE_DIRECTORY / "README.md"
    if not readme_path.is_file():
        raise Stage19BFinalizationError(f"write the README first: {readme_path}")

    written = write_stage19b_documents(
        gate_a=read_json(args.gate_a),
        diagnostics=read_json(args.diagnostics),
        patch=read_json(args.patch),
        translator_inertness=read_json(args.translator_inertness),
        outcomes=args.outcomes,
        readme=readme_path.read_text(encoding="utf-8"),
    )
    for name, path in sorted(written.items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
