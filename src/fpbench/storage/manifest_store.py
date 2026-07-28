"""Reading and writing the manifests that define an experiment.

Manifests are the source of truth. Reports are derived and disposable;
manifests are not, so every write here is:

  * refused by default when the target already exists — regenerating a manifest
    under changed rules must be a deliberate act (docs/adr/0005);
  * atomic — written to a temporary sibling and renamed, so an interrupted run
    cannot leave a half-written file that later looks valid;
  * stamped — creation time, tool version and row count are stored in the
    parquet schema metadata, not in a separate file that can drift.

Layout under the workspace root::

    manifests/datasets/<dataset>/<release>/images.parquet
    manifests/datasets/<dataset>/<release>/subjects.parquet
    manifests/protocols/<protocol>/cohort.json
    manifests/protocols/<protocol>/pairs.parquet
    manifests/protocols/<protocol>/derived/<name>.parquet
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.enums import CohortRole
from fpbench.core.errors import ManifestExistsError, StorageError
from fpbench.core.identifiers import CohortId, SubjectId
from fpbench.core.models import Cohort, CohortSelection, ComparisonPair, ImageRecord, SubjectRecord
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import schemas

__all__ = ["ManifestStore"]

_DERIVED_SELF_ELIGIBLE = "self_eligible_pairs"


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
        return self.manifests_root / "protocols" / protocol_id

    def images_path(self, dataset_id: str, release: str) -> Path:
        return self.dataset_dir(dataset_id, release) / "images.parquet"

    def subjects_path(self, dataset_id: str, release: str) -> Path:
        return self.dataset_dir(dataset_id, release) / "subjects.parquet"

    def cohort_path(self, protocol_id: str) -> Path:
        return self.protocol_dir(protocol_id) / "cohort.json"

    def pairs_path(self, protocol_id: str) -> Path:
        return self.protocol_dir(protocol_id) / "pairs.parquet"

    def derived_pairs_path(self, protocol_id: str, name: str) -> Path:
        return self.protocol_dir(protocol_id) / "derived" / f"{name}.parquet"

    # ----------------------------------------------------------------- images

    def write_images(
        self,
        images: Iterable[ImageRecord],
        *,
        dataset_id: str,
        release: str,
        overwrite: bool = False,
    ) -> Path:
        table = schemas.images_to_table(images)
        return self._write_table(
            self.images_path(dataset_id, release), table, overwrite=overwrite
        )

    def read_images(self, dataset_id: str, release: str) -> list[ImageRecord]:
        return schemas.table_to_images(self._read_table(self.images_path(dataset_id, release)))

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
            self.subjects_path(dataset_id, release), table, overwrite=overwrite
        )

    def read_subjects(self, dataset_id: str, release: str) -> list[SubjectRecord]:
        return schemas.table_to_subjects(
            self._read_table(self.subjects_path(dataset_id, release))
        )

    # ----------------------------------------------------------------- cohort

    def write_cohort(self, cohort: Cohort, *, overwrite: bool = False) -> Path:
        """Cohorts are small and read by humans, so they are JSON, not parquet."""
        path = self.cohort_path(cohort.protocol_id)
        self._guard(path, overwrite)
        return write_json(path, cohort)

    def read_cohort(self, protocol_id: str) -> Cohort:
        payload = read_json(self.cohort_path(protocol_id))
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
            ),
        )

    # ------------------------------------------------------------------ pairs

    def write_pairs(
        self,
        pairs: Iterable[ComparisonPair],
        *,
        protocol_id: str,
        overwrite: bool = False,
    ) -> Path:
        table = schemas.pairs_to_table(pairs)
        return self._write_table(self.pairs_path(protocol_id), table, overwrite=overwrite)

    def read_pairs(self, protocol_id: str) -> list[ComparisonPair]:
        return schemas.table_to_pairs(self._read_table(self.pairs_path(protocol_id)))

    def write_derived_pairs(
        self,
        pairs: Sequence[ComparisonPair],
        *,
        protocol_id: str,
        name: str = _DERIVED_SELF_ELIGIBLE,
        overwrite: bool = True,
    ) -> Path:
        """Write a derived view of the pair manifest.

        Derived views default to ``overwrite=True``: unlike ``pairs.parquet``
        they are a function of results that legitimately change as more of the
        experiment is run.
        """
        table = schemas.pairs_to_table(pairs)
        return self._write_table(
            self.derived_pairs_path(protocol_id, name), table, overwrite=overwrite
        )

    def read_derived_pairs(
        self, protocol_id: str, name: str = _DERIVED_SELF_ELIGIBLE
    ) -> list[ComparisonPair]:
        return schemas.table_to_pairs(
            self._read_table(self.derived_pairs_path(protocol_id, name))
        )

    # --------------------------------------------------------------- internal

    def _guard(self, path: Path, overwrite: bool) -> None:
        if path.exists() and not overwrite:
            raise ManifestExistsError(
                f"{path} already exists; pass overwrite=True to replace it. "
                "Manifests are treated as immutable inputs to every run."
            )

    def _write_table(self, path: Path, table: pa.Table, *, overwrite: bool) -> Path:
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
            }
        )

        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            pq.write_table(stamped, tmp, compression="zstd")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path

    def _read_table(self, path: Path) -> pa.Table:
        if not path.is_file():
            raise StorageError(f"manifest not found: {path}")
        return pq.read_table(path)
