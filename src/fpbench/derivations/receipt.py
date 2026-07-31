"""Assembling and re-checking the two files that close a derivation.

The receipt is the one artefact of stage 5A meant to leave the workspace, so it
is built the same way stage 4B's was: every field derived from something already
verified, the whole document run through a sanitiser before it can be written,
and a verifier that re-derives each claim rather than trusting the file to
describe itself.

The marker comes after, and only after everything else has been read back. Its
job is narrow and important: without it, a directory containing a profile,
decisions, eligibility, three views and a receipt is *retryable work in
progress*, not a finished derivation (docs/adr/0020).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionSetManifest
from fpbench.core.derivation_models import (
    DERIVATION_FINALIZATION_SCHEMA_VERSION,
    DERIVATION_RECEIPT_SCHEMA_VERSION,
    NO_METRIC_STATEMENT,
    DecisionDerivationFinalizationMarker,
    DecisionDerivationReceipt,
    DerivationDefinition,
    derivation_finalization_fingerprint,
    derivation_receipt_content_hash,
    derivation_receipt_fingerprint,
)
from fpbench.core.eligibility_models import SelfEligibilityManifest
from fpbench.core.errors import DecisionFinalizationError, ResultConflictError
from fpbench.core.evaluation_view_models import EvaluationViewManifest
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetManifest
from fpbench.core.serialization import to_plain

__all__ = [
    "EVIDENCE_DIRECTORY",
    "build_derivation_receipt",
    "verify_derivation_receipt",
    "build_derivation_finalization_marker",
    "verify_derivation_finalization_marker",
    "write_derivation_evidence_copy",
]

#: One committed file per decision set, so two thresholds over the same run
#: never overwrite each other's evidence.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-native-decisions"


def build_derivation_receipt(
    *,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest,
    unconditional_view: EvaluationViewManifest,
    conditional_view: EvaluationViewManifest,
    non_mated_view: EvaluationViewManifest,
    derivation_software: SoftwareProvenance,
    pair_manifest_hash: str,
    created_utc: str | None = None,
) -> DecisionDerivationReceipt:
    """Derive the sanitised receipt for a complete, verified derivation.

    Raises:
        DecisionFinalizationError: the links do not agree with one another.
    """
    _require_chain(
        run=run,
        result_set=result_set,
        decision_set=decision_set,
        eligibility=eligibility,
        views=(unconditional_view, conditional_view, non_mated_view),
        pair_manifest_hash=pair_manifest_hash,
    )
    if not derivation_software.is_research_grade:
        raise DecisionFinalizationError(
            "a derivation receipt needs a committed, clean source revision "
            "(docs/adr/0017)"
        )
    _require_software_matches_decision_set(
        derivation_software=derivation_software,
        decision_set=decision_set,
    )

    return DecisionDerivationReceipt(
        schema_version=DERIVATION_RECEIPT_SCHEMA_VERSION,
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        result_set_id=result_set.result_set_id,
        result_set_fingerprint=result_set.result_set_fingerprint,
        pair_manifest_hash=pair_manifest_hash,
        decision_profile_id=decision_set.decision_profile_id,
        decision_profile_fingerprint=decision_set.decision_profile_fingerprint,
        decision_set_id=decision_set.decision_set_id,
        decision_set_fingerprint=decision_set.decision_set_fingerprint,
        eligibility_set_id=eligibility.eligibility_set_id,
        eligibility_set_fingerprint=eligibility.eligibility_set_fingerprint,
        unconditional_view_id=unconditional_view.view_id,
        unconditional_view_fingerprint=unconditional_view.view_fingerprint,
        conditional_view_id=conditional_view.view_id,
        conditional_view_fingerprint=conditional_view.view_fingerprint,
        non_mated_view_id=non_mated_view.view_id,
        non_mated_view_fingerprint=non_mated_view.view_fingerprint,
        derivation_source_commit=derivation_software.source_revision,
        derivation_source_tree_clean=derivation_software.source_tree_clean,
        total_decisions=decision_set.total_decisions,
        decided_count=decision_set.decided_count,
        undecidable_count=decision_set.undecidable_count,
        total_eligibility_units=eligibility.total_units,
        view_total_rows={
            unconditional_view.view_kind: unconditional_view.total_rows,
            conditional_view.view_kind: conditional_view.total_rows,
            non_mated_view.view_kind: non_mated_view.total_rows,
        },
        statement=NO_METRIC_STATEMENT,
        created_utc=created_utc or _utc_now(),
    )


def verify_derivation_receipt(
    *,
    receipt: DecisionDerivationReceipt,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest,
    unconditional_view: EvaluationViewManifest,
    conditional_view: EvaluationViewManifest,
    non_mated_view: EvaluationViewManifest,
    pair_manifest_hash: str,
    definition: DerivationDefinition,
) -> None:
    """Re-derive every load-bearing receipt claim from the current artefacts.

    Deliberately field by field rather than by comparing fingerprints: a forged
    receipt can be perfectly self-consistent while describing a derivation that
    is not the one on disk.
    """
    expected: Mapping[str, object] = {
        "schema_version": DERIVATION_RECEIPT_SCHEMA_VERSION,
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "result_set_id": result_set.result_set_id,
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "pair_manifest_hash": pair_manifest_hash,
        "decision_profile_id": decision_set.decision_profile_id,
        "decision_profile_fingerprint": decision_set.decision_profile_fingerprint,
        "decision_set_id": decision_set.decision_set_id,
        "decision_set_fingerprint": decision_set.decision_set_fingerprint,
        "eligibility_set_id": eligibility.eligibility_set_id,
        "eligibility_set_fingerprint": eligibility.eligibility_set_fingerprint,
        "unconditional_view_id": unconditional_view.view_id,
        "unconditional_view_fingerprint": unconditional_view.view_fingerprint,
        "conditional_view_id": conditional_view.view_id,
        "conditional_view_fingerprint": conditional_view.view_fingerprint,
        "non_mated_view_id": non_mated_view.view_id,
        "non_mated_view_fingerprint": non_mated_view.view_fingerprint,
        "total_decisions": decision_set.total_decisions,
        "decided_count": decision_set.decided_count,
        "undecidable_count": decision_set.undecidable_count,
        "total_eligibility_units": eligibility.total_units,
        "derivation_source_commit": definition.derivation_source_commit,
        "derivation_source_tree_clean": True,
    }
    for name, value in expected.items():
        actual = getattr(receipt, name)
        if actual != value:
            raise DecisionFinalizationError(
                f"derivation receipt field {name} is {actual!r}, expected {value!r}"
            )

    _require_definition_matches_decision_set(
        definition=definition, decision_set=decision_set
    )

    rows = {
        unconditional_view.view_kind: unconditional_view.total_rows,
        conditional_view.view_kind: conditional_view.total_rows,
        non_mated_view.view_kind: non_mated_view.total_rows,
    }
    if dict(receipt.view_total_rows) != rows:
        raise DecisionFinalizationError(
            f"derivation receipt view row counts are {dict(receipt.view_total_rows)}, "
            f"expected {rows}"
        )
    if receipt.statement != NO_METRIC_STATEMENT:
        raise DecisionFinalizationError(
            "the derivation receipt no longer states that it carries no metric"
        )


def build_derivation_finalization_marker(
    *,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest,
    unconditional_view: EvaluationViewManifest,
    conditional_view: EvaluationViewManifest,
    non_mated_view: EvaluationViewManifest,
    receipt: DecisionDerivationReceipt,
    derivation_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> DecisionDerivationFinalizationMarker:
    """Build the last-written authority over an already verified chain."""
    if not derivation_software.is_research_grade:
        raise DecisionFinalizationError(
            "derivation finalization requires a committed, clean source revision"
        )
    _require_software_matches_decision_set(
        derivation_software=derivation_software,
        decision_set=decision_set,
    )
    if receipt.derivation_source_commit != decision_set.derivation_source_revision:
        raise DecisionFinalizationError(
            "the receipt and decision set name different derivation commits"
        )
    claims = {
        "schema_version": DERIVATION_FINALIZATION_SCHEMA_VERSION,
        "run_id": run.run_id,
        "source_result_set_fingerprint": result_set.result_set_fingerprint,
        "decision_profile_fingerprint": decision_set.decision_profile_fingerprint,
        "decision_set_fingerprint": decision_set.decision_set_fingerprint,
        "eligibility_set_fingerprint": eligibility.eligibility_set_fingerprint,
        "unconditional_view_fingerprint": unconditional_view.view_fingerprint,
        "conditional_view_fingerprint": conditional_view.view_fingerprint,
        "non_mated_view_fingerprint": non_mated_view.view_fingerprint,
        "derivation_receipt_fingerprint": derivation_receipt_fingerprint(receipt),
        "derivation_receipt_content_hash": derivation_receipt_content_hash(receipt),
        "derivation_source_commit": derivation_software.source_revision,
        "derivation_source_tree_clean": derivation_software.source_tree_clean,
    }
    fingerprint = derivation_finalization_fingerprint(claims)
    return DecisionDerivationFinalizationMarker(
        **claims,
        finalization_id=f"derivationfinal_{fingerprint[:12]}",
        finalization_fingerprint=fingerprint,
        created_utc=created_utc or _utc_now(),
    )


def verify_derivation_finalization_marker(
    *,
    marker: DecisionDerivationFinalizationMarker,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest,
    unconditional_view: EvaluationViewManifest,
    conditional_view: EvaluationViewManifest,
    non_mated_view: EvaluationViewManifest,
    receipt: DecisionDerivationReceipt,
    definition: DerivationDefinition,
) -> None:
    """Confirm the marker still names every current durable artefact."""
    expected = {
        "run_id": run.run_id,
        "source_result_set_fingerprint": result_set.result_set_fingerprint,
        "decision_profile_fingerprint": decision_set.decision_profile_fingerprint,
        "decision_set_fingerprint": decision_set.decision_set_fingerprint,
        "eligibility_set_fingerprint": eligibility.eligibility_set_fingerprint,
        "unconditional_view_fingerprint": unconditional_view.view_fingerprint,
        "conditional_view_fingerprint": conditional_view.view_fingerprint,
        "non_mated_view_fingerprint": non_mated_view.view_fingerprint,
        "derivation_receipt_fingerprint": derivation_receipt_fingerprint(receipt),
        "derivation_receipt_content_hash": derivation_receipt_content_hash(receipt),
        "derivation_source_commit": definition.derivation_source_commit,
        "derivation_source_tree_clean": True,
    }
    for name, value in expected.items():
        actual = getattr(marker, name)
        if actual != value:
            raise DecisionFinalizationError(
                f"derivation finalization field {name} is {actual!r}, expected "
                f"{value!r}"
            )
    _require_definition_matches_decision_set(
        definition=definition, decision_set=decision_set
    )
    if receipt.derivation_source_commit != definition.derivation_source_commit:
        raise DecisionFinalizationError(
            "the receipt and definition name different derivation commits"
        )


def write_derivation_evidence_copy(
    receipt: DecisionDerivationReceipt,
    *,
    repository_root: Path,
    directory: Path = EVIDENCE_DIRECTORY,
) -> Path:
    """Write the committable copy, byte-identically or not at all.

    Line endings are normalised to the platform's, matching ``write_json``, so
    that a copy checked out by git on another platform is recognised as the same
    evidence rather than as a conflicting one.
    """
    path = Path(repository_root) / directory / f"{receipt.decision_set_id}.json"
    rendered = (
        json.dumps(to_plain(receipt), indent=2, ensure_ascii=False, sort_keys=False)
        + "\n"
    )
    payload = rendered.replace("\n", os.linesep).encode("utf-8")
    if path.is_file():
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} already contains different derivation evidence; refusing to "
                "replace it"
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} appeared with different derivation evidence; refusing "
                "to overwrite it"
            )
    return path


# ----------------------------------------------------------------- internals


def _require_chain(
    *,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest,
    views: Sequence[EvaluationViewManifest],
    pair_manifest_hash: str,
) -> None:
    checks: list[tuple[str, object, object]] = [
        ("result set run", result_set.run_id, run.run_id),
        ("result set run fingerprint", result_set.run_fingerprint, run.run_fingerprint),
        ("decision set run", decision_set.run_id, run.run_id),
        (
            "decision set result set",
            decision_set.result_set_fingerprint,
            result_set.result_set_fingerprint,
        ),
        ("eligibility run", eligibility.run_id, run.run_id),
        (
            "eligibility decision set",
            eligibility.decision_set_fingerprint,
            decision_set.decision_set_fingerprint,
        ),
        (
            "eligibility pair manifest",
            eligibility.pair_manifest_hash,
            pair_manifest_hash,
        ),
    ]
    for index, view in enumerate(views):
        checks.append(
            (
                f"view {index} decision set",
                view.decision_set_fingerprint,
                decision_set.decision_set_fingerprint,
            )
        )
        checks.append(
            (f"view {index} run", view.run_fingerprint, run.run_fingerprint)
        )
    for label, actual, expected in checks:
        if actual != expected:
            raise DecisionFinalizationError(
                f"a derivation receipt cannot be built: {label} is {actual!r}, "
                f"expected {expected!r}"
            )


def _require_software_matches_decision_set(
    *,
    derivation_software: SoftwareProvenance,
    decision_set: DecisionSetManifest,
) -> None:
    if derivation_software.source_revision != decision_set.derivation_source_revision:
        raise DecisionFinalizationError(
            "the derivation software and decision set name different source revisions"
        )
    fingerprint = software_provenance_fingerprint(derivation_software)
    if fingerprint != decision_set.derivation_software_fingerprint:
        raise DecisionFinalizationError(
            "the derivation software does not fingerprint to the decision-set "
            "software identity"
        )


def _require_definition_matches_decision_set(
    *, definition: DerivationDefinition, decision_set: DecisionSetManifest
) -> None:
    if definition.derivation_source_commit != decision_set.derivation_source_revision:
        raise DecisionFinalizationError(
            "the derivation definition and decision set name different source revisions"
        )
    fingerprint = software_provenance_fingerprint(definition.derivation_software)
    if fingerprint != definition.derivation_software_fingerprint:
        raise DecisionFinalizationError(
            "the derivation definition's software fingerprint is invalid"
        )
    if fingerprint != decision_set.derivation_software_fingerprint:
        raise DecisionFinalizationError(
            "the derivation definition and decision set name different software"
        )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
