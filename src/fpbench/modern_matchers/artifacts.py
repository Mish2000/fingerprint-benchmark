"""Offline verification of already-acquired candidate artefacts.

Nothing here downloads.  A manifest either resolves beneath the explicitly
supplied artefact root and rehashes to its claims, or qualification stops.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from fpbench.core.errors import CandidateArtifactError
from fpbench.core.modern_matcher_models import CandidateArtifactManifest, CandidateComponent

__all__ = ["ModernMatcherArtifactStore"]

_CHUNK = 1 << 20
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


class ModernMatcherArtifactStore:
    def __init__(self, root: Path) -> None:
        try:
            self.root = Path(root).resolve()
        except (OSError, RuntimeError) as exc:
            raise CandidateArtifactError(
                f"artefact root cannot be resolved: {root}"
            ) from exc

    def verify_manifest(self, manifest: CandidateArtifactManifest) -> dict[str, Path]:
        if not manifest.required_components_available_offline:
            raise CandidateArtifactError(
                f"{manifest.candidate_id}: required components are not all locked for offline use"
            )
        if manifest.storage_reference is None:
            raise CandidateArtifactError(f"{manifest.candidate_id}: offline manifest has no storage reference")
        reference_parts = self._logical_path_parts(
            manifest.storage_reference,
            "storage_reference",
        )
        base = self._directory_without_links(self.root, reference_parts)
        verified: dict[str, Path] = {}
        for component in manifest.components:
            if component.required:
                verified[component.component_id] = self._verify_component(base, component)
        return verified

    def _verify_component(self, base: Path, component: CandidateComponent) -> Path:
        if not component.filename:
            raise CandidateArtifactError(f"{component.component_id}: locked component has no filename")
        relative_parts = self._logical_path_parts(
            component.filename,
            f"{component.component_id}: filename",
        )
        current = base
        for index, part in enumerate(relative_parts):
            current = current / part
            try:
                info = current.lstat()
            except OSError as exc:
                raise CandidateArtifactError(
                    f"{component.component_id}: required artefact is missing: {current}"
                ) from exc
            if self._is_link_or_reparse(info):
                raise CandidateArtifactError(
                    f"{component.component_id}: artefact path must be non-link "
                    "and may not contain a reparse point"
                )
            self._resolved_beneath_root(current, component.component_id)
            if index < len(relative_parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise CandidateArtifactError(
                    f"{component.component_id}: artefact parent is not a directory"
                )
        path = current
        try:
            info = path.lstat()
        except OSError as exc:
            raise CandidateArtifactError(f"{component.component_id}: required artefact is missing: {path}") from exc
        if self._is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise CandidateArtifactError(f"{component.component_id}: artefact must be a regular non-link file")
        if component.size_bytes is None or info.st_size != component.size_bytes:
            raise CandidateArtifactError(
                f"{component.component_id}: byte size changed (expected {component.size_bytes}, got {info.st_size})"
            )
        expected = component.sha256 or component.source_archive_sha256
        if expected is None:
            raise CandidateArtifactError(f"{component.component_id}: locked file has no SHA-256 identity")
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(_CHUNK), b""):
                    digest.update(block)
        except OSError as exc:
            raise CandidateArtifactError(
                f"{component.component_id}: required artefact could not be read: {path}"
            ) from exc
        if digest.hexdigest() != expected:
            raise CandidateArtifactError(f"{component.component_id}: SHA-256 changed")
        return path

    @staticmethod
    def _logical_path_parts(value: str, label: str) -> tuple[str, ...]:
        """Return canonical, portable relative path parts.

        Manifests use POSIX separators independent of the host platform.  This
        validation is deliberately stricter than ``Path`` so a manifest cannot
        acquire different semantics when moved between POSIX and Windows.
        """

        if not value or "\x00" in value or "\\" in value:
            raise CandidateArtifactError(
                f"{label} must be a canonical relative logical path using POSIX "
                "separators beneath the artefact root"
            )
        posix_path = PurePosixPath(value)
        windows_path = PureWindowsPath(value)
        raw_parts = value.split("/")
        if (
            posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
            or posix_path.as_posix() != value
            or any(part in {"", ".", ".."} for part in raw_parts)
        ):
            raise CandidateArtifactError(
                f"{label} must be a canonical relative logical path using POSIX "
                "separators beneath the artefact root"
            )
        for part in raw_parts:
            stem = part.split(".", 1)[0].upper()
            if (
                any(character in _WINDOWS_FORBIDDEN_CHARACTERS for character in part)
                or any(ord(character) < 32 for character in part)
                or part.endswith((" ", "."))
                or stem in _WINDOWS_RESERVED_NAMES
            ):
                raise CandidateArtifactError(
                    f"{label} must be a canonical relative logical path using POSIX "
                    "separators beneath the artefact root"
                )
        return tuple(raw_parts)

    @staticmethod
    def _is_link_or_reparse(info: object) -> bool:
        mode = getattr(info, "st_mode", 0)
        attributes = getattr(info, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return stat.S_ISLNK(mode) or bool(attributes & reparse_flag)

    def _resolved_beneath_root(self, path: Path, label: str) -> Path:
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise CandidateArtifactError(
                f"{label}: resolved artefact path escapes the supplied root"
            ) from exc
        except (OSError, RuntimeError) as exc:
            raise CandidateArtifactError(
                f"{label}: artefact path could not be resolved: {path}"
            ) from exc
        return resolved

    def _directory_without_links(
        self, base: Path, parts: tuple[str, ...]
    ) -> Path:
        current = base
        for part in parts:
            current = current / part
            try:
                info = current.lstat()
            except OSError as exc:
                raise CandidateArtifactError(
                    f"candidate artefact directory is missing: {current}"
                ) from exc
            if self._is_link_or_reparse(info):
                raise CandidateArtifactError(
                    "storage_reference may not traverse a link or reparse point"
                )
            if not stat.S_ISDIR(info.st_mode):
                raise CandidateArtifactError(
                    f"candidate artefact storage is not a directory: {current}"
                )
            self._resolved_beneath_root(current, "storage_reference")
        return current
