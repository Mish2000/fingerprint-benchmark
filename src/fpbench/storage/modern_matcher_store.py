"""Immutable filing for the small, sanitised Stage 8A evidence tree.

This store knows filenames and fingerprints, not qualification policy.  Like
the rest of :mod:`fpbench.storage`, it imports only ``core`` from the project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from fpbench.core.errors import StorageError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import read_json, to_plain, write_json

__all__ = ["Stage8AEvidenceStore", "FingerprintRecord"]


class FingerprintRecord(Protocol):
    fingerprint: str


class Stage8AEvidenceStore:
    DIRECTORY_NAME = "stage8a-modern-matcher-selection"
    REGISTRY_NAME = "candidate-registry.json"
    SELECTION_NAME = "selection-decision.json"
    FINALIZATION_NAME = "stage-8a-finalization.json"
    README_NAME = "README.md"

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = Path(repository_root)

    @property
    def evidence_dir(self) -> Path:
        return self.repository_root / "evidence" / self.DIRECTORY_NAME

    @property
    def registry_path(self) -> Path:
        return self.evidence_dir / self.REGISTRY_NAME

    @property
    def selection_path(self) -> Path:
        return self.evidence_dir / self.SELECTION_NAME

    @property
    def finalization_path(self) -> Path:
        return self.evidence_dir / self.FINALIZATION_NAME

    @property
    def readme_path(self) -> Path:
        return self.evidence_dir / self.README_NAME

    def qualification_path(self, candidate_id: str) -> Path:
        validate_id(candidate_id)
        return self.evidence_dir / f"qualification-{candidate_id}.json"

    def ensure_registry(self, registry: FingerprintRecord) -> Path:
        return self._ensure(self.registry_path, registry, "candidate registry")

    def ensure_qualification(self, candidate_id: str, report: FingerprintRecord) -> Path:
        if str(getattr(report, "candidate_id", "")) != candidate_id:
            raise StorageError("qualification report candidate id does not match its filename")
        if not self.registry_path.is_file():
            raise StorageError("candidate registry must be written before qualification reports")
        return self._ensure(self.qualification_path(candidate_id), report, f"qualification for {candidate_id}")

    def ensure_selection(self, decision: FingerprintRecord, candidate_ids: tuple[str, ...]) -> Path:
        for candidate_id in candidate_ids:
            validate_id(candidate_id)
        if not self.registry_path.is_file():
            raise StorageError("candidate registry must exist before selection")
        missing = [candidate_id for candidate_id in candidate_ids if not self.qualification_path(candidate_id).is_file()]
        if missing:
            raise StorageError(f"selection requires every qualification report; missing {missing}")
        return self._ensure(self.selection_path, decision, "selection decision")

    def ensure_finalization(self, marker: FingerprintRecord, candidate_ids: tuple[str, ...]) -> Path:
        for candidate_id in candidate_ids:
            validate_id(candidate_id)
        prerequisites = [self.registry_path, self.selection_path, self.readme_path]
        prerequisites.extend(self.qualification_path(candidate_id) for candidate_id in candidate_ids)
        missing = [path.name for path in prerequisites if not path.is_file()]
        if missing:
            raise StorageError(f"Stage 8A finalization is last; missing prerequisites {missing}")
        return self._ensure(self.finalization_path, marker, "Stage 8A finalization")

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

    def _ensure(self, path: Path, record: FingerprintRecord, what: str) -> Path:
        payload = to_plain(record)
        if path.is_file():
            stored = self.read_document(path, what)
            if stored != payload:
                stored_fp = str(stored.get("fingerprint", ""))
                raise StorageError(
                    f"{path} already stores a different {what} "
                    f"({stored_fp[:12]}...); refusing to overwrite it with "
                    f"{record.fingerprint[:12]}..."
                )
            return path
        return write_json(path, record)
