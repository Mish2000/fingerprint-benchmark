"""Where a paired comparison lives, and the rules that keep it immutable.

The same contract every other store in this project follows, and it is worth
stating once more because this is the artefact somebody will be most tempted to
regenerate: the same identity with the same content is a no-op, the same
identity with different content is a conflict, nothing is overwritten and
nothing is silently repaired.

**Write order matters.** Definition and policy first, then the five tables, then
the manifest — which is the marker that says the comparison is readable. The
control audit, summary, report and receipt come after, and the finalization
marker last of all. A crash anywhere leaves a visibly unfinished directory
rather than an identity pointing at rows that were never written.

The layout, and why a paired comparison is not filed under either run, is in
:mod:`fpbench.storage.layout`.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.errors import PairedEvaluationConflictError, StorageError
from fpbench.core.paired_models import (
    PAIRED_SCHEMA_VERSION,
    CommonEligibleMatedEntry,
    NativeCanonicalControlAudit,
    PairedComparisonRecord,
    PairedEvaluationDefinition,
    PairedEvaluationManifest,
    PairedEvaluationReceipt,
    PairedFinalizationMarker,
    PairedRateObservation,
    SelfEligibilityTransitionRecord,
    TransitionCountRecord,
    common_eligible_view_hash,
    ordered_eligibility_transitions_hash,
    ordered_paired_observations_hash,
    ordered_paired_records_hash,
    ordered_transition_counts_hash,
    paired_receipt_fingerprint,
)
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.serialization import read_json, stable_hash, to_plain, write_json
from fpbench.storage import layout, paired_schemas

__all__ = ["PairedEvaluationStore", "paired_summary_content_hash", "report_content_hash"]

_DEFINITION = "definition.json"
_POLICY = "policy.json"
_MANIFEST = "manifest.json"
_COMPARISONS = "paired-comparisons.parquet"
_ELIGIBILITY = "eligibility-transitions.parquet"
_COMMON_ELIGIBLE = "common-eligible-mated.parquet"
_COUNTS = "transition-counts.parquet"
_OBSERVATIONS = "observations.parquet"
_CONTROL_AUDIT = "control-audit.json"
_SUMMARY = "summary.json"
_REPORT = "report.md"
_RECEIPT = "receipt.json"
_FINALIZATION = "finalization.json"


def paired_summary_content_hash(summary: Mapping[str, object]) -> str:
    """A digest of a paired summary with its generation time removed."""
    payload = {
        key: value
        for key, value in dict(summary).items()
        if key != "generated_utc"
    }
    return stable_hash(
        {"schema": "paired_summary_content_hash_v1", "summary": to_plain(payload)},
        length=64,
    )


def report_content_hash(markdown: str) -> str:
    """A digest of the exact report text."""
    return stable_hash(
        {"schema": "paired_report_content_hash_v1", "markdown": str(markdown)},
        length=64,
    )


def write_text_atomically(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


class PairedEvaluationStore:
    """Immutable storage for one comparison of two derivation chains."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    @property
    def paired_root(self) -> Path:
        return layout.paired_evaluations_root(self.root)

    def paired_dir(self, paired_id: str) -> Path:
        return layout.paired_evaluation_directory(self.root, paired_id)

    def definition_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _DEFINITION

    def policy_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _POLICY

    def manifest_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _MANIFEST

    def comparisons_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _COMPARISONS

    def eligibility_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _ELIGIBILITY

    def common_eligible_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _COMMON_ELIGIBLE

    def counts_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _COUNTS

    def observations_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _OBSERVATIONS

    def control_audit_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _CONTROL_AUDIT

    def summary_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _SUMMARY

    def report_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _REPORT

    def receipt_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _RECEIPT

    def finalization_path(self, paired_id: str) -> Path:
        return self.paired_dir(paired_id) / _FINALIZATION

    # ---------------------------------------------------------------- presence

    def has_manifest(self, paired_id: str) -> bool:
        return self.manifest_path(paired_id).is_file()

    def has_control_audit(self, paired_id: str) -> bool:
        return self.control_audit_path(paired_id).is_file()

    def has_summary(self, paired_id: str) -> bool:
        return self.summary_path(paired_id).is_file()

    def has_report(self, paired_id: str) -> bool:
        return self.report_path(paired_id).is_file()

    def has_receipt(self, paired_id: str) -> bool:
        return self.receipt_path(paired_id).is_file()

    def has_finalization(self, paired_id: str) -> bool:
        return self.finalization_path(paired_id).is_file()

    def paired_evaluation_ids(self) -> tuple[str, ...]:
        if not self.paired_root.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in self.paired_root.iterdir()
                if (path / _MANIFEST).is_file()
            )
        )

    # ------------------------------------------------------------------- write

    def ensure_definition(
        self, paired_id: str, definition: PairedEvaluationDefinition
    ) -> Path:
        path = self.definition_path(paired_id)
        if path.is_file():
            stored = self.read_definition(paired_id)
            if stored.definition_fingerprint != definition.definition_fingerprint:
                raise PairedEvaluationConflictError(
                    f"{path} already pins a different paired definition"
                )
            return path
        return write_json(path, definition)

    def ensure_policy(self, paired_id: str, policy: Mapping[str, object]) -> Path:
        """Store the policy beside the numbers, not merely a reference to it.

        The config file it was read from lives in a repository that will keep
        changing, and a comparison pointing at "the policy in configs/" would
        silently mean something different after the next edit.
        """
        path = self.policy_path(paired_id)
        if path.is_file():
            stored = self.read_policy(paired_id)
            if to_plain(stored) != to_plain(dict(policy)):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired policy"
                )
            return path
        return write_json(path, dict(policy))

    def ensure_records(
        self, paired_id: str, records: tuple[PairedComparisonRecord, ...]
    ) -> Path:
        return self._write_parquet(
            self.comparisons_path(paired_id),
            paired_schemas.paired_comparisons_to_table(records),
            paired_id=paired_id,
            row_kind=b"paired_comparisons",
            rows=len(records),
        )

    def ensure_eligibility_transitions(
        self, paired_id: str, records: tuple[SelfEligibilityTransitionRecord, ...]
    ) -> Path:
        return self._write_parquet(
            self.eligibility_path(paired_id),
            paired_schemas.eligibility_transitions_to_table(records),
            paired_id=paired_id,
            row_kind=b"eligibility_transitions",
            rows=len(records),
        )

    def ensure_common_eligible_view(
        self, paired_id: str, entries: tuple[CommonEligibleMatedEntry, ...]
    ) -> Path:
        return self._write_parquet(
            self.common_eligible_path(paired_id),
            paired_schemas.common_eligible_to_table(entries),
            paired_id=paired_id,
            row_kind=b"common_eligible_mated",
            rows=len(entries),
        )

    def ensure_counts(
        self, paired_id: str, records: tuple[TransitionCountRecord, ...]
    ) -> Path:
        return self._write_parquet(
            self.counts_path(paired_id),
            paired_schemas.transition_counts_to_table(records),
            paired_id=paired_id,
            row_kind=b"transition_counts",
            rows=len(records),
        )

    def ensure_observations(
        self, paired_id: str, observations: tuple[PairedRateObservation, ...]
    ) -> Path:
        return self._write_parquet(
            self.observations_path(paired_id),
            paired_schemas.paired_observations_to_table(observations),
            paired_id=paired_id,
            row_kind=b"paired_observations",
            rows=len(observations),
        )

    def ensure_control_audit(
        self, paired_id: str, audit: NativeCanonicalControlAudit
    ) -> Path:
        path = self.control_audit_path(paired_id)
        if path.is_file():
            stored = self.read_control_audit(paired_id)
            if stored.audit_fingerprint != audit.audit_fingerprint:
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different control audit"
                )
            return path
        return write_json(path, audit)

    def ensure_manifest(
        self, manifest: PairedEvaluationManifest
    ) -> Path:
        """The marker that says the comparison is readable. Written last of six."""
        path = self.manifest_path(manifest.paired_evaluation_id)
        if path.is_file():
            stored = self.read_manifest(manifest.paired_evaluation_id)
            if (
                stored.paired_evaluation_fingerprint
                != manifest.paired_evaluation_fingerprint
            ):
                raise PairedEvaluationConflictError(
                    f"{path} already holds paired comparison "
                    f"{stored.paired_evaluation_id}; refusing to replace it"
                )
            return path
        return write_json(path, manifest)

    def ensure_summary(
        self, paired_id: str, summary: Mapping[str, object]
    ) -> Path:
        path = self.summary_path(paired_id)
        if path.is_file():
            stored = self.read_summary(paired_id)
            if paired_summary_content_hash(stored) != paired_summary_content_hash(
                summary
            ):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired summary"
                )
            return path
        return write_json(path, dict(summary))

    def ensure_report(self, paired_id: str, markdown: str) -> Path:
        path = self.report_path(paired_id)
        if path.is_file():
            stored = self.read_report(paired_id)
            if report_content_hash(stored) != report_content_hash(markdown):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired report"
                )
            return path
        return write_text_atomically(path, markdown)

    def ensure_receipt(
        self, paired_id: str, receipt: PairedEvaluationReceipt
    ) -> Path:
        path = self.receipt_path(paired_id)
        if path.is_file():
            stored = self.read_receipt(paired_id)
            if paired_receipt_fingerprint(stored) != paired_receipt_fingerprint(
                receipt
            ):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired receipt"
                )
            return path
        return write_json(path, receipt)

    def ensure_finalization(
        self, paired_id: str, marker: PairedFinalizationMarker
    ) -> Path:
        path = self.finalization_path(paired_id)
        if path.is_file():
            stored = self.read_finalization(paired_id)
            if stored.finalization_fingerprint != marker.finalization_fingerprint:
                raise PairedEvaluationConflictError(
                    f"{path} already finalises a different paired comparison"
                )
            return path
        return write_json(path, marker)

    # -------------------------------------------------------------------- read

    def read_definition(self, paired_id: str) -> PairedEvaluationDefinition:
        payload = self._read_json(
            self.definition_path(paired_id), "paired definition"
        )
        try:
            return PairedEvaluationDefinition(
                **{
                    **payload,
                    "derivation_software": SoftwareProvenance(
                        **payload["derivation_software"]
                    ),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"unreadable paired definition ({exc})") from exc

    def read_policy(self, paired_id: str) -> Mapping[str, object]:
        return self._read_json(self.policy_path(paired_id), "paired policy")

    def read_manifest(self, paired_id: str) -> PairedEvaluationManifest:
        path = self.manifest_path(paired_id)
        payload = self._read_json(path, "paired manifest")
        try:
            manifest = PairedEvaluationManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable paired manifest ({exc})") from exc
        if manifest.paired_evaluation_id != paired_id:
            raise StorageError(
                f"{path}: the manifest names {manifest.paired_evaluation_id} but was "
                f"read from {paired_id}"
            )
        return manifest

    def read_records(self, paired_id: str) -> tuple[PairedComparisonRecord, ...]:
        table = self._read_parquet(self.comparisons_path(paired_id), "paired records")
        return tuple(paired_schemas.table_to_paired_comparisons(table))

    def read_eligibility_transitions(
        self, paired_id: str
    ) -> tuple[SelfEligibilityTransitionRecord, ...]:
        table = self._read_parquet(
            self.eligibility_path(paired_id), "eligibility transitions"
        )
        return tuple(paired_schemas.table_to_eligibility_transitions(table))

    def read_common_eligible_view(
        self, paired_id: str
    ) -> tuple[CommonEligibleMatedEntry, ...]:
        table = self._read_parquet(
            self.common_eligible_path(paired_id), "common-eligible view"
        )
        return tuple(paired_schemas.table_to_common_eligible(table))

    def read_counts(self, paired_id: str) -> tuple[TransitionCountRecord, ...]:
        table = self._read_parquet(self.counts_path(paired_id), "transition counts")
        return tuple(paired_schemas.table_to_transition_counts(table))

    def read_observations(self, paired_id: str) -> tuple[PairedRateObservation, ...]:
        table = self._read_parquet(
            self.observations_path(paired_id), "paired observations"
        )
        return tuple(paired_schemas.table_to_paired_observations(table))

    def read_control_audit(self, paired_id: str) -> NativeCanonicalControlAudit:
        payload = self._read_json(
            self.control_audit_path(paired_id), "control audit"
        )
        try:
            return NativeCanonicalControlAudit(
                **{**payload, "issues": tuple(payload.get("issues") or ())}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"unreadable control audit ({exc})") from exc

    def read_summary(self, paired_id: str) -> Mapping[str, object]:
        return self._read_json(self.summary_path(paired_id), "paired summary")

    def read_report(self, paired_id: str) -> str:
        path = self.report_path(paired_id)
        if not path.is_file():
            raise StorageError(f"paired report not found: {path}")
        return path.read_text(encoding="utf-8")

    def read_receipt(self, paired_id: str) -> PairedEvaluationReceipt:
        payload = self._read_json(self.receipt_path(paired_id), "paired receipt")
        try:
            return PairedEvaluationReceipt(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"unreadable paired receipt ({exc})") from exc

    def read_finalization(self, paired_id: str) -> PairedFinalizationMarker:
        payload = self._read_json(
            self.finalization_path(paired_id), "paired finalization marker"
        )
        try:
            return PairedFinalizationMarker(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"unreadable paired finalization marker ({exc})") from exc

    # ------------------------------------------------------------------ verify

    def verify_paired_evaluation(self, paired_id: str) -> PairedEvaluationManifest:
        """Re-read everything and re-check what storage is able to check.

        Ordinals, ordered hashes, and the manifest's own totals. It does **not**
        re-derive the transitions from the two source chains — that needs both
        workspaces' decisions, and it lives in
        :func:`fpbench.paired.verify.verify_paired_evaluation`. A paired
        comparison is not evidence of itself, and neither is this method.
        """
        manifest = self.read_manifest(paired_id)
        records = self.read_records(paired_id)
        transitions = self.read_eligibility_transitions(paired_id)
        common = self.read_common_eligible_view(paired_id)
        counts = self.read_counts(paired_id)
        observations = self.read_observations(paired_id)

        for label, rows in (
            ("paired records", records),
            ("eligibility transitions", transitions),
            ("common-eligible rows", common),
            ("transition counts", counts),
            ("paired observations", observations),
        ):
            ordinals = [row.ordinal for row in rows]
            if ordinals != list(range(len(rows))):
                raise StorageError(
                    f"{label}: ordinals must be 0..n-1 with no gaps and no repeats"
                )

        checks = (
            (
                "ordered paired records",
                ordered_paired_records_hash(records),
                manifest.ordered_paired_records_hash,
            ),
            (
                "ordered eligibility transitions",
                ordered_eligibility_transitions_hash(transitions),
                manifest.ordered_eligibility_transitions_hash,
            ),
            (
                "common-eligible view",
                common_eligible_view_hash(common),
                manifest.common_eligible_view_hash,
            ),
            (
                "ordered transition counts",
                ordered_transition_counts_hash(counts),
                manifest.ordered_count_records_hash,
            ),
            (
                "ordered observations",
                ordered_paired_observations_hash(observations),
                manifest.ordered_observations_hash,
            ),
        )
        for label, actual, expected in checks:
            if actual != expected:
                raise StorageError(
                    f"the manifest's {label} hash does not cover the stored rows"
                )

        if manifest.total_paired_comparisons != len(records):
            raise StorageError(
                f"the manifest declares {manifest.total_paired_comparisons} paired "
                f"comparisons but the table holds {len(records)}"
            )
        if manifest.total_eligibility_units != len(transitions):
            raise StorageError(
                f"the manifest declares {manifest.total_eligibility_units} "
                f"eligibility units but the table holds {len(transitions)}"
            )
        included = sum(1 for entry in common if entry.included)
        if manifest.total_common_eligible_rows != included:
            raise StorageError(
                f"the manifest declares {manifest.total_common_eligible_rows} "
                f"common-eligible rows but {included} are marked included"
            )

        audit = self.read_control_audit(paired_id)
        if audit.audit_fingerprint != manifest.control_audit_fingerprint:
            raise StorageError(
                "the stored control audit is not the one the manifest names"
            )
        definition = self.read_definition(paired_id)
        if definition.definition_fingerprint != manifest.definition_fingerprint:
            raise StorageError(
                "the stored definition is not the one the manifest names"
            )
        return manifest

    # --------------------------------------------------------------- internals

    def _read_json(self, path: Path, what: str):
        if not path.is_file():
            raise StorageError(f"{what} not found: {path}")
        try:
            return read_json(path)
        except (OSError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable {what} ({exc})") from exc

    def _read_parquet(self, path: Path, what: str) -> pa.Table:
        if not path.is_file():
            raise StorageError(f"{what} not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                return reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc

    def _write_parquet(
        self,
        path: Path,
        table: pa.Table,
        *,
        paired_id: str,
        row_kind: bytes,
        rows: int,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"row_kind": row_kind,
                b"schema_version": PAIRED_SCHEMA_VERSION.encode(),
                b"paired_evaluation_id": paired_id.encode(),
                b"row_count": str(rows).encode(),
                b"fpbench_version": __version__.encode(),
                b"created_utc": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .encode(),
            }
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            pq.write_table(stamped, tmp, compression="zstd")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path
