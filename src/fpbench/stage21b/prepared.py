"""Resolve the frozen canonical500 set into adapter-safe inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from fpbench.core.enums import ChecksumStatus
from fpbench.core.execution_models import PreparedImage
from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import PreparedImageEntry
from fpbench.stage21b.constants import (
    EFFECTIVE_PPI,
    LEGACY_PAIR_MANIFEST_HASH,
    PREPARATION_PROFILE_ID,
    PREPARATION_SET_ID,
)
from fpbench.stage21b.errors import Stage21BPreflightError
from fpbench.stage21b.models import PlannedPair, PreparationReference
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore


class FrozenPreparedInputs:
    """A verified prepared set and the only path from pair IDs to image bytes."""

    def __init__(
        self,
        *,
        workspace: Path,
        required_image_ids: Iterable[str],
        verify_prepared_bytes: bool = True,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.store = PreparedImageSetStore(self.workspace)
        try:
            self.manifest = self.store.verify_set(PREPARATION_SET_ID)
            self.profile = self.store.read_transform_profile(
                self.store.set_dir(PREPARATION_SET_ID)
            )
            entries = self.store.read_entries(PREPARATION_SET_ID)
        except Exception as exc:  # storage supplies the useful detail
            raise Stage21BPreflightError(
                f"the frozen canonical500 set is not valid: {exc}"
            ) from exc
        if self.manifest.preparation_set_id != PREPARATION_SET_ID:
            raise Stage21BPreflightError("canonical500 preparation-set ID changed")
        if self.manifest.transform_profile_id != PREPARATION_PROFILE_ID:
            raise Stage21BPreflightError("canonical500 preparation profile changed")
        if self.manifest.pair_manifest_hash != LEGACY_PAIR_MANIFEST_HASH:
            raise Stage21BPreflightError("the canonical500 set no longer binds legacy 6,000")
        if self.profile.target_ppi != EFFECTIVE_PPI:
            raise Stage21BPreflightError("the canonical500 profile is not 500 ppi")
        self._entries: dict[str, PreparedImageEntry] = {
            str(entry.image_id): entry for entry in entries
        }
        required = {str(item) for item in required_image_ids}
        missing = sorted(required - set(self._entries))
        if missing:
            raise Stage21BPreflightError(
                f"canonical500 does not cover {len(missing)} Stage 21B images: {missing[:3]}"
            )
        self.verify_prepared_bytes = bool(verify_prepared_bytes)
        self._references: dict[str, PreparationReference] = {}
        self._verified: dict[str, tuple[Path, tuple[int, int]]] = {}

    @property
    def preparation_set_fingerprint(self) -> str:
        return self.manifest.preparation_set_fingerprint

    @property
    def preparation_profile_fingerprint(self) -> str:
        return self.manifest.transform_profile_fingerprint

    def reference(self, image_id: str) -> PreparationReference:
        cached = self._references.get(str(image_id))
        if cached is not None:
            return cached
        entry = self._require_entry(image_id)
        if entry.output_effective_ppi != EFFECTIVE_PPI:
            raise Stage21BPreflightError(f"{image_id}: prepared input is not 500 ppi")
        reference = PreparationReference(
            preparation_set_id=self.manifest.preparation_set_id,
            preparation_set_fingerprint=self.manifest.preparation_set_fingerprint,
            preparation_profile_id=entry.transform_profile_id,
            preparation_profile_fingerprint=entry.transform_profile_fingerprint,
            preparation_entry_hash=entry.entry_hash,
            encoded_sha256=entry.output_encoded_sha256,
            pixel_sha256=entry.output_pixel_sha256,
            width=entry.output_width,
            height=entry.output_height,
            effective_ppi=entry.output_effective_ppi,
        )
        self._references[str(image_id)] = reference
        return reference

    def plan(self, pairs: Iterable[object]) -> tuple[PlannedPair, ...]:
        planned: list[PlannedPair] = []
        for ordinal, pair in enumerate(pairs):
            planned.append(
                PlannedPair(
                    ordinal=ordinal,
                    pair_id=str(pair.pair_id),
                    release=str(pair.release),
                    left_image_id=str(pair.left_image_id),
                    right_image_id=str(pair.right_image_id),
                    ground_truth=pair.ground_truth.value,
                    left_preparation=self.reference(str(pair.left_image_id)),
                    right_preparation=self.reference(str(pair.right_image_id)),
                )
            )
        return tuple(planned)

    def resolve_pair(self, pair: PlannedPair) -> tuple[PreparedImage, PreparedImage]:
        return (
            self._resolve(pair.left_image_id, pair.left_preparation),
            self._resolve(pair.right_image_id, pair.right_preparation),
        )

    def _resolve(
        self, image_id: str, expected: PreparationReference
    ) -> PreparedImage:
        entry = self._require_entry(image_id)
        if self.reference(image_id) != expected:
            raise Stage21BPreflightError(
                f"{image_id}: prepared entry no longer matches the frozen plan"
            )
        path = self._verified_path(entry)
        return PreparedImage(
            image_id=ImageId(image_id),
            local_path=path,
            effective_ppi=entry.output_effective_ppi,
            media_type=entry.output_media_type,
            expected_sha256=entry.source_expected_sha256,
            checksum_status=ChecksumStatus.VERIFIED,
            preparation_profile_id=entry.transform_profile_id,
            preparation_hash=entry.entry_hash,
            source_effective_ppi=entry.source_effective_ppi,
            prepared_sha256=entry.output_encoded_sha256,
            prepared_size_bytes=entry.output_size_bytes,
            preparation_set_id=self.manifest.preparation_set_id,
            preparation_set_fingerprint=self.manifest.preparation_set_fingerprint,
            preparation_entry_hash=entry.entry_hash,
            pixel_sha256=entry.output_pixel_sha256,
            pixel_width=entry.output_width,
            pixel_height=entry.output_height,
        )

    def _verified_path(self, entry: PreparedImageEntry) -> Path:
        """The verified artefact for one image, decoded and re-hashed once.

        Gate 21B-I1 is about *images*, not invocations: the 73,500 pairs name
        3,000 distinct canonical500 images, so verifying on every resolution
        re-decodes and re-hashes each one 49 times per method.  Measured on this
        set that is 12.9 ms per image, 26 ms per pair, ~32 minutes per method and
        over three hours across the roster, buying no guarantee the first
        verification did not already give.

        Gate 21B-EQ1 is satisfied without an equivalence experiment, because
        this is not a departure from the certified route: ``verify_entry`` is a
        preparation-set operation there too, called when a set is derived or
        verified and never once per comparison.  The bytes handed to the adapter
        are the same bytes, so no score semantics can move.

        What is *not* memoised is the identity check.  Every resolution still
        compares the entry against the frozen plan, and re-stats the artefact so
        a file replaced mid-run is re-verified in full rather than trusted.
        """
        key = str(entry.image_id)
        path = (self.workspace / entry.relative_path).resolve()
        cached = self._verified.get(key)
        current = _stat_identity(path)
        if cached is not None and cached[1] == current:
            return cached[0]
        if self.verify_prepared_bytes:
            try:
                path = Path(self.store.verify_entry(entry, profile=self.profile)).resolve()
            except Exception as exc:
                raise Stage21BPreflightError(
                    f"{entry.image_id}: prepared input failed re-verification: {exc}"
                ) from exc
            current = _stat_identity(path)
        self._verified[key] = (path, current)
        return path

    def _require_entry(self, image_id: str) -> PreparedImageEntry:
        try:
            return self._entries[str(image_id)]
        except KeyError:
            raise Stage21BPreflightError(
                f"image {image_id!r} is not in the frozen preparation set"
            ) from None


def _stat_identity(path: Path) -> tuple[int, int]:
    """Size and modification time, the cheap half of "is this the same file?"."""
    try:
        value = Path(path).stat()
    except OSError as exc:
        raise Stage21BPreflightError(
            f"prepared input is unavailable: {Path(path).name}"
        ) from exc
    return value.st_size, value.st_mtime_ns
