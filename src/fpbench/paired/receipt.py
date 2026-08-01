"""The two files a paired comparison publishes, and what they may not contain.

A paired receipt is the artefact most likely to be read by someone who has
neither workspace. It may carry identities, the control audit's counts, the
aggregate transition counts and the paired rates as integer pairs.

It may not carry a pair id, a job id, a subject, a finger, an image id, a
filename, a path, a raw score, a per-pair delta or a template. Some of those are
dataset inventory, and the rest are the raw material of exactly the per-pair
narrative this stage refuses to tell (spec section 65).

:func:`require_sanitised_paired_receipt` checks that rather than trusting the
builder, for the same reason the preparation receipt does: the failure mode is
somebody adding a helpful field to make debugging easier, and committing it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from fpbench.core.errors import PairedEvaluationError, ResultConflictError
from fpbench.core.paired_models import (
    NO_SUPERIORITY_STATEMENT,
    PAIRED_EVALUATION_ID_LENGTH,
    PAIRED_SCHEMA_VERSION,
    NativeCanonicalControlAudit,
    PairedEvaluationManifest,
    PairedEvaluationReceipt,
    PairedFinalizationMarker,
    PairedRateObservation,
    TransitionCountRecord,
    paired_finalization_fingerprint,
    paired_receipt_content_hash,
    paired_receipt_fingerprint,
)
from fpbench.core.serialization import to_plain

__all__ = [
    "EVIDENCE_DIRECTORY",
    "FORBIDDEN_RECEIPT_KEYS",
    "build_paired_receipt",
    "build_paired_finalization_marker",
    "require_sanitised_paired_receipt",
    "verify_paired_receipt",
    "write_paired_evidence_copies",
]

EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-native-vs-canonical500"

#: Field names a paired receipt may never carry.
FORBIDDEN_RECEIPT_KEYS: frozenset[str] = frozenset(
    {
        "pair_id",
        "pair_ids",
        "job_id",
        "job_ids",
        "subject_id",
        "subject_ids",
        "finger_id",
        "finger_ids",
        "image_id",
        "image_ids",
        "filename",
        "filenames",
        "path",
        "paths",
        "relative_path",
        "raw_score",
        "raw_scores",
        "score",
        "scores",
        "score_delta",
        "score_deltas",
        "score_delta_decimal",
        "template",
        "templates",
        "records",
        "entries",
    }
)

#: Substrings that would mean an SD300 image or pair id had leaked in.
_ID_MARKERS = ("_plain_", "_roll_", "sd300a_", "sd300b_", "sd300c_")


def build_paired_receipt(
    *,
    manifest: PairedEvaluationManifest,
    policy_id: str,
    policy_fingerprint: str,
    native_ids: Mapping[str, str],
    canonical_ids: Mapping[str, str],
    canonical_preparation_set_id: str,
    pair_manifest_hash: str,
    control: NativeCanonicalControlAudit,
    counts: Sequence[TransitionCountRecord],
    observations: Sequence[PairedRateObservation],
    source_commit: str,
    source_tree_clean: bool,
    created_utc: str | None = None,
) -> PairedEvaluationReceipt:
    """Derive the sanitised receipt for a finished, verified comparison."""
    transition_counts = {
        f"{record.family}.{record.scope.label}": dict(record.counts)
        for record in counts
    }
    rate_observations = {
        f"{observation.observation_id}.{observation.scope.label}": {
            "native": f"{observation.native_numerator}/"
            f"{observation.native_denominator}",
            "canonical": f"{observation.canonical_numerator}/"
            f"{observation.canonical_denominator}",
            "difference": (
                f"{observation.difference_numerator}/"
                f"{observation.difference_denominator}"
                if observation.has_difference
                else "not_comparable"
            ),
            "comparability": observation.comparability.value,
        }
        for observation in observations
    }

    receipt = PairedEvaluationReceipt(
        schema_version=PAIRED_SCHEMA_VERSION,
        paired_evaluation_id=manifest.paired_evaluation_id,
        paired_evaluation_fingerprint=manifest.paired_evaluation_fingerprint,
        definition_fingerprint=manifest.definition_fingerprint,
        policy_id=policy_id,
        policy_fingerprint=policy_fingerprint,
        native_run_id=native_ids["run_id"],
        native_result_set_id=native_ids["result_set_id"],
        native_decision_set_id=native_ids["decision_set_id"],
        native_eligibility_set_id=native_ids["eligibility_set_id"],
        native_metric_set_id=native_ids["metric_set_id"],
        canonical_run_id=canonical_ids["run_id"],
        canonical_result_set_id=canonical_ids["result_set_id"],
        canonical_decision_set_id=canonical_ids["decision_set_id"],
        canonical_eligibility_set_id=canonical_ids["eligibility_set_id"],
        canonical_metric_set_id=canonical_ids["metric_set_id"],
        canonical_preparation_set_id=canonical_preparation_set_id,
        pair_manifest_hash=pair_manifest_hash,
        source_commit=source_commit,
        source_tree_clean=source_tree_clean,
        total_paired_comparisons=manifest.total_paired_comparisons,
        total_eligibility_units=manifest.total_eligibility_units,
        total_common_eligible_rows=manifest.total_common_eligible_rows,
        control_audit={
            "planned_sd300a_pairs": control.planned_sd300a_pairs,
            "compared_scores": control.compared_scores,
            "equal_scores": control.equal_scores,
            "equal_result_statuses": control.equal_result_statuses,
            "equal_decisions": control.equal_decisions,
        },
        transition_counts=transition_counts,
        rate_observations=rate_observations,
        statement=NO_SUPERIORITY_STATEMENT,
        created_utc=created_utc or _utc_now(),
    )
    require_sanitised_paired_receipt(receipt)
    return receipt


def require_sanitised_paired_receipt(receipt: PairedEvaluationReceipt) -> None:
    """Refuse a receipt that would publish per-pair detail or dataset inventory.

    Raises:
        PairedEvaluationError: the receipt names a pair, a job, a subject, a
            finger, an image, a file, a score or a per-pair delta.
    """
    payload = to_plain(receipt)
    problems: list[str] = []

    for key in _walk_keys(payload):
        if key.lower() in FORBIDDEN_RECEIPT_KEYS:
            problems.append(f"carries a {key!r} field")

    rendered = json.dumps(payload, ensure_ascii=False).lower()
    for marker in _ID_MARKERS:
        if marker in rendered:
            problems.append(f"contains {marker!r}, which is part of an SD300 id")

    if problems:
        raise PairedEvaluationError(
            "a paired receipt may not publish per-pair detail: "
            + "; ".join(sorted(set(problems)))
        )


def verify_paired_receipt(
    *,
    receipt: PairedEvaluationReceipt,
    manifest: PairedEvaluationManifest,
    policy_id: str,
    policy_fingerprint: str,
    native_ids: Mapping[str, str],
    canonical_ids: Mapping[str, str],
    canonical_preparation_set_id: str,
    pair_manifest_hash: str,
    control: NativeCanonicalControlAudit,
    counts: Sequence[TransitionCountRecord],
    observations: Sequence[PairedRateObservation],
) -> None:
    """Re-derive every load-bearing claim from current evidence.

    The receipt is never its own proof: a forged one can be internally
    self-consistent while contradicting the comparison it summarises.
    """
    expected = build_paired_receipt(
        manifest=manifest,
        policy_id=policy_id,
        policy_fingerprint=policy_fingerprint,
        native_ids=native_ids,
        canonical_ids=canonical_ids,
        canonical_preparation_set_id=canonical_preparation_set_id,
        pair_manifest_hash=pair_manifest_hash,
        control=control,
        counts=counts,
        observations=observations,
        source_commit=receipt.source_commit,
        source_tree_clean=receipt.source_tree_clean,
        created_utc=receipt.created_utc,
    )
    if paired_receipt_fingerprint(receipt) != paired_receipt_fingerprint(expected):
        differing = [
            name
            for name in to_plain(expected)
            if name != "created_utc"
            and to_plain(getattr(receipt, name)) != to_plain(getattr(expected, name))
        ]
        raise PairedEvaluationError(
            "the paired receipt does not match the comparison it claims to "
            f"summarise; disagreeing field(s): {differing[:5]}"
        )
    require_sanitised_paired_receipt(receipt)


def build_paired_finalization_marker(
    *,
    manifest: PairedEvaluationManifest,
    control: NativeCanonicalControlAudit,
    summary_content_hash: str,
    report_content_hash: str,
    receipt: PairedEvaluationReceipt,
    source_commit: str,
    source_tree_clean: bool,
    created_utc: str | None = None,
) -> PairedFinalizationMarker:
    """Build the last-written authority over an already verified comparison."""
    if not source_tree_clean:
        raise PairedEvaluationError(
            "finalising a paired comparison requires a committed, clean source "
            "tree (docs/adr/0017)"
        )
    if not control.is_clean:
        raise PairedEvaluationError(
            "the SD300A control did not reproduce; no paired comparison may be "
            "finalised over it"
        )
    claims = {
        "schema_version": PAIRED_SCHEMA_VERSION,
        "paired_evaluation_id": manifest.paired_evaluation_id,
        "paired_evaluation_fingerprint": manifest.paired_evaluation_fingerprint,
        "definition_fingerprint": manifest.definition_fingerprint,
        "control_audit_fingerprint": control.audit_fingerprint,
        "summary_content_hash": summary_content_hash,
        "report_content_hash": report_content_hash,
        "receipt_fingerprint": paired_receipt_fingerprint(receipt),
        "receipt_content_hash": paired_receipt_content_hash(receipt),
        "source_commit": source_commit,
        "source_tree_clean": source_tree_clean,
    }
    fingerprint = paired_finalization_fingerprint(claims)
    return PairedFinalizationMarker(
        **claims,
        finalization_id=f"pairedfinal_{fingerprint[:PAIRED_EVALUATION_ID_LENGTH]}",
        finalization_fingerprint=fingerprint,
        created_utc=created_utc or _utc_now(),
    )


def write_paired_evidence_copies(
    *,
    receipt: PairedEvaluationReceipt,
    markdown: str,
    repository_root: Path,
    directory: Path = EVIDENCE_DIRECTORY,
) -> tuple[Path, Path]:
    """Write the committable copies, byte-identically or not at all."""
    require_sanitised_paired_receipt(receipt)
    root = Path(repository_root) / directory
    json_path = root / f"{receipt.paired_evaluation_id}.json"
    markdown_path = root / f"{receipt.paired_evaluation_id}.md"

    rendered = (
        json.dumps(to_plain(receipt), indent=2, ensure_ascii=False, sort_keys=False)
        + "\n"
    )
    _write_once(json_path, rendered.replace("\n", os.linesep).encode("utf-8"))
    _write_once(markdown_path, markdown.replace("\n", os.linesep).encode("utf-8"))
    return json_path, markdown_path


def _write_once(path: Path, payload: bytes) -> Path:
    if path.is_file():
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} already contains different committed evidence; refusing to "
                "overwrite it"
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:  # pragma: no cover - lost a race
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} appeared with different content; refusing to overwrite it"
            )
    return path


def _walk_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_keys(item)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
