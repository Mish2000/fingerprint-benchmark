"""Where a paired comparison lives, and the rules that keep it immutable.

The same contract every other store in this project follows, and it is worth
stating once more because this is the artefact somebody will be most tempted to
regenerate: the same identity with the same content is a no-op, the same
identity with different content is a conflict, nothing is overwritten and
nothing is silently repaired.

**The manifest is the claim.** It is published first, create-if-absent, and only
its owner writes the eight files it describes — definition, policy, the five
tables and the control audit (docs/adr/0139). The old order wrote those eight
first and published the manifest last, which read as caution and was the defect:
two writers with different content both found the manifest absent, both replaced
the body, and one was then refused the manifest, leaving one writer's manifest
standing over the other writer's rows.

The summary, report and receipt come after the manifest, and the finalization
marker last of all; each claims its own name. A crash between the claim and the
body leaves a set that is visibly unfinished and can be finished by the same
fingerprint — never a set that is silently mixed.

The layout, and why a paired comparison is not filed under either run, is in
:mod:`fpbench.storage.layout`.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
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
from fpbench.core.serialization import read_json, stable_hash, to_plain
from fpbench.storage import layout, paired_schemas
from fpbench.storage.immutable_publication import claim_document, claim_text
from fpbench.storage.atomic_parquet import replace_table
from fpbench.storage.set_publication import publish_set

__all__ = [
    "PairedEvaluationStore",
    "PairedSetInputs",
    "paired_summary_content_hash",
    "report_content_hash",
]

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


@dataclass(frozen=True, slots=True)
class PairedSetInputs:
    """Everything one paired comparison is made of, in one argument.

    The nine documents used to be published by nine public methods, called in
    order by one caller. That order *was* the contract — definition, policy,
    five tables, control audit, then the manifest — and nothing enforced it, so
    the body went to disk while the set was still unowned.

    They arrive together now because the manifest cannot be published until they
    have all been checked against it: the manifest's hashes, counts and
    fingerprints describe exactly these objects, and a claim is irreversible.
    """

    definition: PairedEvaluationDefinition
    policy: Mapping[str, object]
    records: tuple[PairedComparisonRecord, ...]
    transitions: tuple[SelfEligibilityTransitionRecord, ...]
    common: tuple[CommonEligibleMatedEntry, ...]
    counts: tuple[TransitionCountRecord, ...]
    observations: tuple[PairedRateObservation, ...]
    control_audit: NativeCanonicalControlAudit
    manifest: PairedEvaluationManifest


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

    def publish_paired_set(self, inputs: PairedSetInputs) -> Path:
        """Publish one whole paired comparison, manifest first. Returns its directory.

        The manifest is the claim over the set (docs/adr/0139). It is published
        create-if-absent *before* a single body file is written, so two writers
        with different content can never leave one writer's manifest standing
        over the other writer's rows.

        Because a claim cannot be taken back, everything is checked against the
        manifest first — the same coherence :meth:`verify_paired_evaluation`
        applies to what is on disk, applied here to what is about to go there.
        Otherwise a mis-derived set would take a name that can only be refused
        from then on, never corrected.
        """
        manifest = inputs.manifest
        paired_id = manifest.paired_evaluation_id
        self._require_coherent(
            manifest=manifest,
            definition=inputs.definition,
            records=inputs.records,
            transitions=inputs.transitions,
            common=inputs.common,
            counts=inputs.counts,
            observations=inputs.observations,
            control_audit=inputs.control_audit,
            where="the paired comparison being published",
        )

        manifest_path = self.manifest_path(paired_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        claim = publish_set(
            manifest_path=manifest_path,
            manifest=manifest,
            body_paths=self._body_paths(paired_id),
            stored_fingerprint=lambda: self.read_manifest(
                paired_id
            ).paired_evaluation_fingerprint,
            fingerprint=manifest.paired_evaluation_fingerprint,
        )

        if claim.write_body:
            self._write_body(paired_id, inputs)

        if not claim.owned:
            stored = self.read_manifest(paired_id)
            if (
                stored.paired_evaluation_fingerprint
                != manifest.paired_evaluation_fingerprint
            ):
                raise PairedEvaluationConflictError(
                    f"{manifest_path} already holds paired comparison "
                    f"{stored.paired_evaluation_id} "
                    f"({stored.paired_evaluation_fingerprint[:12]}...); refusing to "
                    f"replace it with {manifest.paired_evaluation_fingerprint[:12]}..."
                )
        return manifest_path.parent

    def _body_paths(self, paired_id: str) -> tuple[Path, ...]:
        """Every file the manifest describes. All of them, not a representative.

        A crash between two of them leaves a set the retry would otherwise
        declare finished; :func:`~fpbench.storage.set_publication.publish_set`
        can only tell that it stopped half way if it is given the whole list.
        """
        return (
            self.definition_path(paired_id),
            self.policy_path(paired_id),
            self.comparisons_path(paired_id),
            self.eligibility_path(paired_id),
            self.common_eligible_path(paired_id),
            self.counts_path(paired_id),
            self.observations_path(paired_id),
            self.control_audit_path(paired_id),
        )

    def _write_body(self, paired_id: str, inputs: PairedSetInputs) -> None:
        """Write the files the manifest describes. Only a claim holder gets here.

        The three JSON bodies keep claiming their own names rather than being
        replaced. Under the set claim that is not what stops a second writer —
        the manifest already did — but it is still the check that catches a
        *resumed* publication finishing a set with something other than what the
        first writer left, and it costs one create-if-absent call.
        """
        self._claim_definition(paired_id, inputs.definition)
        self._claim_policy(paired_id, inputs.policy)
        self._write_records(paired_id, inputs.records)
        self._write_eligibility_transitions(paired_id, inputs.transitions)
        self._write_common_eligible_view(paired_id, inputs.common)
        self._write_counts(paired_id, inputs.counts)
        self._write_observations(paired_id, inputs.observations)
        self._claim_control_audit(paired_id, inputs.control_audit)

    def _claim_definition(
        self, paired_id: str, definition: PairedEvaluationDefinition
    ) -> Path:
        path = self.definition_path(paired_id)
        if not claim_document(path, definition):
            stored = self.read_definition(paired_id)
            if stored.definition_fingerprint != definition.definition_fingerprint:
                raise PairedEvaluationConflictError(
                    f"{path} already pins a different paired definition"
                )
        return path

    def _claim_policy(self, paired_id: str, policy: Mapping[str, object]) -> Path:
        """Store the policy beside the numbers, not merely a reference to it.

        The config file it was read from lives in a repository that will keep
        changing, and a comparison pointing at "the policy in configs/" would
        silently mean something different after the next edit.
        """
        path = self.policy_path(paired_id)
        if not claim_document(path, dict(policy)):
            stored = self.read_policy(paired_id)
            if to_plain(stored) != to_plain(dict(policy)):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired policy"
                )
        return path

    def _claim_control_audit(
        self, paired_id: str, audit: NativeCanonicalControlAudit
    ) -> Path:
        path = self.control_audit_path(paired_id)
        if not claim_document(path, audit):
            stored = self.read_control_audit(paired_id)
            if stored.audit_fingerprint != audit.audit_fingerprint:
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different control audit"
                )
        return path

    def _write_records(
        self, paired_id: str, records: tuple[PairedComparisonRecord, ...]
    ) -> Path:
        return self._write_parquet(
            self.comparisons_path(paired_id),
            paired_schemas.paired_comparisons_to_table(records),
            paired_id=paired_id,
            row_kind=b"paired_comparisons",
            rows=len(records),
        )

    def _write_eligibility_transitions(
        self, paired_id: str, records: tuple[SelfEligibilityTransitionRecord, ...]
    ) -> Path:
        return self._write_parquet(
            self.eligibility_path(paired_id),
            paired_schemas.eligibility_transitions_to_table(records),
            paired_id=paired_id,
            row_kind=b"eligibility_transitions",
            rows=len(records),
        )

    def _write_common_eligible_view(
        self, paired_id: str, entries: tuple[CommonEligibleMatedEntry, ...]
    ) -> Path:
        return self._write_parquet(
            self.common_eligible_path(paired_id),
            paired_schemas.common_eligible_to_table(entries),
            paired_id=paired_id,
            row_kind=b"common_eligible_mated",
            rows=len(entries),
        )

    def _write_counts(
        self, paired_id: str, records: tuple[TransitionCountRecord, ...]
    ) -> Path:
        return self._write_parquet(
            self.counts_path(paired_id),
            paired_schemas.transition_counts_to_table(records),
            paired_id=paired_id,
            row_kind=b"transition_counts",
            rows=len(records),
        )

    def _write_observations(
        self, paired_id: str, observations: tuple[PairedRateObservation, ...]
    ) -> Path:
        return self._write_parquet(
            self.observations_path(paired_id),
            paired_schemas.paired_observations_to_table(observations),
            paired_id=paired_id,
            row_kind=b"paired_observations",
            rows=len(observations),
        )

    def ensure_summary(
        self, paired_id: str, summary: Mapping[str, object]
    ) -> Path:
        path = self.summary_path(paired_id)
        if not claim_document(path, dict(summary)):
            stored = self.read_summary(paired_id)
            if paired_summary_content_hash(stored) != paired_summary_content_hash(
                summary
            ):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired summary"
                )
        return path

    def ensure_report(self, paired_id: str, markdown: str) -> Path:
        path = self.report_path(paired_id)
        if not claim_text(path, markdown):
            stored = self.read_report(paired_id)
            if report_content_hash(stored) != report_content_hash(markdown):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired report"
                )
        return path

    def ensure_receipt(
        self, paired_id: str, receipt: PairedEvaluationReceipt
    ) -> Path:
        path = self.receipt_path(paired_id)
        if not claim_document(path, receipt):
            stored = self.read_receipt(paired_id)
            if paired_receipt_fingerprint(stored) != paired_receipt_fingerprint(
                receipt
            ):
                raise PairedEvaluationConflictError(
                    f"{path} already carries a different paired receipt"
                )
        return path

    def ensure_finalization(
        self, paired_id: str, marker: PairedFinalizationMarker
    ) -> Path:
        path = self.finalization_path(paired_id)
        if not claim_document(path, marker):
            stored = self.read_finalization(paired_id)
            if stored.finalization_fingerprint != marker.finalization_fingerprint:
                raise PairedEvaluationConflictError(
                    f"{path} already finalises a different paired comparison"
                )
        return path

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
        self._require_coherent(
            manifest=manifest,
            definition=self.read_definition(paired_id),
            records=self.read_records(paired_id),
            transitions=self.read_eligibility_transitions(paired_id),
            common=self.read_common_eligible_view(paired_id),
            counts=self.read_counts(paired_id),
            observations=self.read_observations(paired_id),
            control_audit=self.read_control_audit(paired_id),
            where=f"the stored paired comparison {paired_id}",
        )
        return manifest

    @staticmethod
    def _require_coherent(
        *,
        manifest: PairedEvaluationManifest,
        definition: PairedEvaluationDefinition,
        records: tuple[PairedComparisonRecord, ...],
        transitions: tuple[SelfEligibilityTransitionRecord, ...],
        common: tuple[CommonEligibleMatedEntry, ...],
        counts: tuple[TransitionCountRecord, ...],
        observations: tuple[PairedRateObservation, ...],
        control_audit: NativeCanonicalControlAudit,
        where: str,
    ) -> None:
        """Everything the manifest says, checked against the rows it says it about.

        One definition of coherence, applied twice: to the objects about to be
        published, before the manifest claims the name, and to the documents read
        back off the disk afterwards. Two copies of these checks would have been
        two chances to disagree about what a whole set is.
        """
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
                    f"{where}: {label} ordinals must be 0..n-1 with no gaps and "
                    "no repeats"
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
                    f"{where}: the manifest's {label} hash does not cover the rows"
                )

        if manifest.total_paired_comparisons != len(records):
            raise StorageError(
                f"{where}: the manifest declares "
                f"{manifest.total_paired_comparisons} paired comparisons but the "
                f"table holds {len(records)}"
            )
        if manifest.total_eligibility_units != len(transitions):
            raise StorageError(
                f"{where}: the manifest declares "
                f"{manifest.total_eligibility_units} eligibility units but the "
                f"table holds {len(transitions)}"
            )
        included = sum(1 for entry in common if entry.included)
        if manifest.total_common_eligible_rows != included:
            raise StorageError(
                f"{where}: the manifest declares "
                f"{manifest.total_common_eligible_rows} common-eligible rows but "
                f"{included} are marked included"
            )

        if control_audit.audit_fingerprint != manifest.control_audit_fingerprint:
            raise StorageError(
                f"{where}: the control audit is not the one the manifest names"
            )
        if definition.definition_fingerprint != manifest.definition_fingerprint:
            raise StorageError(
                f"{where}: the definition is not the one the manifest names"
            )

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
        replace_table(path, stamped, what="paired-evaluation table")
        return path
