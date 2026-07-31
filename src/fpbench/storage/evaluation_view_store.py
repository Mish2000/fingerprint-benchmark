"""Where the three evaluation views live.

    results/<run_id>/decisions/<decision_set_id>/evaluation-views/
    ├── plain-roll-mated-unconditional/{manifest.json,entries.parquet}
    ├── plain-roll-mated-both-self-match/{manifest.json,entries.parquet}
    └── plain-roll-non-mated-sanity/{manifest.json,entries.parquet}

Directories are named after the *kind* rather than the view id, because the id
changes whenever the contents do and a reader looking for "the conditional view"
should not have to know this derivation's digest. The id is inside, in the
manifest, where a conflict can be detected.

Immutable, atomic, no overwrite — the same terms as every other store here.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.errors import DecisionSetConflictError, StorageError
from fpbench.core.evaluation_view_models import (
    EVALUATION_VIEW_SCHEMA_VERSION,
    EvaluationViewEntry,
    EvaluationViewManifest,
    ordered_entries_hash,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import derivation_schemas, layout

__all__ = ["EvaluationViewStore"]

_MANIFEST = "manifest.json"
_ENTRIES = "entries.parquet"


class EvaluationViewStore:
    """Immutable storage for evaluation views beneath one decision set."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    def views_dir(self, run_id: str, decision_set_id: str) -> Path:
        return layout.evaluation_views_directory(self.root, run_id, decision_set_id)

    def view_dir(self, run_id: str, decision_set_id: str, view_kind: str) -> Path:
        return layout.evaluation_view_directory(
            self.root, run_id, decision_set_id, view_kind
        )

    def manifest_path(
        self, run_id: str, decision_set_id: str, view_kind: str
    ) -> Path:
        return self.view_dir(run_id, decision_set_id, view_kind) / _MANIFEST

    def entries_path(self, run_id: str, decision_set_id: str, view_kind: str) -> Path:
        return self.view_dir(run_id, decision_set_id, view_kind) / _ENTRIES

    def has_view(self, run_id: str, decision_set_id: str, view_kind: str) -> bool:
        return self.manifest_path(run_id, decision_set_id, view_kind).is_file()

    # ------------------------------------------------------------------ write

    def ensure_view(
        self,
        *,
        run_id: str,
        decision_set_id: str,
        manifest: EvaluationViewManifest,
        entries: tuple[EvaluationViewEntry, ...],
    ) -> Path:
        """Store the view, or confirm the stored one is already it."""
        entries = tuple(entries)
        self._require_coherent(manifest=manifest, entries=entries)

        manifest_path = self.manifest_path(
            run_id, decision_set_id, manifest.view_kind
        )
        if manifest_path.is_file():
            stored = self.read_manifest(run_id, decision_set_id, manifest.view_kind)
            if stored.view_fingerprint != manifest.view_fingerprint:
                raise DecisionSetConflictError(
                    f"decision set {decision_set_id} already holds view "
                    f"{stored.view_id} of kind {manifest.view_kind}; refusing to "
                    f"replace it with {manifest.view_id}"
                )
            return manifest_path.parent

        self._write_entries(run_id, decision_set_id, manifest, entries)
        write_json(manifest_path, manifest)
        return manifest_path.parent

    # ------------------------------------------------------------------- read

    def read_manifest(
        self, run_id: str, decision_set_id: str, view_kind: str
    ) -> EvaluationViewManifest:
        path = self.manifest_path(run_id, decision_set_id, view_kind)
        if not path.is_file():
            raise StorageError(f"evaluation view manifest not found: {path}")
        payload = read_json(path)
        try:
            manifest = EvaluationViewManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable evaluation view manifest ({exc})"
            ) from exc
        if manifest.view_kind != view_kind:
            raise StorageError(
                f"{path}: manifest kind {manifest.view_kind!r} does not match its "
                f"{view_kind!r} directory"
            )
        return manifest

    def read_entries(
        self, run_id: str, decision_set_id: str, view_kind: str
    ) -> tuple[EvaluationViewEntry, ...]:
        path = self.entries_path(run_id, decision_set_id, view_kind)
        if not path.is_file():
            raise StorageError(f"evaluation view entries not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                table = reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        try:
            return tuple(derivation_schemas.table_to_view_entries(table))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable view entries ({exc})") from exc

    def read_view(
        self, run_id: str, decision_set_id: str, view_kind: str
    ) -> tuple[EvaluationViewManifest, tuple[EvaluationViewEntry, ...]]:
        manifest = self.read_manifest(run_id, decision_set_id, view_kind)
        entries = self.read_entries(run_id, decision_set_id, view_kind)
        self._require_coherent(manifest=manifest, entries=entries)
        return manifest, entries

    # --------------------------------------------------------------- internal

    def _require_coherent(
        self,
        *,
        manifest: EvaluationViewManifest,
        entries: tuple[EvaluationViewEntry, ...],
    ) -> None:
        if not entries:
            raise StorageError("an evaluation view with no rows is not one")
        if len(entries) != manifest.total_rows:
            raise StorageError(
                f"view declares {manifest.total_rows} rows but carries {len(entries)}"
            )
        if [entry.ordinal for entry in entries] != list(range(len(entries))):
            raise StorageError(
                "view ordinals must be 0..n-1 with no gaps and no repeats"
            )
        pair_ids = [entry.pair_id for entry in entries]
        if len(set(pair_ids)) != len(pair_ids):
            raise StorageError("a pair may appear at most once in a view")
        if ordered_entries_hash(entries) != manifest.ordered_entries_hash:
            raise StorageError(
                "the manifest's ordered entries hash does not cover these rows"
            )

    def _write_entries(
        self,
        run_id: str,
        decision_set_id: str,
        manifest: EvaluationViewManifest,
        entries: tuple[EvaluationViewEntry, ...],
    ) -> Path:
        path = self.entries_path(run_id, decision_set_id, manifest.view_kind)
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        table = derivation_schemas.view_entries_to_table(entries)
        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"schema_version": EVALUATION_VIEW_SCHEMA_VERSION.encode(),
                b"view_id": manifest.view_id.encode(),
                b"view_kind": manifest.view_kind.encode(),
                b"view_fingerprint": manifest.view_fingerprint.encode(),
                b"ordered_entries_hash": manifest.ordered_entries_hash.encode(),
                b"policy_id": manifest.policy_id.encode(),
                b"policy_version": manifest.policy_version.encode(),
                b"decision_set_id": decision_set_id.encode(),
                b"decision_set_fingerprint": manifest.decision_set_fingerprint.encode(),
                b"run_id": run_id.encode(),
                b"row_count": str(len(entries)).encode(),
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
