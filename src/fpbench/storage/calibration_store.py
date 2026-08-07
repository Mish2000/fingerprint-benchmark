"""Append-only storage for calibration artifacts.

One rule, applied to all four kinds:

* writing an id that is not on disk stores it;
* writing an id that *is* on disk, with byte-identical content, succeeds and
  changes nothing;
* writing an id that is on disk with different content fails.

The third case is the reason the store exists. Every id here is derived from a
digest of the artifact's own contents, so two different documents under one id
cannot be a naming accident — it means something that was supposed to be
determined by its inputs was not, and overwriting would destroy the evidence of
that. The correct response is a new artifact, never a lost one (docs/adr/0005,
docs/adr/0009).

The second case matters almost as much. Re-running a finished calibration is the
normal way to verify it, and a store that refused an identical re-write would
make verification an operation you can only perform once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fpbench.core.calibration_errors import CalibrationConflictError
from fpbench.core.calibration_models import (
    CalibrationOperatingPoint,
    CalibrationProtocol,
    CalibrationSourceBinding,
    read_calibration_operating_point,
    read_calibration_protocol,
    read_calibration_source_binding,
    strict_json_document,
)
from fpbench.core.errors import StorageError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import to_plain
from fpbench.storage.layout import (
    calibration_operating_points_directory,
    calibration_protocols_directory,
    calibration_receipts_directory,
    calibration_source_bindings_directory,
)

__all__ = ["CalibrationStore", "canonical_bytes"]


def canonical_bytes(value: object) -> bytes:
    """The exact bytes an artifact is stored as.

    Written once here and used both to store and to compare, so "the same
    document" means the same thing to the writer and to the conflict check. Keys
    keep declaration order rather than being sorted, because that is what
    :func:`fpbench.core.serialization.write_json` produces and a stored file
    should be diffable against a freshly derived one.
    """
    payload = json.dumps(to_plain(value), indent=2, ensure_ascii=False, sort_keys=False)
    return (payload + "\n").encode("utf-8")


@dataclass(frozen=True, slots=True)
class CalibrationStore:
    """Append-only files under ``<workspace>/calibration/``."""

    root: Path

    # ------------------------------------------------------------- paths

    def protocol_path(self, protocol_id: str) -> Path:
        return calibration_protocols_directory(self.root) / (
            f"{validate_id(protocol_id)}.json"
        )

    def source_binding_path(self, binding_id: str) -> Path:
        return calibration_source_bindings_directory(self.root) / (
            f"{validate_id(binding_id)}.json"
        )

    def operating_point_path(self, operating_point_id: str) -> Path:
        return calibration_operating_points_directory(self.root) / (
            f"{validate_id(operating_point_id)}.json"
        )

    def receipt_path(self, operating_point_id: str) -> Path:
        return calibration_receipts_directory(self.root) / (
            f"{validate_id(operating_point_id)}.json"
        )

    # ------------------------------------------------------------- write

    def _append_only_write(self, path: Path, value: object, *, what: str) -> Path:
        """Store, or confirm what is already stored, or refuse.

        Writes *bytes* rather than text, and does not go through
        :func:`fpbench.core.serialization.write_json`. That function writes with
        ``write_text``, which applies the platform's newline translation — so on
        Windows the bytes on disk would be ``\\r\\n`` while the bytes this store
        compares against are ``\\n``, and an identical re-write would be reported
        as a conflict. A content-addressed store whose comparison depends on the
        operating system is not content-addressed.

        The temp-file-then-replace is the same atomicity ``write_json`` provides:
        an interrupted write can never leave a half-written artifact behind.
        """
        expected = canonical_bytes(value)
        if path.exists():
            try:
                stored = path.read_bytes()
            except OSError as exc:
                raise StorageError(f"cannot read stored {what} at {path}: {exc}") from exc
            if stored == expected:
                return path
            raise CalibrationConflictError(
                f"a different {what} is already stored at {path.name}. Its id is "
                "derived from a digest of its own contents, so two different "
                "documents under one id mean something that should have been "
                "determined by its inputs was not — never something to resolve by "
                "overwriting (docs/adr/0009)"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_bytes(expected)
            temporary.replace(path)
        except OSError as exc:
            raise StorageError(f"cannot write {what} to {path}: {exc}") from exc
        return path

    def write_protocol(self, protocol: CalibrationProtocol) -> Path:
        return self._append_only_write(
            self.protocol_path(protocol.protocol_id),
            protocol,
            what="calibration protocol",
        )

    def write_source_binding(self, binding: CalibrationSourceBinding) -> Path:
        return self._append_only_write(
            self.source_binding_path(binding.binding_id),
            binding,
            what="calibration source binding",
        )

    def write_operating_point(self, point: CalibrationOperatingPoint) -> Path:
        return self._append_only_write(
            self.operating_point_path(point.operating_point_id),
            point,
            what="calibration operating point",
        )

    def write_receipt(self, operating_point_id: str, receipt: object) -> Path:
        return self._append_only_write(
            self.receipt_path(operating_point_id),
            receipt,
            what="calibration receipt",
        )

    # -------------------------------------------------------------- read

    def read_protocol(self, protocol_id: str) -> CalibrationProtocol:
        return read_calibration_protocol(
            strict_json_document(self._read_text(self.protocol_path(protocol_id)))
        )

    def read_source_binding(self, binding_id: str) -> CalibrationSourceBinding:
        return read_calibration_source_binding(
            strict_json_document(
                self._read_text(self.source_binding_path(binding_id))
            )
        )

    def read_operating_point(
        self, operating_point_id: str
    ) -> CalibrationOperatingPoint:
        return read_calibration_operating_point(
            strict_json_document(
                self._read_text(self.operating_point_path(operating_point_id))
            )
        )

    def _read_text(self, path: Path) -> str:
        if not path.is_file():
            raise StorageError(f"calibration artifact not found: {path}")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"cannot read {path}: {exc}") from exc

    # ---------------------------------------------------------- inventory

    def stored_operating_point_ids(self) -> tuple[str, ...]:
        directory = calibration_operating_points_directory(self.root)
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.json")))


# The protected-evaluation registry is deliberately not stored here, and this
# store has no method for it. It is not a calibration output — it is a
# *constraint on inputs*, published with the stage that declares it rather than
# copied into every workspace that obeys it. A per-workspace copy could drift
# from another workspace's, and the whole value of the artifact is that there is
# one (docs/adr/0079).
