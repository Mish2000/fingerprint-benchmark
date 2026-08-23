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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.adapters.mcc import adapter as production
from fpbench.adapters.mcc import identity as route
from fpbench.core.json_io import publish_evidence_document
from fpbench.core.serialization import read_json
from fpbench.experiments import stage20b_identity as frozen
from fpbench.experiments.stage20b_gates import GATE_A_PASS, GATE_B_PASS
from fpbench.experiments.stage18a_inputs import DEFAULT_WORKSPACE, REPOSITORY_ROOT
from fpbench.experiments.stage19_pair_manifest import (
    CanonicalPairManifest,
    load_canonical_pair_manifest,
    pairs_path_for,
)
from fpbench.adapters.mcc.failure_mapping import STAGE20B_STATUSES
from fpbench.adapters.mcc.identity import SCORE_MAXIMUM, SCORE_MINIMUM
from fpbench.experiments.stage19_result_integrity import (
    OutcomeShape,
    ReasonRule,
    ScoreContract,
    OutcomeStoreIntegrity,
    Stage19ResultIntegrityError,
    bound_manifest_digest,
    verify_outcome_store_integrity,
)

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
CLASSIFIED_FAILURE_REASONS = frozenset(
    {
        "invalid_raster_dimensions",
        "minutia_outside_mindtct_raster",
        "invalid_mindtct_direction",
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

#: What each outcome of this route requires of the rest of its row. See the
#: matching table in ``stage19a_finalization`` for the rules; the entries here
#: come from ``fpbench.adapters.mcc`` and from the C# bridge it drives, which
#: publishes the exception type as the detail — so the pairs that carry a
#: vendor's text are open and the pairs that carry a translation refusal are not.
OUTCOME_CONTRACT: dict[str, OutcomeShape] = {
    # The SDK's similarity, from ``mcc.identity``.
    "OK": OutcomeShape(
        scored=True,
        score=ScoreContract(minimum=SCORE_MINIMUM, maximum=SCORE_MAXIMUM),
    ),
    **{
        f"MINDTCT_FAILED_{side}": OutcomeShape(
            codes={"template_extraction_failed": ReasonRule(pattern=_EXIT_CODE)}
        )
        for side in ("LEFT", "RIGHT", "BOTH")
    },
    **{
        f"INVALID_XYT_{side}": OutcomeShape(
            codes={"template_extraction_failed": ReasonRule(reasons=_XYT_KINDS)}
        )
        for side in ("LEFT", "RIGHT", "BOTH")
    },
    **{
        # Owns the translation's refusals *and* is open: the bridge passes the
        # SDK's own message through, so ``System.ArgumentException`` arrives
        # here as legitimately as ``invalid_raster_dimensions``.
        f"MCC_TEMPLATE_REFUSAL_{side}": OutcomeShape(
            codes={
                "template_extraction_failed": ReasonRule(
                    reasons=CLASSIFIED_FAILURE_REASONS,
                    allow_unowned=True,
                )
            }
        )
        for side in ("LEFT", "RIGHT", "BOTH")
    },
    # ``sdk_refusal`` is deliberately owned by neither this nor
    # ``MCC_TEMPLATE_REFUSAL_*``: the adapter writes it as the fallback when the
    # SDK declined without a message, on *both* paths, so claiming it for one
    # would refuse the other. It is the vendor's silence, not a route's
    # vocabulary, and stays unclassified like the rest of that text.
    "MCC_MATCH_REFUSAL": OutcomeShape(
        codes={"matching_failed": ReasonRule(allow_unowned=True)}
    ),
    "MCC_INVALID_SCORE": OutcomeShape(
        codes={"no_score": ReasonRule(reasons=frozenset({"invalid_score"}))}
    ),
    "MCC_RUNTIME_FAILURE": OutcomeShape(
        codes={
            "dependency_missing": ReasonRule(
                reasons=frozenset({"bridge_launch", "clr_failure"}),
                pattern=r"bridge_crash_-?\d+",
                allow_unowned=True,
            )
        }
    ),
    "BRIDGE_FAILURE": OutcomeShape(
        codes={
            "internal_error": ReasonRule(
                reasons=frozenset(
                    {
                        "no_bridge_output",
                        "unreadable_bridge_output",
                        "unknown_bridge_status",
                        "unexpected_bridge_state",
                        "unreadable_score",
                        "workspace_not_visible_to_windows",
                        "bridge_refusal",
                    }
                ),
                allow_unowned=True,
            )
        }
    ),
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

#: The route's status vocabulary is the contract's own keys.
ALLOWED_STATUSES = frozenset(OUTCOME_CONTRACT)

#: One ``(status, failure_code, failure_reason)`` per producer path in this
#: route's own source, including the C# bridge — which publishes the exception
#: type as its detail, so ``System.ArgumentException`` is a row this route
#: really produces. See the matching set in ``stage19a_finalization``.
PRODUCIBLE_OUTCOMES: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("MINDTCT_FAILED_LEFT", "template_extraction_failed", "exit_code_2"),
        ("MINDTCT_FAILED_RIGHT", "template_extraction_failed", "exit_code_0"),
        ("MINDTCT_FAILED_BOTH", "template_extraction_failed", "exit_code_-1"),
        ("INVALID_XYT_LEFT", "template_extraction_failed", "invalid_extractor_output"),
        ("INVALID_XYT_RIGHT", "template_extraction_failed", "missing_extractor_output"),
        ("INVALID_XYT_BOTH", "template_extraction_failed", "invalid_extractor_output"),
        (
            "MCC_TEMPLATE_REFUSAL_LEFT",
            "template_extraction_failed",
            "invalid_raster_dimensions",
        ),
        (
            "MCC_TEMPLATE_REFUSAL_RIGHT",
            "template_extraction_failed",
            "minutia_outside_mindtct_raster",
        ),
        (
            "MCC_TEMPLATE_REFUSAL_BOTH",
            "template_extraction_failed",
            "invalid_mindtct_direction",
        ),
        ("MCC_TEMPLATE_REFUSAL_LEFT", "template_extraction_failed", "sdk_refusal"),
        (
            "MCC_TEMPLATE_REFUSAL_LEFT",
            "template_extraction_failed",
            "System.ArgumentException",
        ),
        ("MCC_MATCH_REFUSAL", "matching_failed", "sdk_refusal"),
        ("MCC_MATCH_REFUSAL", "matching_failed", "System.InvalidOperationException"),
        ("MCC_INVALID_SCORE", "no_score", "invalid_score"),
        ("MCC_RUNTIME_FAILURE", "dependency_missing", "bridge_launch"),
        ("MCC_RUNTIME_FAILURE", "dependency_missing", "bridge_crash_134"),
        ("MCC_RUNTIME_FAILURE", "dependency_missing", "clr_failure"),
        ("BRIDGE_FAILURE", "internal_error", "no_bridge_output"),
        ("BRIDGE_FAILURE", "internal_error", "unreadable_bridge_output"),
        ("BRIDGE_FAILURE", "internal_error", "unknown_bridge_status"),
        ("BRIDGE_FAILURE", "internal_error", "unexpected_bridge_state"),
        ("BRIDGE_FAILURE", "internal_error", "unreadable_score"),
        ("BRIDGE_FAILURE", "internal_error", "workspace_not_visible_to_windows"),
        ("BRIDGE_FAILURE", "internal_error", "bridge_refusal"),
        ("INFRASTRUCTURE_FAILURE", "input_invalid", "unsupported_resolution"),
        ("INFRASTRUCTURE_FAILURE", "dependency_missing", "mindtct_launch"),
        ("INFRASTRUCTURE_FAILURE", "timeout", "mindtct_timeout"),
        ("INFRASTRUCTURE_FAILURE", "timeout", "mcc_bridge_timeout"),
        ("INFRASTRUCTURE_FAILURE", "process_crashed", "mindtct_crash_139"),
        ("INFRASTRUCTURE_FAILURE", "internal_error", "OSError"),
    }
)


#: The two conditions that have an outcome of their own, so they are not
#: also required for COMPLETE — a failed gate is published as a failed
#: gate rather than refused.
_GATE_CONDITIONS = frozenset(
    {"gate_a_bridge_reproduction", "gate_b_mindtct_parity"}
)




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


#: The cohort Stage 20B ran over — the same one every other algorithm used.
#: Named here rather than imported from an earlier stage's identity module,
#: which this stage's boundary audit does not permit it to read.
_PROTOCOL_ID = "sd300_50_subjects"
_COHORT_ID = "sd300_50_subjects_test_22f8d52a7478"


def _pair_manifest(workspace: Path | None) -> CanonicalPairManifest:
    """The comparisons Stage 20B is defined over, loaded from the cohort.

    ``REFERENCE_PAIR_MANIFEST_HASH`` is what the artifact must *prove*; the hash
    that reaches the binding is re-derived from the artifact's own rows.
    """
    root = Path(workspace) if workspace is not None else DEFAULT_WORKSPACE
    try:
        return load_canonical_pair_manifest(
            pairs_path_for(root, _PROTOCOL_ID, _COHORT_ID),
            expected_pair_manifest_hash=frozen.REFERENCE_PAIR_MANIFEST_HASH,
        )
    except Stage19ResultIntegrityError as exc:
        raise Stage20BFinalizationError(str(exc)) from None


def build_canonical_run_binding(
    diagnostics: Mapping[str, Any],
    *,
    stored: int,
    missing: int,
    manifest: CanonicalPairManifest,
    integrity: OutcomeStoreIntegrity,
) -> dict[str, Any]:
    """What was compared, and the arithmetic of whether all of it was.

    Every population here is counted off the verified store. They used to be
    copied out of the diagnostics document, which is a *report* of the store:
    ``outcome_counts`` decides ``no_systemic_bridge_defect``, so a report
    saying ``{"OK": 6000}`` over six thousand ``BRIDGE_FAILURE`` rows published
    a run with no systemic defect. The validator already refuses a diagnostics
    document that contradicts the store, and this reads the store's own numbers
    so that there is nothing left to contradict.
    """
    return {
        "kind": "stage_20b_canonical_run_binding",
        "stage": "20B",
        "algorithm_id": frozen.ALGORITHM_ID,
        "run_id": frozen.RUN_ID,
        "preparation_set_id": frozen.REFERENCE_PREPARATION_SET_ID,
        # Re-derived from the manifest artifact, not restated from a constant.
        "pair_manifest_hash": manifest.pair_manifest_hash,
        "nbis_build_id": frozen.NBIS_BUILD_ID,
        "pairs_regenerated": False,
        "pair_order_changed": False,
        "dataset_changed": False,
        "expected_outcomes": frozen.EXPECTED_OUTCOMES,
        "stored_outcomes": stored,
        "missing": missing,
        "protocol_stages": {
            str(row["label"]): int(row["comparisons"])
            for row in integrity.by_protocol_stage
        },
        "outcome_counts": dict(integrity.outcome_counts),
        "failure_reasons": dict(integrity.failure_reasons),
        "unclassified_failure_reasons": dict(integrity.unclassified_failure_reasons),
        "unclassified_failures": integrity.unclassified_failures,
        "score_bearing": integrity.score_bearing,
        "score_bearing_fraction": integrity.score_bearing_fraction,
        "score_type": "System.Double",
        "score_range": [route.SCORE_MINIMUM, route.SCORE_MAXIMUM],
        "score_direction": "HIGHER_MORE_SIMILAR",
        "score_transform": "NONE",
        "threshold_applied": None,
        "calibration_performed": False,
        "decisions_produced": 0,
        "metrics_produced": [],
    }


def _verified_store(
    outcomes_path: Path | None,
    diagnostics: Mapping[str, Any],
    manifest: CanonicalPairManifest,
) -> OutcomeStoreIntegrity:
    """Stage 19's validator, over Stage 20B's store.

    Required, with no path meaning "skip": the reviewer's duplicate-ordinal
    store passed every check this stage had of its own, and a validator a
    publisher can decline to run is not a validator.
    """
    if outcomes_path is None:
        raise Stage20BFinalizationError(
            "Stage 20B finalization needs the outcome store itself; the parsed "
            "outcomes are a reading of it and cannot verify it"
        )
    try:
        return verify_outcome_store_integrity(
            Path(outcomes_path),
            diagnostics,
            manifest=manifest.pairs,
            algorithm_id=frozen.ALGORITHM_ID,
            pair_manifest_hash=manifest.pair_manifest_hash,
            expected_outcomes=frozen.EXPECTED_OUTCOMES,
            classified_failure_reasons=CLASSIFIED_FAILURE_REASONS,
            outcome_contract=OUTCOME_CONTRACT,
        )
    except Stage19ResultIntegrityError as exc:
        raise Stage20BFinalizationError(str(exc)) from None

def build_result_integrity(
    outcomes: Sequence[Any],
    diagnostics: Mapping[str, Any],
    manifest: CanonicalPairManifest,
    integrity: OutcomeStoreIntegrity,
) -> dict[str, Any]:
    """The checks that make the stored file trustworthy on its own terms.

    Not statistics: these are the properties a result file must have before any
    number in it is worth reading. Every pair appears exactly once, in the
    manifest's order, *and is the manifest's pair*; no score sits outside the
    frozen contract; no failure was stored as a zero and no zero was stored as a
    failure.

    ``integrity`` is the Stage 19 validator's verdict over the same store, and
    it has already refused everything structural: a repeated ordinal, an ordinal
    outside 0..5,999, a row that is not the manifest's row, a row naming another
    algorithm, a failure carrying a score. This function reports what that
    verdict found and adds the route's own score contract. It used to run a
    weaker check of its own, which compared every row against
    ``manifest.pairs[ordinal]`` and never asked whether one ordinal appeared
    6,000 times.
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
        # Read off the rows, so a store carrying another algorithm's results
        # says so here instead of being described by a constant.
        "algorithm_ids_present": sorted(
            {str(outcome.algorithm_id) for outcome in outcomes}
        ),
        # Also read off the verified store rather than asserted. The validator
        # would have refused a store bound to other rows, but "the check ran and
        # did not raise" is not a thing a reader can see in a published file.
        "bound_to_pair_manifest": (
            integrity.pair_manifest_hash == manifest.pair_manifest_hash
            and integrity.bound_manifest_digest == bound_manifest_digest(manifest.pairs)
        ),
        "pair_manifest_hash": integrity.pair_manifest_hash,
        "bound_manifest_digest": integrity.bound_manifest_digest,
        "outcome_store_sha256": integrity.outcome_store_sha256,
        "unique_pair_ids": integrity.unique_pair_ids,
        "unique_ordinals": integrity.unique_ordinals,
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


def build_stage20b_finalization(
    *,
    repository_root: Path,
    gate_a: Mapping[str, Any],
    gate_b: Mapping[str, Any],
    binding: Mapping[str, Any],
    integrity: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
    created_utc: str | None = None,
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
    # From the binding, which counts them off the verified store. Read from the
    # diagnostics, this condition asked the run to report its own defects.
    translation_defects = sum(
        value
        for key, value in binding.get("failure_reasons", {}).items()
        if key in CLASSIFIED_FAILURE_REASONS
        or key == "workspace_not_visible_to_windows"
    )
    # A reason this route has never classified is not a translation defect and
    # not an upstream answer; it is a failure nobody has read.
    unclassified_failures = int(binding.get("unclassified_failures", 0))

    # Every structural property, not just the row count. The published
    # integrity document already said ``duplicate_pair_ids=5999`` and
    # ``ordinals_are_complete=false`` while ``canonical_run_complete`` said the
    # run was complete, because the condition only ever looked at ``stored``.
    #
    # Kept as a list of named requirements rather than one long ``and`` so the
    # refusal can say which one failed: "stored 6000 with 0 missing" is a true
    # sentence and a useless one when what is wrong is that all six thousand
    # rows are the same pair.
    structural = {
        "stored_outcomes": (stored, frozen.EXPECTED_OUTCOMES),
        "missing": (missing, 0),
        "every_attempt_stored": (integrity["every_attempt_stored"], True),
        "duplicate_pair_ids": (integrity["duplicate_pair_ids"], 0),
        "ordinals_are_complete": (integrity["ordinals_are_complete"], True),
        "ordinals_are_the_manifest_order": (
            integrity["ordinals_are_the_manifest_order"],
            True,
        ),
        # Read from the run binding, where the manifest hash is measured and
        # published. It was read from the integrity document, which is the one
        # place it is *not* independently recorded.
        "pair_manifest_hash": (
            binding.get("pair_manifest_hash"),
            frozen.REFERENCE_PAIR_MANIFEST_HASH,
        ),
        #
        # ``unique_pair_ids`` and ``unique_ordinals`` are deliberately not here.
        # They are not dropped checks: ``duplicate_pair_ids == 0`` *is*
        # ``len(ids) - len(set(ids)) == 0``, so with ``stored_outcomes`` fixed
        # at 6,000 the distinct count is 6,000; and ``ordinals_are_complete``
        # *is* ``len(set(ordinals)) == len(outcomes)`` with the range pinned to
        # 0..5,999. Requiring the derived pair as well made this condition
        # unsatisfiable from the published evidence — the marker could not be
        # rebuilt from the documents beside it, which is the property that lets
        # a reader check it at all.
        "algorithm_ids_present": (
            integrity["algorithm_ids_present"],
            [frozen.ALGORITHM_ID],
        ),
        "scores_outside_contract": (integrity["scores_outside_contract"], 0),
        "failures_recorded_as_zero": (integrity["failures_recorded_as_zero"], 0),
        "successes_recorded_without_a_score": (
            integrity["successes_recorded_without_a_score"],
            0,
        ),
    }
    unmet = {
        name: (found, required)
        for name, (found, required) in structural.items()
        if found != required
    }

    conditions = {
        "gate_a_bridge_reproduction": gate_a.get("outcome") == GATE_A_PASS
        and gate_a.get("mismatches") == 0,
        "gate_b_mindtct_parity": gate_b.get("outcome") == GATE_B_PASS
        and gate_b.get("mismatches") == 0,
        "canonical_run_complete": not unmet,
        "route_unchanged": (
            binding["pairs_regenerated"] is False
            and binding["pair_order_changed"] is False
            and binding["dataset_changed"] is False
        ),
        "no_systemic_bridge_defect": bridge_defects == 0 and runtime_defects == 0,
        "no_systemic_translation_defect": translation_defects == 0,
        "no_unclassified_failure": unclassified_failures == 0,
        # ADR 0128. An existence requirement, not a performance threshold.
        "at_least_one_score": score_bearing > 0,
        "no_parameter_selection": True,
        "no_calibration": binding["calibration_performed"] is False,
        "no_threshold_selection": binding["threshold_applied"] is None,
    }

    failed = sorted(name for name, value in conditions.items() if value is False)
    if not conditions["gate_a_bridge_reproduction"]:
        outcome = frozen.OUTCOME_GATE_A_FAIL
    elif not conditions["gate_b_mindtct_parity"]:
        outcome = frozen.OUTCOME_GATE_B_FAIL
    elif failed:
        # The evidence is written and the marker says which conditions were not
        # met, including the structural detail that used to be an exception —
        # ``duplicate_pair_ids is 5999, required 0`` and the rest.
        outcome = frozen.OUTCOME_NOT_COMPLETE
    else:
        # Every remaining condition, not just the structural ones. They were
        # computed, published in ``completion_conditions``, and read by nobody:
        # a run of 6,000 unique comparisons in which every single one was a
        # BRIDGE_FAILURE published ``no_systemic_bridge_defect: false`` and
        # ``outcome: ..._COMPLETE`` in the same document, and
        # ``publication_eligible`` followed the outcome.
        #
        # The two gates are excluded because each has its own outcome above;
        # everything else here is a requirement for calling the run complete.
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
        "created_utc": _written_at(created_utc),
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
        "failed_conditions": failed,
        "unmet_structural_requirements": {
            name: {"found": found, "required": required}
            for name, (found, required) in sorted(unmet.items())
        },
        "expected_outcomes": frozen.EXPECTED_OUTCOMES,
        "stored_outcomes": stored,
        "score_bearing": score_bearing,
        "missing": missing,
        "mcc_full_score_coverage": full_coverage,
        "failure_count": stored - score_bearing,
        "failure_reasons": binding["failure_reasons"],
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
    outcomes_path: Path | None = None,
    workspace: Path | None = None,
) -> dict[str, Path]:
    directory = Path(repository_root) / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write(name: str, payload: Any) -> None:
        # Through the sanitising door, so a stage document cannot publish a
        # path that names the machine it ran on.
        written[name] = publish_evidence_document(directory / name, payload)

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
    manifest = _pair_manifest(workspace)
    # Before any document derived from the run is written. The binding used to
    # be published first, so a store the validator was about to refuse still
    # left a canonical-run-binding.json behind in the evidence directory.
    verified = _verified_store(outcomes_path, diagnostics, manifest)
    binding = build_canonical_run_binding(
        diagnostics,
        stored=stored,
        missing=missing,
        manifest=manifest,
        integrity=verified,
    )
    _write("canonical-run-binding.json", binding)
    integrity = build_result_integrity(outcomes, diagnostics, manifest, verified)
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
        outcomes_path=args.outcomes,
        environment=recorded.get("runtime", {}),
        runtime=recorded.get("dependencies", {}),
        readme=readme_path.read_text(encoding="utf-8"),
    )
    for name, path in sorted(written.items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
