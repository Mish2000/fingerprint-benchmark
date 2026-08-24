"""Where SELF eligibility lives: beneath the decision set that produced it.

    results/<run_id>/decisions/<decision_set_id>/self-eligibility/
    ├── entries.parquet   one row per release/subject/finger
    └── manifest.json     the identity

The path is the argument. Eligibility could plausibly have been filed beneath
the *run*, next to the results — it is, after all, a fact about fingers. It is
not: it is a fact about fingers *under one threshold*, and the same finger can
change status when the threshold does. Filing it beneath the decision set makes
that impossible to forget and impossible to mis-join (docs/adr/0023).

Immutable, atomic, and no overwrite, on the same terms as everything else.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.eligibility_models import (
    ELIGIBILITY_SCHEMA_VERSION,
    SelfEligibilityDecisionRecord,
    SelfEligibilityManifest,
    eligibility_set_fingerprint,
)
from fpbench.core.errors import DecisionSetConflictError, StorageError
from fpbench.core.serialization import read_json
from fpbench.storage import derivation_schemas, layout
from fpbench.storage.atomic_parquet import replace_table
from fpbench.storage.set_publication import publish_set, table_body

__all__ = ["EligibilitySetStore"]

_MANIFEST = "manifest.json"
_ENTRIES = "entries.parquet"


class EligibilitySetStore:
    """Immutable storage for one eligibility set per decision set."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    def eligibility_dir(self, run_id: str, decision_set_id: str) -> Path:
        return layout.eligibility_directory(self.root, run_id, decision_set_id)

    def manifest_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.eligibility_dir(run_id, decision_set_id) / _MANIFEST

    def entries_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.eligibility_dir(run_id, decision_set_id) / _ENTRIES

    def has_eligibility_set(self, run_id: str, decision_set_id: str) -> bool:
        return self.manifest_path(run_id, decision_set_id).is_file()

    # ------------------------------------------------------------------ write

    def ensure_eligibility_set(
        self,
        *,
        decision_set_id: str,
        manifest: SelfEligibilityManifest,
        records: tuple[SelfEligibilityDecisionRecord, ...],
    ) -> Path:
        """Store the set, or confirm the stored one is already it."""
        records = tuple(records)
        self._require_coherent(manifest=manifest, records=records)

        manifest_path = self.manifest_path(manifest.run_id, decision_set_id)

        # The manifest is the claim and goes first, so two writers cannot both
        # replace the entries and leave one writer's manifest standing over the
        # other writer's rows (docs/adr/0139).
        def conflict(stored: str) -> BaseException:
            return DecisionSetConflictError(
                f"decision set {decision_set_id} already holds eligibility set "
                f"{stored[:12]}...; refusing to replace it with "
                f"{manifest.eligibility_set_id}"
            )

        publish_set(
            manifest_path=manifest_path,
            manifest=manifest,
            fingerprint=manifest.eligibility_set_fingerprint,
            stored_fingerprint=lambda: self.read_manifest(
                manifest.run_id, decision_set_id
            ).eligibility_set_fingerprint,
            bodies=(
                table_body(
                    path=self.entries_path(manifest.run_id, decision_set_id),
                    expected=lambda: self._entries_table(
                        decision_set_id, manifest, records
                    ),
                    what="eligibility entries",
                    error=DecisionSetConflictError,
                ),
            ),
            verify_whole_set=lambda: self.read_eligibility_set(
                manifest.run_id, decision_set_id
            ),
            conflict=conflict,
        )
        return manifest_path.parent

    # ------------------------------------------------------------------- read

    def read_manifest(
        self, run_id: str, decision_set_id: str
    ) -> SelfEligibilityManifest:
        path = self.manifest_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"eligibility manifest not found: {path}")
        payload = read_json(path)
        try:
            return SelfEligibilityManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable eligibility manifest ({exc})"
            ) from exc

    def read_records(
        self, run_id: str, decision_set_id: str
    ) -> tuple[SelfEligibilityDecisionRecord, ...]:
        path = self.entries_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"eligibility entries not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                table = reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        try:
            return tuple(derivation_schemas.table_to_eligibility(table))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable eligibility entries ({exc})"
            ) from exc

    def read_eligibility_set(
        self, run_id: str, decision_set_id: str
    ) -> tuple[SelfEligibilityManifest, tuple[SelfEligibilityDecisionRecord, ...]]:
        manifest = self.read_manifest(run_id, decision_set_id)
        records = self.read_records(run_id, decision_set_id)
        self._require_coherent(manifest=manifest, records=records)
        return manifest, records

    # --------------------------------------------------------------- internal

    def _require_coherent(
        self,
        *,
        manifest: SelfEligibilityManifest,
        records: tuple[SelfEligibilityDecisionRecord, ...],
    ) -> None:
        from fpbench.core.eligibility_models import ordered_units_hash

        if not records:
            raise StorageError("an eligibility set with no units is not one")
        if len(records) != manifest.total_units:
            raise StorageError(
                f"eligibility set declares {manifest.total_units} units but carries "
                f"{len(records)}"
            )
        if [record.ordinal for record in records] != list(range(len(records))):
            raise StorageError(
                "eligibility ordinals must be 0..n-1 with no gaps and no repeats"
            )
        unit_ids = [record.eligibility_unit_id for record in records]
        if len(set(unit_ids)) != len(unit_ids):
            raise StorageError("a unit may appear at most once in an eligibility set")
        if ordered_units_hash(records) != manifest.ordered_units_hash:
            raise StorageError(
                "the manifest's ordered units hash does not cover these records"
            )

        # And the identity itself, re-derived. The ordered hash above says the
        # rows are the rows; this says the *name* follows from them. It is the
        # key publish_set decides ownership by, so a declared one that nothing
        # derives lets a set be completed under a manifest describing something
        # else.
        expected = eligibility_set_fingerprint(
            result_set_fingerprint=manifest.result_set_fingerprint,
            decision_set_fingerprint=manifest.decision_set_fingerprint,
            decision_profile_fingerprint=manifest.decision_profile_fingerprint,
            pair_manifest_hash=manifest.pair_manifest_hash,
            records=records,
            policy_id=manifest.policy_id,
            policy_version=manifest.policy_version,
        )
        if manifest.eligibility_set_fingerprint != expected:
            raise StorageError(
                "the manifest's eligibility_set_fingerprint is not derived from "
                f"what it describes ({manifest.eligibility_set_fingerprint[:12]}"
                f"... declared, {expected[:12]}... derived)"
            )

    def _entries_table(
        self,
        decision_set_id: str,
        manifest: SelfEligibilityManifest,
        records: tuple[SelfEligibilityDecisionRecord, ...],
    ) -> pa.Table:
        """The entries body this set would store, stamped. Built, never written."""
        from fpbench import __version__

        table = derivation_schemas.eligibility_to_table(records)
        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"schema_version": ELIGIBILITY_SCHEMA_VERSION.encode(),
                b"eligibility_set_id": manifest.eligibility_set_id.encode(),
                b"eligibility_set_fingerprint": (
                    manifest.eligibility_set_fingerprint.encode()
                ),
                b"ordered_units_hash": manifest.ordered_units_hash.encode(),
                b"decision_set_id": decision_set_id.encode(),
                b"decision_set_fingerprint": manifest.decision_set_fingerprint.encode(),
                b"decision_profile_fingerprint": (
                    manifest.decision_profile_fingerprint.encode()
                ),
                b"policy_id": manifest.policy_id.encode(),
                b"policy_version": manifest.policy_version.encode(),
                b"run_id": manifest.run_id.encode(),
                b"row_count": str(len(records)).encode(),
                b"fpbench_version": __version__.encode(),
                b"created_utc": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .encode(),
            }
        )
        return stamped
