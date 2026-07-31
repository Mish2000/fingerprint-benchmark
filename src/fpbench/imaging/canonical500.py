"""The preparer that looks things up instead of computing them.

This is the point of the whole stage. ``Canonical500ImagePreparer`` performs no
resampling, no decoding and no encoding. Every canonical pixel it hands to an
adapter was produced once, hours or months earlier, by
:mod:`fpbench.imaging.canonical`, verified, and filed under the digest of its own
bytes. All this class does is find the right entry, prove it is the right entry,
prove the file has not moved, and point at it.

That is what makes the fairness claim in docs/adr/0031 checkable rather than
aspirational. If resampling happened here it would happen once per comparison,
inside a run, under whichever algorithm's timing budget — and two algorithms
could be handed different pixels without anything recording that they were.
Because it happens beforehand, ``preparation_set_fingerprint`` is a single value
that either matches between two runs or does not.

Three checks, at three different costs:

**Once per run** (:meth:`preflight`) the whole set is verified: manifest,
profile, runtime, definition, every entry hash, the ordered-entries hash, the
set fingerprint, the receipt, the marker, and every canonical PNG's bytes and
decoded raster. A missing artefact stops the run before the first JVM starts.

**Once per prepared image** the entry is checked against the source record it
claims — digest, effective ppi, transform profile — so that an image manifest
rebuilt under a different resolution policy cannot silently be paired with
artefacts made under the old one.

**Once per comparison** a ``stat`` compares size, mtime and inode against the
snapshot preflight took. Cheap, and it catches the thing that actually happens:
someone regenerating a set in a second terminal while a run is going.

The threat model is accidental drift, not an adversary who mutates a file and
restores it between two ``stat`` calls. That is stated here rather than implied,
because the difference decides how much this class is worth (spec section 59).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from fpbench.core.enums import ChecksumStatus
from fpbench.core.errors import (
    ImagePreparationError,
    PreflightError,
    PreparedImageDriftError,
    StorageError,
)
from fpbench.core.execution_models import ExecutionProfile, PreparedImage
from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import PreparedImageEntry
from fpbench.core.models import ImageRecord
from fpbench.core.serialization import stable_hash
from fpbench.imaging.base import ImagePreparer
from fpbench.imaging.source_records import source_record_fingerprint
from fpbench.imaging.verify import verify_prepared_artifacts
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

__all__ = [
    "Canonical500ImagePreparer",
    "PREPARER_ID",
    "PREPARER_VERSION",
    "RUNNER_METADATA_SCHEMA",
    "RESOLUTION_MODE",
]

PREPARER_ID = "canonical_500_png"

#: Bumped whenever the meaning of this preparer's output changes. It is part of
#: ``preparation_hash`` and of every stored result, so a bump makes results
#: produced before and after visibly different.
PREPARER_VERSION = "1"

#: Names the exact key set a canonical result's ``runner_metadata`` carries, so
#: a validator can require every field rather than accept what is present.
RUNNER_METADATA_SCHEMA = "canonical_preparation_v1"

#: The value ``ExecutionProfile.parameters['resolution_mode']`` must hold.
RESOLUTION_MODE = "canonical_500"


class _FileIdentity:
    """What a cheap per-comparison check compares against.

    Deliberately not a digest. Re-hashing a 200 KB PNG twice per comparison,
    12,000 times a run, would cost more than the matcher does; the full digest
    runs before and after each batch instead.
    """

    __slots__ = ("size", "mtime_ns", "inode", "device")

    def __init__(self, path: Path) -> None:
        stat_result = path.stat()
        self.size = stat_result.st_size
        self.mtime_ns = stat_result.st_mtime_ns
        self.inode = stat_result.st_ino
        self.device = stat_result.st_dev

    def differences(self, other: "_FileIdentity") -> tuple[str, ...]:
        problems: list[str] = []
        if self.size != other.size:
            problems.append(f"size {other.size} != {self.size}")
        if self.mtime_ns != other.mtime_ns:
            problems.append("modification time changed")
        # Zero is what a filesystem reports when it has no such notion; comparing
        # it would produce a false alarm on every call.
        if self.inode and other.inode and self.inode != other.inode:
            problems.append("the path now names a different file")
        if self.device and other.device and self.device != other.device:
            problems.append("the file moved to a different device")
        return tuple(problems)


class Canonical500ImagePreparer(ImagePreparer):
    """Hands an adapter one immutable, pre-materialised canonical 500 ppi PNG."""

    def __init__(
        self,
        *,
        store: PreparedImageSetStore,
        preparation_set_id: str,
        preparation_set_fingerprint: str,
    ) -> None:
        self._store = store
        self._set_id = str(preparation_set_id)
        self._set_fingerprint = str(preparation_set_fingerprint)
        self._entries: dict[ImageId, PreparedImageEntry] = {}
        self._identities: dict[ImageId, _FileIdentity] = {}
        self._profile_id: str | None = None
        self._profile_fingerprint: str | None = None
        self._runtime_fingerprint: str | None = None
        self._target_ppi: int | None = None
        self._prepared = False

    @property
    def preparer_id(self) -> str:
        return PREPARER_ID

    @property
    def preparer_version(self) -> str:
        return PREPARER_VERSION

    @property
    def runner_metadata_schema(self) -> str:
        return RUNNER_METADATA_SCHEMA

    @property
    def preparation_set_id(self) -> str:
        return self._set_id

    @property
    def preparation_set_fingerprint(self) -> str:
        return self._set_fingerprint

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def prepared_entries(self) -> Mapping[ImageId, PreparedImageEntry]:
        """The verified entry index, for a validator that checks results against it.

        Read-only and only meaningful after :meth:`preflight`. Exposed rather
        than reached into, so that the result validator does not depend on this
        class's private state (spec section 75).
        """
        self._require_prepared()
        return dict(self._entries)

    # -------------------------------------------------------------- preflight

    def preflight(self) -> None:
        """Verify the whole set once, and snapshot every artefact's identity.

        Raises:
            PreflightError: the set is missing, does not verify, or is not the
                set this preparer was constructed for. Never a per-pair failure:
                6,000 identical ``PREPARATION_FAILED`` rows would describe the
                same single fault six thousand times (spec section 56).
        """
        try:
            manifest = self._store.read_manifest(self._set_id)
        except StorageError as exc:
            raise PreflightError(
                f"prepared-image set {self._set_id} cannot be read: {exc}"
            ) from exc

        if manifest.preparation_set_fingerprint != self._set_fingerprint:
            raise PreflightError(
                f"prepared-image set {self._set_id} fingerprints to "
                f"{manifest.preparation_set_fingerprint[:12]}..., but this run is "
                f"pinned to {self._set_fingerprint[:12]}...; a run may not straddle "
                "two input sets"
            )

        verification = verify_prepared_artifacts(
            store=self._store,
            preparation_set_id_value=self._set_id,
            require_receipt=True,
            require_finalization=True,
        )
        if not verification.is_valid:
            raise PreflightError(
                f"prepared-image set {self._set_id} did not verify: "
                f"{'; '.join(verification.issues[:3])}"
            )

        container = self._store.set_dir(self._set_id)
        profile = self._store.read_transform_profile(container)
        runtime = self._store.read_runtime(container)
        entries = self._store.read_entries(self._set_id)

        self._entries = {entry.image_id: entry for entry in entries}
        self._profile_id = profile.profile_id
        self._profile_fingerprint = profile.profile_fingerprint
        self._runtime_fingerprint = runtime.runtime_fingerprint
        self._target_ppi = profile.target_ppi

        self._identities = {}
        for entry in entries:
            path = self._store.root / entry.relative_path
            if path.is_symlink() or not path.is_file():
                raise PreflightError(
                    f"{entry.image_id}: the canonical artefact is not a regular file"
                )
            self._identities[entry.image_id] = _FileIdentity(path)

        self._prepared = True

    def require_expected_images(self, image_ids: set[ImageId]) -> None:
        """Prove the set covers exactly the images a run will ask for.

        Missing images stop the run. Extra images do not: a set materialised for
        a superset of experiments is precisely the reuse docs/adr/0033 is about.
        What is refused is a set that cannot answer a question the run will ask.
        """
        self._require_prepared()
        missing = sorted(str(item) for item in image_ids - set(self._entries))
        if missing:
            raise PreflightError(
                f"prepared-image set {self._set_id} holds no artefact for "
                f"{len(missing)} participating image(s), starting with "
                f"{missing[:3]}; materialise a set that covers this pair manifest"
            )

    # ---------------------------------------------------------------- metadata

    def run_metadata(self) -> Mapping[str, str]:
        self._require_prepared()
        return {
            "preparation_set_id": self._set_id,
            "preparation_set_fingerprint": self._set_fingerprint,
            "transform_profile_id": str(self._profile_id),
            "transform_profile_fingerprint": str(self._profile_fingerprint),
            "transform_runtime_fingerprint": str(self._runtime_fingerprint),
            "resolution_mode": RESOLUTION_MODE,
        }

    def side_metadata(self, prepared: PreparedImage) -> Mapping[str, str]:
        return {
            "preparation_entry_hash": str(prepared.preparation_entry_hash),
            "prepared_sha256": str(prepared.prepared_sha256),
            "pixel_sha256": str(prepared.pixel_sha256),
            "source_ppi": str(prepared.source_effective_ppi),
            "output_ppi": str(prepared.effective_ppi),
            "output_width": str(prepared.pixel_width),
            "output_height": str(prepared.pixel_height),
        }

    # ----------------------------------------------------------------- prepare

    def prepare(
        self,
        image: ImageRecord,
        dataset_root: Path,
        profile: ExecutionProfile,
    ) -> PreparedImage:
        """Look up, check, and point at the canonical artefact for ``image``.

        ``dataset_root`` is accepted and deliberately unused. The canonical
        artefact lives in the workspace, and reaching back into the delivery here
        is exactly the bypass docs/adr/0031 forbids: an algorithm must not be
        able to read the 2000 ppi original and step around the shared set.
        """
        self._require_prepared()
        image_id = image.image_id

        if not image.is_usable:
            raise ImagePreparationError(
                f"{image_id}: image is blocked by validation "
                f"({', '.join(image.blocking_issues) or image.checksum_status.value})"
            )

        entry = self._entries.get(image_id)
        if entry is None:
            raise ImagePreparationError(
                f"{image_id}: prepared-image set {self._set_id} holds no canonical "
                "artefact for this image"
            )

        self._require_matching_source(image, entry)
        self._require_matching_profile(entry, profile)

        path = (self._store.root / entry.relative_path).resolve()
        self._require_undisturbed(entry, path)

        return PreparedImage(
            image_id=image_id,
            local_path=path,
            effective_ppi=entry.output_effective_ppi,
            media_type=entry.output_media_type,
            # The publisher's digest of the *source*, kept under its historical
            # name. The file the adapter opens is prepared_sha256, below.
            expected_sha256=entry.source_expected_sha256,
            checksum_status=image.checksum_status,
            preparation_profile_id=profile.profile_id,
            preparation_hash=self._preparation_hash(entry, profile),
            source_effective_ppi=entry.source_effective_ppi,
            prepared_sha256=entry.output_encoded_sha256,
            prepared_size_bytes=entry.output_size_bytes,
            preparation_set_id=self._set_id,
            preparation_set_fingerprint=self._set_fingerprint,
            preparation_entry_hash=entry.entry_hash,
            pixel_sha256=entry.output_pixel_sha256,
            pixel_width=entry.output_width,
            pixel_height=entry.output_height,
        )

    # ---------------------------------------------------------------- internals

    def _require_prepared(self) -> None:
        if not self._prepared:
            raise PreflightError(
                f"prepared-image set {self._set_id} has not been verified; a "
                "canonical comparison cannot rest on an unchecked input set"
            )

    def _require_matching_source(
        self, image: ImageRecord, entry: PreparedImageEntry
    ) -> None:
        if image.expected_sha256 != entry.source_expected_sha256:
            raise ImagePreparationError(
                f"{image.image_id}: the image manifest's digest is not the one the "
                "canonical artefact was produced from"
            )
        if image.effective_ppi != entry.source_effective_ppi:
            raise ImagePreparationError(
                f"{image.image_id}: the manifest records {image.effective_ppi} ppi "
                f"but the artefact was scaled from {entry.source_effective_ppi}"
            )
        if image.checksum_status is not ChecksumStatus.VERIFIED:
            raise ImagePreparationError(
                f"{image.image_id}: the source carries no VERIFIED checksum evidence"
            )
        if source_record_fingerprint(image) != entry.source_record_fingerprint:
            raise ImagePreparationError(
                f"{image.image_id}: the image manifest now describes a different "
                "record than the canonical artefact was produced from"
            )

    def _require_matching_profile(
        self, entry: PreparedImageEntry, profile: ExecutionProfile
    ) -> None:
        parameters = profile.parameters
        for key, expected in (
            ("transform_profile_id", self._profile_id),
            ("transform_profile_fingerprint", self._profile_fingerprint),
            ("preparation_set_id", self._set_id),
            ("preparation_set_fingerprint", self._set_fingerprint),
        ):
            declared = parameters.get(key)
            if declared is None:
                raise ImagePreparationError(
                    f"execution profile {profile.profile_id} does not declare {key}; "
                    "a canonical run must name the exact input set it used"
                )
            if declared != expected:
                raise ImagePreparationError(
                    f"execution profile {profile.profile_id} declares {key}="
                    f"{declared[:16]}..., but this preparer serves "
                    f"{str(expected)[:16]}..."
                )
        if parameters.get("resolution_mode") != RESOLUTION_MODE:
            raise ImagePreparationError(
                f"execution profile {profile.profile_id} is not a {RESOLUTION_MODE} "
                "profile"
            )
        if entry.transform_profile_fingerprint != self._profile_fingerprint:
            raise ImagePreparationError(
                f"{entry.image_id}: the artefact was produced under a different "
                "transform profile than the set declares"
            )

    def _require_undisturbed(self, entry: PreparedImageEntry, path: Path) -> None:
        """The cheap per-comparison drift check.

        Raises:
            PreparedImageDriftError: the artefact changed. A
                :class:`RuntimeDriftError` subclass, so the runner's existing
                rule applies unchanged — re-raised unrecorded, fatal to the
                invocation, and not salvageable by a later run
                (docs/adr/0018, docs/adr/0033).
        """
        expected = self._identities.get(entry.image_id)
        if expected is None:  # pragma: no cover - preflight fills every entry
            raise PreparedImageDriftError(
                f"{entry.image_id}: no file identity was recorded at preflight"
            )
        if path.is_symlink():
            raise PreparedImageDriftError(
                f"{entry.image_id}: the canonical artefact is now a symlink"
            )
        try:
            current = _FileIdentity(path)
        except OSError as exc:
            raise PreparedImageDriftError(
                f"{entry.image_id}: the canonical artefact is no longer readable "
                f"({type(exc).__name__})"
            ) from exc
        differences = expected.differences(current)
        if differences:
            raise PreparedImageDriftError(
                f"{entry.image_id}: the canonical artefact changed during the run "
                f"({'; '.join(differences)}). Every result after this point would "
                "claim an input it did not have; a new preparation set and a new "
                "run are needed"
            )

    def _preparation_hash(
        self, entry: PreparedImageEntry, profile: ExecutionProfile
    ) -> str:
        """Identifies what the adapter will receive, independent of where it lives.

        Derived from the entry hash rather than equal to it, so that the same
        canonical artefact served by a future preparer version is visibly a
        different preparation (spec section 57).
        """
        return stable_hash(
            {
                "schema": "preparation_hash_v1",
                "preparer_id": PREPARER_ID,
                "preparer_version": PREPARER_VERSION,
                "image_id": str(entry.image_id),
                "preparation_set_fingerprint": self._set_fingerprint,
                "entry_hash": entry.entry_hash,
                "execution_profile_id": profile.profile_id,
            },
            length=64,
        )
