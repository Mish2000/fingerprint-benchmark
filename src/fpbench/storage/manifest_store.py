"""Reading and writing the manifests that define an experiment.

Manifests are the source of truth. Reports are derived and disposable;
manifests are not, so every write here is:

  * refused by default when the target already exists — regenerating a manifest
    under changed rules must be a deliberate act (docs/adr/0005). The refusal is
    the *filesystem's*, not a check's: ``overwrite=False`` publishes
    create-if-absent, so two writers arriving together cannot both pass a guard
    and have the second replace the first. ``overwrite=True`` is the separate,
    deliberate replacement (docs/adr/0139);
  * atomic — written to a uniquely named temporary sibling and renamed, so an
    interrupted run cannot leave a half-written file that later looks valid, and
    two concurrent writers cannot corrupt each other's scratch copy;
  * stamped — creation time, tool version and row count are stored in the
    parquet schema metadata, not in a separate file that can drift.

Layout under the workspace root::

    manifests/datasets/<dataset>/<release>/images.parquet
    manifests/datasets/<dataset>/<release>/subjects.parquet
    manifests/protocols/<protocol>/cohorts/<cohort>/cohort.json
    manifests/protocols/<protocol>/cohorts/<cohort>/pairs.parquet
    results/<run>/decisions/<decision-profile>/self_eligibility.parquet
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.enums import CohortRole
from fpbench.core.errors import ManifestExistsError, StorageError
from fpbench.core.identifiers import CohortId, SubjectId, validate_id
from fpbench.core.models import (
    Cohort,
    CohortSelection,
    ComparisonPair,
    ImageRecord,
    SelfEligibilityRecord,
    SubjectRecord,
)
from fpbench.core.atomic_write import PublishConflictError
from fpbench.core.serialization import read_json, stable_hash
from fpbench.core.json_io import publish_json, write_json
from fpbench.storage import schemas
from fpbench.storage.atomic_parquet import publish_table, replace_table

__all__ = ["ManifestStore"]

_IMAGE_SCHEMA_VERSION = "2"
_SUBJECT_SCHEMA_VERSION = "1"
_PAIR_SCHEMA_VERSION = "2"
_SELF_ELIGIBILITY_SCHEMA_VERSION = "1"


class ManifestStore:
    """Filesystem-backed manifest storage rooted at a workspace directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    @property
    def manifests_root(self) -> Path:
        return self.root / "manifests"

    def dataset_dir(self, dataset_id: str, release: str) -> Path:
        return self.manifests_root / "datasets" / dataset_id / release

    def protocol_dir(self, protocol_id: str) -> Path:
        return self.manifests_root / "protocols" / validate_id(protocol_id)

    def cohort_dir(self, protocol_id: str, cohort_id: str) -> Path:
        return (
            self.protocol_dir(protocol_id)
            / "cohorts"
            / validate_id(str(cohort_id))
        )

    def images_path(self, dataset_id: str, release: str) -> Path:
        return self.dataset_dir(dataset_id, release) / "images.parquet"

    def subjects_path(self, dataset_id: str, release: str) -> Path:
        return self.dataset_dir(dataset_id, release) / "subjects.parquet"

    def validation_report_path(self, dataset_id: str, release: str) -> Path:
        return self.dataset_dir(dataset_id, release) / "validation.json"

    def cohort_path(self, protocol_id: str, cohort_id: str) -> Path:
        return self.cohort_dir(protocol_id, cohort_id) / "cohort.json"

    def pairs_path(self, protocol_id: str, cohort_id: str) -> Path:
        return self.cohort_dir(protocol_id, cohort_id) / "pairs.parquet"

    def self_eligibility_path(
        self, run_id: str, decision_profile_id: str
    ) -> Path:
        return (
            self.root
            / "results"
            / validate_id(run_id)
            / "decisions"
            / validate_id(decision_profile_id)
            / "self_eligibility.parquet"
        )

    # ----------------------------------------------------------------- images

    def write_images(
        self,
        images: Iterable[ImageRecord],
        *,
        dataset_id: str,
        release: str,
        validation_override_reason: str | None = None,
        overwrite: bool = False,
    ) -> Path:
        image_records = tuple(images)
        blocked = [image.image_id for image in image_records if not image.is_usable]
        override_reason = (validation_override_reason or "").strip()
        if blocked and not override_reason:
            raise StorageError(
                f"{release}: {len(blocked)} blocked image record(s); provide a "
                "documented validation_override_reason to persist them for audit"
            )
        table = schemas.images_to_table(image_records)
        metadata = {
            "schema_version": _IMAGE_SCHEMA_VERSION,
            "content_hash": self._content_hash(table),
        }
        if override_reason:
            metadata["validation_override_reason"] = override_reason
        return self._write_table(
            self.images_path(dataset_id, release),
            table,
            overwrite=overwrite,
            metadata=metadata,
        )

    def read_images(self, dataset_id: str, release: str) -> list[ImageRecord]:
        return schemas.table_to_images(self._read_table(self.images_path(dataset_id, release)))

    def image_manifest_hash(self, dataset_id: str, release: str) -> str:
        """Semantic hash of one persisted image manifest (timestamps excluded)."""
        return self._required_metadata(
            self.images_path(dataset_id, release), "content_hash"
        )

    def image_manifest_metadata(
        self, dataset_id: str, release: str
    ) -> Mapping[str, str]:
        return self._metadata(self.images_path(dataset_id, release))

    def write_validation_report(
        self,
        report: object,
        *,
        dataset_id: str,
        release: str,
        overwrite: bool = False,
    ) -> Path:
        """Persist a dataset report without making storage depend on providers."""
        if getattr(report, "dataset_id", None) != dataset_id:
            raise StorageError("validation report dataset_id does not match its path")
        if getattr(report, "release", None) != release:
            raise StorageError("validation report release does not match its path")
        path = self.validation_report_path(dataset_id, release)
        self._guard(path, overwrite)
        return self._publish_json_document(path, report, overwrite=overwrite)

    def read_validation_report(
        self, dataset_id: str, release: str
    ) -> Mapping[str, object]:
        """Read the JSON report as plain data for audit and CLI presentation."""
        return read_json(self.validation_report_path(dataset_id, release))

    # --------------------------------------------------------------- subjects

    def write_subjects(
        self,
        subjects: Iterable[SubjectRecord],
        *,
        dataset_id: str,
        release: str,
        overwrite: bool = False,
    ) -> Path:
        table = schemas.subjects_to_table(subjects)
        return self._write_table(
            self.subjects_path(dataset_id, release),
            table,
            overwrite=overwrite,
            metadata={
                "schema_version": _SUBJECT_SCHEMA_VERSION,
                "content_hash": self._content_hash(table),
            },
        )

    def read_subjects(self, dataset_id: str, release: str) -> list[SubjectRecord]:
        return schemas.table_to_subjects(
            self._read_table(self.subjects_path(dataset_id, release))
        )

    # ----------------------------------------------------------------- cohort

    def write_cohort(self, cohort: Cohort, *, overwrite: bool = False) -> Path:
        """Cohorts are small and read by humans, so they are JSON, not parquet."""
        path = self.cohort_path(cohort.protocol_id, cohort.cohort_id)
        self._guard(path, overwrite)
        return self._publish_json_document(path, cohort, overwrite=overwrite)

    def read_cohort(self, protocol_id: str, cohort_id: str) -> Cohort:
        payload = read_json(self.cohort_path(protocol_id, cohort_id))
        selection = payload["selection"]
        return Cohort(
            cohort_id=CohortId(payload["cohort_id"]),
            protocol_id=payload["protocol_id"],
            dataset_id=payload["dataset_id"],
            role=CohortRole(payload["role"]),
            releases=tuple(payload["releases"]),
            subject_ids=tuple(SubjectId(s) for s in payload["subject_ids"]),
            selection=CohortSelection(
                seed=selection["seed"],
                size=selection["size"],
                candidate_ids=tuple(SubjectId(s) for s in selection["candidate_ids"]),
                criteria=dict(selection["criteria"]),
                image_manifest_hashes=dict(selection["image_manifest_hashes"]),
            ),
        )

    # ------------------------------------------------------------------ pairs

    def write_pairs(
        self,
        pairs: Iterable[ComparisonPair],
        *,
        cohort: Cohort,
        overwrite: bool = False,
    ) -> Path:
        pair_records = tuple(pairs)
        invalid = [
            pair.pair_id
            for pair in pair_records
            if pair.dataset_id != cohort.dataset_id
            or pair.release not in cohort.releases
        ]
        if invalid:
            raise StorageError(
                f"pair manifest contains rows outside cohort {cohort.cohort_id}: "
                f"{invalid[:3]}"
            )
        table = schemas.pairs_to_table(pair_records)
        image_manifest_hash = stable_hash(
            cohort.selection.image_manifest_hashes, length=64
        )
        provenance = {
            "protocol_id": cohort.protocol_id,
            "cohort_id": str(cohort.cohort_id),
            "image_manifest_hash": image_manifest_hash,
            "schema_version": _PAIR_SCHEMA_VERSION,
        }
        pair_manifest_hash = stable_hash(
            {"provenance": provenance, "pairs": table.to_pylist()}, length=64
        )
        return self._write_table(
            self.pairs_path(cohort.protocol_id, cohort.cohort_id),
            table,
            overwrite=overwrite,
            metadata={**provenance, "pair_manifest_hash": pair_manifest_hash},
        )

    def read_pairs(self, protocol_id: str, cohort_id: str) -> list[ComparisonPair]:
        return schemas.table_to_pairs(
            self._read_table(self.pairs_path(protocol_id, cohort_id))
        )

    def pair_manifest_metadata(
        self, protocol_id: str, cohort_id: str
    ) -> Mapping[str, str]:
        path = self.pairs_path(protocol_id, cohort_id)
        return {
            key: self._required_metadata(path, key)
            for key in (
                "protocol_id",
                "cohort_id",
                "image_manifest_hash",
                "pair_manifest_hash",
                "schema_version",
            )
        }

    # ------------------------------------------------------ SELF eligibility

    def write_self_eligibility(
        self,
        records: Iterable[SelfEligibilityRecord],
        *,
        run_id: str,
        decision_profile_id: str,
        cohort: Cohort,
        overwrite: bool = False,
    ) -> Path:
        """Persist per-finger SELF decisions at run/decision-profile scope."""
        decision_records = tuple(records)
        invalid = [
            (record.release, record.subject_id, record.finger_position)
            for record in decision_records
            if record.release not in cohort.releases
            or record.subject_id not in cohort.subject_ids
        ]
        if invalid:
            raise StorageError(
                f"SELF eligibility contains rows outside cohort "
                f"{cohort.cohort_id}: {invalid[:3]}"
            )
        pair_metadata = self.pair_manifest_metadata(
            cohort.protocol_id, cohort.cohort_id
        )
        table = schemas.self_eligibility_to_table(decision_records)
        return self._write_table(
            self.self_eligibility_path(run_id, decision_profile_id),
            table,
            overwrite=overwrite,
            metadata={
                "schema_version": _SELF_ELIGIBILITY_SCHEMA_VERSION,
                "run_id": run_id,
                "decision_profile_id": decision_profile_id,
                "protocol_id": cohort.protocol_id,
                "cohort_id": str(cohort.cohort_id),
                "pair_manifest_hash": pair_metadata["pair_manifest_hash"],
                "content_hash": self._content_hash(table),
            },
        )

    def read_self_eligibility(
        self, run_id: str, decision_profile_id: str
    ) -> list[SelfEligibilityRecord]:
        return schemas.table_to_self_eligibility(
            self._read_table(self.self_eligibility_path(run_id, decision_profile_id))
        )

    # --------------------------------------------------------------- internal

    def _guard(self, path: Path, overwrite: bool) -> None:
        """Refuse early, and cheaply, when the manifest is already there.

        No longer the thing that makes ``overwrite=False`` safe — the writers
        below reserve the name with the filesystem, which is what a *second*
        writer arriving at the same moment runs into. This stays because it
        turns the ordinary case into an immediate message with the remedy in it,
        without first producing a scratch parquet nobody will keep.
        """
        if path.exists() and not overwrite:
            raise ManifestExistsError(
                f"{path} already exists; pass overwrite=True to replace it. "
                "Manifests are treated as immutable inputs to every run."
            )

    @staticmethod
    def _refuse_a_taken_name(path: Path) -> ManifestExistsError:
        return ManifestExistsError(
            f"{path} was published by another writer while this one was storing "
            "its own; pass overwrite=True to replace it. Manifests are treated "
            "as immutable inputs to every run."
        )

    def _publish_json_document(
        self, path: Path, payload: object, *, overwrite: bool
    ) -> Path:
        """One JSON manifest, refused-if-present or deliberately replaced.

        ``overwrite=False`` means "create this, and tell me if somebody else
        already did" — so it publishes create-if-absent and turns *either* way of
        losing into the refusal this store has always raised. Both ways matter:
        a second writer with different bytes raises ``PublishConflictError``, and
        one that happens to produce the same bytes is simply not the creator.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            return write_json(path, payload)
        try:
            published = publish_json(path, payload)
        except PublishConflictError as exc:
            raise self._refuse_a_taken_name(path) from exc
        if not published.created:
            raise self._refuse_a_taken_name(path)
        return path

    def _write_table(
        self,
        path: Path,
        table: pa.Table,
        *,
        overwrite: bool,
        metadata: Mapping[str, str] | None = None,
    ) -> Path:
        self._guard(path, overwrite)
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"fpbench_version": __version__.encode(),
                b"created_utc": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .encode(),
                b"row_count": str(table.num_rows).encode(),
                **{
                    key.encode(): value.encode()
                    for key, value in (metadata or {}).items()
                },
            }
        )

        if overwrite:
            # A deliberate replacement, which is what overwrite=True is for.
            replace_table(path, stamped, what="manifest table")
            return path

        # Create-if-absent. ``created_utc`` has one-second resolution, so two
        # writers of the same rows inside one second produce *identical* bytes
        # and the loser is told ALREADY_IDENTICAL rather than being refused —
        # which for a store whose contract is "refuse if present" would be a
        # silent success. Both outcomes are turned back into the refusal.
        try:
            published = publish_table(path, stamped, what="manifest table")
        except PublishConflictError as exc:
            raise self._refuse_a_taken_name(path) from exc
        if not published.created:
            raise self._refuse_a_taken_name(path)
        return path

    def _read_table(self, path: Path) -> pa.Table:
        if not path.is_file():
            raise StorageError(f"manifest not found: {path}")
        return pq.read_table(path)

    @staticmethod
    def _content_hash(table: pa.Table) -> str:
        return stable_hash(table.to_pylist(), length=64)

    @staticmethod
    def _required_metadata(path: Path, key: str) -> str:
        if not path.is_file():
            raise StorageError(f"manifest not found: {path}")
        metadata = pq.read_schema(path).metadata or {}
        value = metadata.get(key.encode())
        if value is None:
            raise StorageError(f"{path}: missing required metadata {key!r}")
        return value.decode()

    @staticmethod
    def _metadata(path: Path) -> dict[str, str]:
        if not path.is_file():
            raise StorageError(f"manifest not found: {path}")
        return {
            key.decode(): value.decode()
            for key, value in (pq.read_schema(path).metadata or {}).items()
        }
