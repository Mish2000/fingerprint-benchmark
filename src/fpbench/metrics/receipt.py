"""Assembling the two files that close an evaluation, and the copies that leave.

The receipt is the artefact of stage 5B meant to leave the workspace, and it is
built the way stage 4B's and 5A's were: every field derived from something
already verified, the whole document run through a sanitiser before it can be
written, and a verifier that re-derives each claim rather than trusting the file
to describe itself.

The one thing that changes at this layer is what the sanitiser permits. A
derivation receipt may carry no outcome at all, because a count of matches under
a threshold nobody had justified was not a number this project was entitled to
publish. That justification now exists — a documented threshold, named
denominators, an explicit population — so aggregate outcomes are exactly what
this receipt is *for*. What stays forbidden is everything below the aggregate:
scores, subjects, fingers, images, pairs, jobs, filenames, paths (spec section
58).

The marker comes after, and only after every other file has been read back and
re-hashed. Without it, a directory containing a definition, a policy, counts,
observations, a summary, a report and a receipt is retryable work in progress
(docs/adr/0020).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.core.errors import EvaluationFinalizationError, ResultConflictError
from fpbench.core.evaluation_models import (
    EVALUATION_FINALIZATION_SCHEMA_VERSION,
    EVALUATION_RECEIPT_SCHEMA_VERSION,
    EVALUATION_SCOPE_STATEMENT,
    STRUCTURAL_COUNT_KEYS,
    EvaluationFinalizationMarker,
    EvaluationReceipt,
    EvaluationSummary,
    MetricDerivationDefinition,
    evaluation_finalization_fingerprint,
    evaluation_receipt_content_hash,
    evaluation_receipt_fingerprint,
    evaluation_summary_content_hash,
    report_content_hash,
)
from fpbench.core.metric_models import (
    MetricObservation,
    MetricPolicy,
    MetricSetManifest,
)
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import require_exact_int, to_plain

__all__ = [
    "EVIDENCE_DIRECTORY",
    "build_evaluation_receipt",
    "build_evaluation_finalization_marker",
    "structural_counts_of",
    "write_evaluation_evidence_copies",
]

#: One JSON and one Markdown file per metric set, so two policies over the same
#: decisions never overwrite each other's evidence.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-native-evaluation"


def structural_counts_of(
    *,
    total_decisions: int,
    total_eligibility_units: int,
    unconditional_rows: int,
    conditional_rows: int,
    negative_sanity_rows: int,
) -> Mapping[str, int]:
    """The shape of the evaluation, in the fixed key order the receipt expects."""
    counts = {
        "decisions": require_exact_int(total_decisions, "total_decisions"),
        "eligibility_units": require_exact_int(
            total_eligibility_units, "total_eligibility_units"
        ),
        "unconditional_rows": require_exact_int(
            unconditional_rows, "unconditional_rows"
        ),
        "conditional_rows": require_exact_int(conditional_rows, "conditional_rows"),
        "negative_sanity_rows": require_exact_int(
            negative_sanity_rows, "negative_sanity_rows"
        ),
    }
    missing = [key for key in STRUCTURAL_COUNT_KEYS if key not in counts]
    if missing:  # pragma: no cover - guarded by the signature
        raise EvaluationFinalizationError(f"structural counts are missing {missing}")
    return counts


def build_evaluation_receipt(
    *,
    manifest: MetricSetManifest,
    definition: MetricDerivationDefinition,
    policy: MetricPolicy,
    observations: Sequence[MetricObservation],
    releases: Sequence[str],
    structural_counts: Mapping[str, int],
    run_id: str,
    result_set_id: str,
    decision_profile_id: str,
    metric_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> EvaluationReceipt:
    """Derive the sanitised receipt for a complete, verified metric set.

    Raises:
        EvaluationFinalizationError: the links do not agree with one another, or
            the metric software is not committed and clean.
    """
    if not metric_software.is_research_grade:
        raise EvaluationFinalizationError(
            "an evaluation receipt needs a committed, clean metric-engine "
            "revision (docs/adr/0017)"
        )
    if software_provenance_fingerprint(metric_software) != (
        manifest.metric_software_fingerprint
    ):
        raise EvaluationFinalizationError(
            "the metric software does not fingerprint to the metric-set software "
            "identity"
        )
    if metric_software.source_revision != manifest.metric_source_revision:
        raise EvaluationFinalizationError(
            "the metric software and metric set name different source revisions"
        )
    if definition.metric_policy_fingerprint != policy.policy_fingerprint:
        raise EvaluationFinalizationError(
            "the definition pins a different metric policy than the one applied"
        )
    if policy.policy_fingerprint != manifest.metric_policy_fingerprint:
        raise EvaluationFinalizationError(
            "the metric set was computed under a different policy than the one "
            "stored beside it"
        )

    metrics: dict[str, dict[str, dict[str, int]]] = {}
    for observation in observations:
        metrics.setdefault(observation.metric_id, {})[observation.scope.label] = {
            "numerator": observation.numerator_count,
            "denominator": observation.denominator_count,
        }

    return EvaluationReceipt(
        schema_version=EVALUATION_RECEIPT_SCHEMA_VERSION,
        run_id=run_id,
        result_set_id=result_set_id,
        decision_profile_id=decision_profile_id,
        decision_set_id=manifest.decision_set_id,
        eligibility_set_id=manifest.eligibility_set_id,
        metric_policy_id=policy.policy_id,
        metric_policy_fingerprint=policy.policy_fingerprint,
        metric_set_id=manifest.metric_set_id,
        metric_set_fingerprint=manifest.metric_set_fingerprint,
        metric_source_commit=metric_software.source_revision,
        metric_source_tree_clean=metric_software.source_tree_clean,
        releases=tuple(releases),
        structural_counts=structural_counts,
        metrics=metrics,
        statement=EVALUATION_SCOPE_STATEMENT,
        created_utc=created_utc or _utc_now(),
    )


def build_evaluation_finalization_marker(
    *,
    definition: MetricDerivationDefinition,
    manifest: MetricSetManifest,
    summary: EvaluationSummary,
    markdown: str,
    receipt: EvaluationReceipt,
    decision_finalization_fingerprint: str,
    metric_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> EvaluationFinalizationMarker:
    """Build the last-written authority over an already verified evaluation."""
    if not metric_software.is_research_grade:
        raise EvaluationFinalizationError(
            "evaluation finalization requires a committed, clean metric-engine "
            "revision"
        )
    if receipt.metric_set_fingerprint != manifest.metric_set_fingerprint:
        raise EvaluationFinalizationError(
            "the receipt and metric set name different metric sets"
        )
    if receipt.metric_source_commit != metric_software.source_revision:
        raise EvaluationFinalizationError(
            "the receipt and metric software name different source revisions"
        )
    if summary.metric_set_id != manifest.metric_set_id:
        raise EvaluationFinalizationError(
            "the summary and metric set name different metric sets"
        )

    claims = {
        "schema_version": EVALUATION_FINALIZATION_SCHEMA_VERSION,
        "source_decision_finalization_fingerprint": decision_finalization_fingerprint,
        "metric_definition_fingerprint": definition.definition_fingerprint,
        "metric_set_fingerprint": manifest.metric_set_fingerprint,
        "summary_content_hash": evaluation_summary_content_hash(summary),
        "report_content_hash": report_content_hash(markdown),
        "evaluation_receipt_fingerprint": evaluation_receipt_fingerprint(receipt),
        "evaluation_receipt_content_hash": evaluation_receipt_content_hash(receipt),
        "metric_source_commit": metric_software.source_revision,
        "metric_source_tree_clean": metric_software.source_tree_clean,
    }
    fingerprint = evaluation_finalization_fingerprint(claims)
    return EvaluationFinalizationMarker(
        **claims,
        finalization_id=f"evaluationfinal_{fingerprint[:12]}",
        finalization_fingerprint=fingerprint,
        created_utc=created_utc or _utc_now(),
    )


def write_evaluation_evidence_copies(
    *,
    receipt: EvaluationReceipt,
    markdown: str,
    repository_root: Path,
    directory: Path = EVIDENCE_DIRECTORY,
) -> tuple[Path, Path]:
    """Write the committable copies, byte-identically or not at all.

    Two files: the machine-readable receipt and the human-readable report, named
    after the metric set so that two evaluations of the same run cannot collide.
    Line endings are normalised to the platform's, matching ``write_json`` and
    the workspace report, so the committed copies are byte-identical to the
    verified ones (spec section 84).

    Exclusive creation, and no regenerate-and-replace: existing identical bytes
    are a no-op and existing different bytes are a conflict.
    """
    root = Path(repository_root) / directory
    json_path = root / f"{receipt.metric_set_id}.json"
    markdown_path = root / f"{receipt.metric_set_id}.md"

    rendered = (
        json.dumps(to_plain(receipt), indent=2, ensure_ascii=False, sort_keys=False)
        + "\n"
    )
    _write_exclusively(json_path, rendered)
    _write_exclusively(markdown_path, markdown)
    return json_path, markdown_path


def _write_exclusively(path: Path, text: str) -> Path:
    payload = text.replace("\n", os.linesep).encode("utf-8")
    if path.is_file():
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} already contains different evaluation evidence; refusing "
                "to replace it"
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} appeared with different evaluation evidence; refusing to "
                "overwrite it"
            ) from None
    return path


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
