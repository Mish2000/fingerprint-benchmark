"""Where a decision set lives, and the rules that keep it immutable.

Layout, beneath the run whose scores it interprets::

    results/<run_id>/decisions/<decision_set_id>/
    ├── profile.json        the exact threshold that was applied
    ├── decisions.parquet   one row per planned job
    └── manifest.json       the identity

**The profile is stored beside the decisions**, not merely referenced. The
config file it was read from lives in a repository that will keep changing, and
a decision set that pointed at "the profile in configs/" would silently mean
something different after the next edit. The copy here is what the decisions
were actually made under.

**Write order matters**, as everywhere else in this project: profile first, then
the rows, then the manifest. The manifest is the marker that says the set is
complete, so a crash leaves a visibly unfinished directory rather than an
identity pointing at rows that were never written.

**No overwrite.** The same set again is a no-op; a different set under the same
id is a conflict. Since the id is derived from the scores, the profile and the
derivation code, a genuinely different derivation lands in a different directory
and cannot collide (docs/adr/0022).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.decision_models import (
    DECISION_PROFILE_SCHEMA_VERSION,
    DECISION_SET_SCHEMA_VERSION,
    DecisionProfile,
    DecisionRecord,
    DecisionSetManifest,
    ThresholdComparator,
    ThresholdOrigin,
)
from fpbench.core.derivation_models import (
    DecisionDerivationFinalizationMarker,
    DecisionDerivationReceipt,
    derivation_receipt_fingerprint,
)
from fpbench.core.enums import ScoreDirection
from fpbench.core.errors import DecisionSetConflictError, StorageError
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import derivation_schemas, layout

__all__ = ["DecisionSetStore"]

_PROFILE = "profile.json"
_MANIFEST = "manifest.json"
_RECORDS = "decisions.parquet"
_RECEIPT = "derivation-receipt.json"
_FINALIZATION = "derivation-finalization.json"


class DecisionSetStore:
    """Immutable storage for decision sets beneath one run."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    def decisions_root(self, run_id: str) -> Path:
        return layout.decisions_root(self.root, run_id)

    def decision_set_dir(self, run_id: str, decision_set_id: str) -> Path:
        return layout.decision_set_directory(self.root, run_id, decision_set_id)

    def profile_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.decision_set_dir(run_id, decision_set_id) / _PROFILE

    def manifest_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.decision_set_dir(run_id, decision_set_id) / _MANIFEST

    def records_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.decision_set_dir(run_id, decision_set_id) / _RECORDS

    def receipt_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.decision_set_dir(run_id, decision_set_id) / _RECEIPT

    def finalization_path(self, run_id: str, decision_set_id: str) -> Path:
        return self.decision_set_dir(run_id, decision_set_id) / _FINALIZATION

    def has_decision_set(self, run_id: str, decision_set_id: str) -> bool:
        return self.manifest_path(run_id, decision_set_id).is_file()

    def has_receipt(self, run_id: str, decision_set_id: str) -> bool:
        return self.receipt_path(run_id, decision_set_id).is_file()

    def has_finalization(self, run_id: str, decision_set_id: str) -> bool:
        return self.finalization_path(run_id, decision_set_id).is_file()

    def decision_set_ids(self, run_id: str) -> tuple[str, ...]:
        directory = self.decisions_root(run_id)
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in directory.iterdir()
                if (path / _MANIFEST).is_file()
            )
        )

    # ------------------------------------------------------------------ write

    def ensure_decision_set(
        self,
        *,
        profile: DecisionProfile,
        manifest: DecisionSetManifest,
        records: tuple[DecisionRecord, ...],
    ) -> Path:
        """Store the set, or confirm the stored one is already it.

        Raises:
            StorageError: the manifest, profile and records do not describe one
                another.
            DecisionSetConflictError: a different set is already stored here.
        """
        records = tuple(records)
        self._require_coherent(profile=profile, manifest=manifest, records=records)

        run_id = manifest.run_id
        set_id = manifest.decision_set_id
        manifest_path = self.manifest_path(run_id, set_id)

        if manifest_path.is_file():
            stored = self.read_manifest(run_id, set_id)
            if stored.decision_set_fingerprint != manifest.decision_set_fingerprint:
                raise DecisionSetConflictError(
                    f"run {run_id} already holds decision set {stored.decision_set_id} "
                    f"({stored.decision_set_fingerprint[:12]}...); refusing to replace "
                    f"it with {manifest.decision_set_fingerprint[:12]}..."
                )
            return manifest_path.parent

        write_json(self.profile_path(run_id, set_id), profile)
        self._write_records(manifest, records)
        write_json(manifest_path, manifest)
        return manifest_path.parent

    # ------------------------------------------------------------------- read

    def read_profile(self, run_id: str, decision_set_id: str) -> DecisionProfile:
        path = self.profile_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"decision profile not found: {path}")
        payload = read_json(path)
        try:
            return DecisionProfile(
                profile_id=payload["profile_id"],
                profile_fingerprint=payload["profile_fingerprint"],
                display_name=payload["display_name"],
                profile_version=payload["profile_version"],
                algorithm_id=payload["algorithm_id"],
                implementation_version=payload["implementation_version"],
                algorithm_fingerprint=payload["algorithm_fingerprint"],
                score_direction=ScoreDirection(payload["score_direction"]),
                comparator=ThresholdComparator(payload["comparator"]),
                threshold=payload["threshold"],
                origin=ThresholdOrigin(payload["origin"]),
                source_kind=payload["source_kind"],
                source_reference=payload["source_reference"],
                source_version=payload["source_version"],
                allowed_execution_profiles=tuple(
                    payload["allowed_execution_profiles"]
                ),
                calibration_performed=payload["calibration_performed"],
                calibration_manifest_fingerprint=payload[
                    "calibration_manifest_fingerprint"
                ],
                metadata=payload["metadata"],
                # Absent from every profile stored before stage 7D, and absence
                # means schema 1 — which is what those profiles were, and what
                # their published fingerprints were computed under.
                schema_version=payload.get(
                    "schema_version", DECISION_PROFILE_SCHEMA_VERSION
                ),
                # Absent from every profile written before stage 8D, and absent
                # is what a non-calibrated profile carries. Read with ``get`` for
                # the same reason ``schema_version`` is: a stored schema-1 or
                # schema-2 document does not have the keys, and reconstructing it
                # must produce exactly the profile it was written as.
                calibration_operating_point_fingerprint=payload.get(
                    "calibration_operating_point_fingerprint"
                ),
                calibration_protocol_fingerprint=payload.get(
                    "calibration_protocol_fingerprint"
                ),
                calibration_source_binding_fingerprint=payload.get(
                    "calibration_source_binding_fingerprint"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable decision profile ({exc})") from exc

    def read_manifest(self, run_id: str, decision_set_id: str) -> DecisionSetManifest:
        path = self.manifest_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"decision-set manifest not found: {path}")
        payload = read_json(path)
        try:
            return DecisionSetManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable decision-set manifest ({exc})"
            ) from exc

    def read_records(
        self, run_id: str, decision_set_id: str
    ) -> tuple[DecisionRecord, ...]:
        path = self.records_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"decision records not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                table = reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        try:
            return tuple(derivation_schemas.table_to_decisions(table))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable decision records ({exc})") from exc

    def read_decision_set(
        self, run_id: str, decision_set_id: str
    ) -> tuple[DecisionProfile, DecisionSetManifest, tuple[DecisionRecord, ...]]:
        """Read all three parts and confirm they describe one another."""
        profile = self.read_profile(run_id, decision_set_id)
        manifest = self.read_manifest(run_id, decision_set_id)
        records = self.read_records(run_id, decision_set_id)
        self._require_coherent(profile=profile, manifest=manifest, records=records)
        return profile, manifest, records

    # -------------------------------------------------- receipt and marker

    def ensure_receipt(
        self, *, decision_set_id: str, receipt: DecisionDerivationReceipt
    ) -> Path:
        """Write the sanitised receipt once, or confirm the stored one matches.

        Compared on the *semantic* fingerprint, which excludes ``created_utc``.
        Re-running a finalisation must be a no-op, and a receipt that differed
        only in when it was written would otherwise conflict with itself. The
        stronger content hash — timestamp included — is what the finalization
        marker binds, and it binds the bytes actually stored here.
        """
        path = self.receipt_path(receipt.run_id, decision_set_id)
        if path.is_file():
            stored = self.read_receipt(receipt.run_id, decision_set_id)
            if derivation_receipt_fingerprint(
                stored
            ) != derivation_receipt_fingerprint(receipt):
                raise DecisionSetConflictError(
                    f"{path} already carries a different derivation receipt"
                )
            return path
        return write_json(path, receipt)

    def read_receipt(
        self, run_id: str, decision_set_id: str
    ) -> DecisionDerivationReceipt:
        path = self.receipt_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"derivation receipt not found: {path}")
        payload = read_json(path)
        try:
            return DecisionDerivationReceipt(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable derivation receipt ({exc})"
            ) from exc

    def ensure_finalization(
        self,
        *,
        run_id: str,
        decision_set_id: str,
        marker: DecisionDerivationFinalizationMarker,
    ) -> Path:
        """Write the last file, the one that makes the rest authoritative."""
        path = self.finalization_path(run_id, decision_set_id)
        if path.is_file():
            stored = self.read_finalization(run_id, decision_set_id)
            if stored.finalization_fingerprint != marker.finalization_fingerprint:
                raise DecisionSetConflictError(
                    f"{path} already finalises a different derivation chain"
                )
            return path
        return write_json(path, marker)

    def read_finalization(
        self, run_id: str, decision_set_id: str
    ) -> DecisionDerivationFinalizationMarker:
        path = self.finalization_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"derivation finalization marker not found: {path}")
        payload = read_json(path)
        try:
            return DecisionDerivationFinalizationMarker(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable derivation finalization marker ({exc})"
            ) from exc

    def record_metadata(self, run_id: str, decision_set_id: str) -> Mapping[str, str]:
        path = self.records_path(run_id, decision_set_id)
        if not path.is_file():
            raise StorageError(f"decision records not found: {path}")
        try:
            metadata = pq.read_schema(path).metadata or {}
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        return {key.decode(): value.decode() for key, value in metadata.items()}

    # --------------------------------------------------------------- internal

    def _require_coherent(
        self,
        *,
        profile: DecisionProfile,
        manifest: DecisionSetManifest,
        records: tuple[DecisionRecord, ...],
    ) -> None:
        """Cheap structural agreement. Re-derivation lives in ``decisions.verify``."""
        if not records:
            raise StorageError("a decision set with no decisions is not one")
        if len(records) != manifest.total_decisions:
            raise StorageError(
                f"decision set declares {manifest.total_decisions} decisions but "
                f"carries {len(records)}"
            )
        if profile.profile_fingerprint != manifest.decision_profile_fingerprint:
            raise StorageError(
                "the stored profile is not the profile the manifest names"
            )
        if profile.profile_id != manifest.decision_profile_id:
            raise StorageError(
                "the stored profile id is not the one the manifest names"
            )
        if [record.ordinal for record in records] != list(range(len(records))):
            raise StorageError(
                "decision ordinals must be 0..n-1 with no gaps and no repeats"
            )
        job_ids = [record.job_id for record in records]
        if len(set(job_ids)) != len(job_ids):
            raise StorageError("a job may appear at most once in a decision set")
        hashes = [record.decision_record_hash for record in records]
        if len(set(hashes)) != len(hashes):
            raise StorageError("two decisions hash identically")
        for record in records:
            if record.decision_profile_fingerprint != profile.profile_fingerprint:
                raise StorageError(
                    f"decision {record.job_id} was made under a different profile "
                    "than the one stored beside it"
                )

    def _write_records(
        self, manifest: DecisionSetManifest, records: tuple[DecisionRecord, ...]
    ) -> Path:
        path = self.records_path(manifest.run_id, manifest.decision_set_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        table = derivation_schemas.decisions_to_table(records)
        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"schema_version": DECISION_SET_SCHEMA_VERSION.encode(),
                b"decision_set_id": manifest.decision_set_id.encode(),
                b"decision_set_fingerprint": manifest.decision_set_fingerprint.encode(),
                b"ordered_decisions_hash": manifest.ordered_decisions_hash.encode(),
                b"run_id": manifest.run_id.encode(),
                b"run_fingerprint": manifest.run_fingerprint.encode(),
                b"result_set_fingerprint": manifest.result_set_fingerprint.encode(),
                b"decision_profile_fingerprint": (
                    manifest.decision_profile_fingerprint.encode()
                ),
                b"derivation_source_revision": (
                    manifest.derivation_source_revision.encode()
                ),
                b"row_count": str(len(records)).encode(),
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
