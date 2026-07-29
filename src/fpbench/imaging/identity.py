"""The preparer that changes nothing.

It resolves an image record to a file on disk, checks that the file is really
there and really inside the dataset root, and hands the adapter the original
bytes untouched. No pixels are decoded, no header is rewritten, no temporary
copy is made — SD300 as delivered is what the matcher sees.

That is the correct default for stage 3A. Every later transformation (2000 ppi
down to 500, format conversion for a matcher that cannot read PNG) becomes a
*different* preparer with a different ``preparer_id``, so a result can always
say which one produced it. Silently changing what this one does would make old
and new results incomparable while looking identical.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from fpbench.core.enums import ChecksumStatus
from fpbench.core.errors import ImagePreparationError
from fpbench.core.execution_models import ExecutionProfile, PreparedImage
from fpbench.core.models import ImageRecord
from fpbench.core.serialization import stable_hash
from fpbench.imaging.base import ImagePreparer

__all__ = ["IdentityImagePreparer", "PREPARER_ID", "PREPARER_VERSION"]

PREPARER_ID = "identity"

#: Bumped whenever the meaning of the output changes. It is part of
#: ``preparation_hash``, so a bump makes every prepared image visibly different
#: from one prepared by the previous version.
PREPARER_VERSION = "1"

#: The identity preparer passes bytes through untouched, so it can only serve
#: formats an adapter is expected to read directly.
_MEDIA_TYPES = {".png": "image/png"}


class IdentityImagePreparer(ImagePreparer):
    """Passes the dataset's own file through, unmodified."""

    @property
    def preparer_id(self) -> str:
        return PREPARER_ID

    def prepare(
        self,
        image: ImageRecord,
        dataset_root: Path,
        profile: ExecutionProfile,
    ) -> PreparedImage:
        if not image.is_usable:
            raise ImagePreparationError(
                f"{image.image_id}: image is blocked by validation "
                f"({', '.join(image.blocking_issues) or image.checksum_status.value})"
            )

        # Path safety is checked before anything else. A traversal attempt or an
        # absolute path must be rejected as such, not incidentally rejected
        # later for having the wrong file extension.
        local_path = self._resolve(image, Path(dataset_root))
        media_type = self._media_type(image)

        return PreparedImage(
            image_id=image.image_id,
            local_path=local_path,
            effective_ppi=image.effective_ppi,
            media_type=media_type,
            expected_sha256=image.expected_sha256,
            checksum_status=image.checksum_status,
            preparation_profile_id=profile.profile_id,
            preparation_hash=self._preparation_hash(image, media_type),
        )

    # ---------------------------------------------------------------- helpers

    def _media_type(self, image: ImageRecord) -> str:
        suffix = PurePosixPath(image.relative_path).suffix.lower()
        try:
            return _MEDIA_TYPES[suffix]
        except KeyError:
            raise ImagePreparationError(
                f"{image.image_id}: the identity preparer does not handle "
                f"{suffix or 'files without a suffix'}; a converting preparer is needed"
            ) from None

    def _resolve(self, image: ImageRecord, dataset_root: Path) -> Path:
        relative = image.relative_path
        # Joining an absolute path onto a root silently discards the root, so
        # this has to be rejected before the join rather than after it.
        if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).is_absolute():
            raise ImagePreparationError(
                f"{image.image_id}: relative_path must be relative, got {relative!r}"
            )

        root = dataset_root.resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ImagePreparationError(
                f"{image.image_id}: {relative!r} resolves outside the dataset root"
            )
        if not candidate.exists():
            raise ImagePreparationError(f"{image.image_id}: file not found: {relative}")
        if not candidate.is_file():
            raise ImagePreparationError(
                f"{image.image_id}: {relative} is not a regular file"
            )
        return candidate

    def _preparation_hash(self, image: ImageRecord, media_type: str) -> str:
        """Identifies what the adapter will receive, independent of where it lives.

        The absolute path is deliberately excluded. Two machines with the
        dataset unpacked in different directories must produce byte-identical
        prepared images, or nothing downstream is portable.
        """
        return stable_hash(
            {
                "schema": "preparation_hash_v1",
                "preparer_id": PREPARER_ID,
                "preparer_version": PREPARER_VERSION,
                "image_id": str(image.image_id),
                "expected_sha256": image.expected_sha256,
                "checksum_status": ChecksumStatus(image.checksum_status).value,
                "effective_ppi": image.effective_ppi,
                "media_type": media_type,
            },
            length=64,
        )
