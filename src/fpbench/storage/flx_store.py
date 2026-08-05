"""Immutable filing for the small, sanitised Stage 8B evidence tree.

This store knows filenames and write order, not qualification policy.  Like the
rest of :mod:`fpbench.storage` it imports only ``core``.

It is deliberately not re-exported from ``fpbench.storage.__init__``: that
module is one of the paths Stage 8A's published finalization pins byte for
byte, and Stage 8B has no business moving it (docs/adr/0067).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from fpbench.core.errors import StorageError
from fpbench.core.serialization import read_json, to_plain, write_json

__all__ = ["Stage8BEvidenceStore"]


class _FingerprintRecord(Protocol):
    fingerprint: str


class Stage8BEvidenceStore:
    DIRECTORY_NAME = "stage8b-flx-runtime-qualification"
    README_NAME = "README.md"
    ARTIFACT_BINDING_NAME = "artifact-binding.json"
    RUNTIME_MANIFEST_NAME = "runtime-manifest.json"
    PREPROCESSING_PROFILE_NAME = "preprocessing-profile.json"
    REPRESENTATION_PROFILE_NAME = "representation-profile.json"
    SCORE_PROFILE_NAME = "score-profile.json"
    ADAPTER_PROFILE_NAME = "adapter-profile.json"
    RUNTIME_PROBE_NAME = "runtime-probe.json"
    QUALIFICATION_REPORT_NAME = "qualification-report.json"
    FINALIZATION_NAME = "stage-8b-finalization.json"

    #: Finalization is last, and everything it binds must exist first.
    PREREQUISITE_NAMES = (
        README_NAME,
        ARTIFACT_BINDING_NAME,
        RUNTIME_MANIFEST_NAME,
        PREPROCESSING_PROFILE_NAME,
        REPRESENTATION_PROFILE_NAME,
        SCORE_PROFILE_NAME,
        ADAPTER_PROFILE_NAME,
        RUNTIME_PROBE_NAME,
        QUALIFICATION_REPORT_NAME,
    )
    ALL_NAMES = PREREQUISITE_NAMES + (FINALIZATION_NAME,)

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = Path(repository_root)

    @property
    def evidence_dir(self) -> Path:
        return self.repository_root / "evidence" / self.DIRECTORY_NAME

    def path(self, name: str) -> Path:
        if name not in self.ALL_NAMES:
            raise StorageError(f"{name} is not part of the Stage 8B publication")
        return self.evidence_dir / name

    @property
    def readme_path(self) -> Path:
        return self.path(self.README_NAME)

    @property
    def finalization_path(self) -> Path:
        return self.path(self.FINALIZATION_NAME)

    def ensure(self, name: str, record: _FingerprintRecord) -> Path:
        return self._ensure(self.path(name), record, name)

    def ensure_finalization(self, marker: _FingerprintRecord) -> Path:
        missing = [
            name for name in self.PREREQUISITE_NAMES if not self.path(name).is_file()
        ]
        if missing:
            raise StorageError(
                f"Stage 8B finalization is last; missing prerequisites {missing}"
            )
        return self._ensure(self.finalization_path, marker, self.FINALIZATION_NAME)

    def read_document(self, path: Path, what: str) -> Mapping[str, Any]:
        if not Path(path).is_file():
            raise StorageError(f"{what} not found: {path}")
        try:
            payload = read_json(Path(path))
        except (OSError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable {what} ({exc})") from exc
        if not isinstance(payload, Mapping):
            raise StorageError(f"{path}: {what} must be a JSON object")
        return dict(payload)

    def _ensure(self, path: Path, record: _FingerprintRecord, what: str) -> Path:
        payload = to_plain(record)
        if path.is_file():
            stored = self.read_document(path, what)
            if stored != payload:
                stored_fingerprint = str(stored.get("fingerprint", ""))
                raise StorageError(
                    f"{path} already stores a different {what} "
                    f"({stored_fingerprint[:12]}...); refusing to overwrite it with "
                    f"{record.fingerprint[:12]}..."
                )
            return path
        return write_json(path, record)
