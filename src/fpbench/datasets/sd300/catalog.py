"""The SD300 dataset provider.

Turns the directory tree NIST ships into :class:`ImageRecord` values, and
reports how well that tree matches its own declarations. It does not select
subjects, build pairs, load pixels or know that any algorithm exists.

Expected layout, per the SD300 READMEs::

    <root>/<release_directory>/images/<ppi>/<format>/plain/*.png
    <root>/<release_directory>/images/<ppi>/<format>/roll/*.png
    <root>/<release_directory>/images/<ppi>/checksum_<ppi>_<format>_<impression>.csv
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from fpbench.core.enums import ChecksumStatus, Impression
from fpbench.core.errors import ConfigurationError, DatasetLayoutError
from fpbench.core.identifiers import ImageId, SubjectId, compose_id
from fpbench.core.models import ImageRecord
from fpbench.datasets.base import (
    DatasetProvider,
    DatasetSpec,
    DatasetValidationReport,
    Severity,
    ValidationIssue,
)
from fpbench.datasets.sd300 import checksums, ppi_policy
from fpbench.datasets.sd300.filenames import SD300Filename, try_parse
from fpbench.datasets.sd300.finger_mapping import resolve_position
from fpbench.datasets.sd300.validation import (
    IssueCode,
    iter_image_files,
    load_header,
    validate_file,
)

__all__ = ["SD300ReleaseLayout", "SD300DatasetProvider", "DEFAULT_RELEASE_DIRECTORIES"]

DEFAULT_RELEASE_DIRECTORIES: Mapping[str, str] = {
    "SD300A": "sd300a",
    "SD300B": "sd300b",
    "SD300C": "sd300c",
}


@dataclass(frozen=True, slots=True)
class SD300ReleaseLayout:
    """Where one release's files live, relative to the dataset root."""

    release: str
    directory: str
    image_format: str = "png"

    @property
    def nominal_ppi(self) -> int:
        return ppi_policy.nominal_ppi(self.release)

    @property
    def effective_ppi(self) -> int:
        return ppi_policy.effective_ppi(self.release)

    def images_directory(self, root: Path) -> Path:
        return root / self.directory / "images" / str(self.nominal_ppi)

    def impression_directory(self, root: Path, impression: Impression) -> Path:
        return self.images_directory(root) / self.image_format / impression.value

    def checksum_path(self, root: Path, impression: Impression) -> Path:
        return self.images_directory(root) / checksums.checksum_filename(
            self.nominal_ppi, impression, self.image_format
        )


class SD300DatasetProvider(DatasetProvider):
    """Describes NIST Special Database 300 releases A, B and C."""

    dataset_id = "sd300"

    def __init__(
        self,
        root: Path,
        layouts: Sequence[SD300ReleaseLayout],
    ) -> None:
        """Configure releases; scans always validate each small PNG header."""
        self.root = Path(root)
        self._layouts: dict[str, SD300ReleaseLayout] = {
            layout.release: layout for layout in layouts
        }
        if not self._layouts:
            raise ConfigurationError("SD300 provider configured with no releases")

    # ------------------------------------------------------------------ setup

    @classmethod
    def from_spec(cls, spec: DatasetSpec) -> "SD300DatasetProvider":
        options: Mapping[str, Any] = spec.options or {}
        image_format = str(options.get("image_format", "png")).lower()

        declared = options.get("releases")
        if declared is None:
            declared = {
                release: {"directory": directory}
                for release, directory in DEFAULT_RELEASE_DIRECTORIES.items()
            }
        if not isinstance(declared, Mapping):
            raise ConfigurationError(
                "dataset.options.releases must be a mapping of release -> settings"
            )

        layouts = []
        for release, settings in declared.items():
            settings = settings or {}
            if not isinstance(settings, Mapping):
                raise ConfigurationError(
                    f"dataset.options.releases.{release} must be a mapping"
                )
            ppi_policy.nominal_ppi(release)  # rejects unknown releases early
            layouts.append(
                SD300ReleaseLayout(
                    release=release,
                    directory=str(
                        settings.get(
                            "directory",
                            DEFAULT_RELEASE_DIRECTORIES.get(
                                release, release.lower()
                            ),
                        )
                    ),
                    image_format=str(settings.get("image_format", image_format)).lower(),
                )
            )

        return cls(
            root=spec.root,
            layouts=layouts,
        )

    @property
    def releases(self) -> tuple[str, ...]:
        return tuple(self._layouts)

    def layout(self, release: str) -> SD300ReleaseLayout:
        try:
            return self._layouts[release]
        except KeyError:
            raise ConfigurationError(
                f"release {release!r} is not configured; have {list(self._layouts)}"
            ) from None

    # ----------------------------------------------------------------- public

    def scan(
        self, release: str, *, verify_checksums: bool = False
    ) -> Iterator[ImageRecord]:
        """Yield one audited record per officially declared image.

        Files whose names cannot be parsed are skipped here and reported by
        :meth:`validate`: a record that cannot be described faithfully is worse
        than a missing one. PNG headers are always validated. Set
        ``verify_checksums`` to hash the bytes and persist VERIFIED/MISMATCH
        evidence; the default still records NIST's expected digest without
        reading all image bytes.
        """
        for record, _ in self._walk(
            release, read_header=True, verify_checksum=verify_checksums
        ):
            if record is not None:
                yield record

    def validate(self, release: str) -> DatasetValidationReport:
        """Check names, layout and PNG headers for every file in ``release``."""
        issues: list[ValidationIssue] = []
        checked = 0
        for _, file_issues in self._walk(
            release, read_header=True, verify_checksum=False
        ):
            checked += 1
            issues.extend(file_issues)

        issues.extend(self._validate_layout(release))
        return DatasetValidationReport(
            dataset_id=self.dataset_id,
            release=release,
            checked_files=checked,
            issues=tuple(issues),
        )

    def verify_checksums(
        self, release: str, impressions: Sequence[Impression] | None = None
    ) -> tuple[ValidationIssue, ...]:
        """Hash every file and compare against NIST's manifest.

        Expensive — roughly 38 GB per release — and therefore never called by
        :meth:`validate`. Run it once on delivery, not on every experiment.
        """
        layout = self.layout(release)
        issues: list[ValidationIssue] = []
        for impression in impressions or tuple(Impression):
            directory = layout.impression_directory(self.root, impression)
            expected = checksums.load_checksums(
                layout.checksum_path(self.root, impression)
            )
            for filename, actual, reason in checksums.iter_mismatches(
                directory, expected
            ):
                issues.append(
                    ValidationIssue(
                        code=reason,
                        severity=Severity.ERROR,
                        detail=(
                            f"expected {expected.get(filename, '-')}, "
                            f"got {actual or 'missing'}"
                        ),
                        relative_path=self._relative(directory / filename),
                    )
                )
        return tuple(issues)

    # ---------------------------------------------------------------- internal

    def _walk(
        self, release: str, *, read_header: bool, verify_checksum: bool = False
    ) -> Iterator[tuple[ImageRecord | None, tuple[ValidationIssue, ...]]]:
        """Single traversal shared by :meth:`scan` and :meth:`validate`."""
        layout = self.layout(release)
        for impression in Impression:
            directory = layout.impression_directory(self.root, impression)
            if not directory.is_dir():
                continue
            try:
                expected = checksums.load_checksums(
                    layout.checksum_path(self.root, impression)
                )
            except DatasetLayoutError:
                expected = {}
            for path in iter_image_files(directory, layout.image_format):
                yield self._build(
                    release,
                    layout,
                    path,
                    expected_sha256=expected.get(path.name),
                    read_header=read_header,
                    verify_checksum=verify_checksum,
                )

    def _build(
        self,
        release: str,
        layout: SD300ReleaseLayout,
        path: Path,
        *,
        expected_sha256: str | None,
        read_header: bool,
        verify_checksum: bool,
    ) -> tuple[ImageRecord | None, tuple[ValidationIssue, ...]]:
        relative = self._relative(path)
        parsed: SD300Filename | None = try_parse(path.name)
        header, header_error = load_header(path) if read_header else (None, None)
        issues = validate_file(
            release=release,
            relative_path=relative,
            parsed=parsed,
            header=header,
            header_error=header_error,
        )
        issues = list(issues)
        checksum_status = ChecksumStatus.NOT_VERIFIED
        if expected_sha256 is None:
            issues.append(
                ValidationIssue(
                    code=IssueCode.CHECKSUM_NOT_DECLARED,
                    severity=Severity.ERROR,
                    detail="image is absent from the official NIST checksum manifest",
                    relative_path=relative,
                )
            )
        elif verify_checksum:
            actual_sha256 = checksums.sha256_file(path)
            if actual_sha256 == expected_sha256:
                checksum_status = ChecksumStatus.VERIFIED
            else:
                checksum_status = ChecksumStatus.MISMATCH
                issues.append(
                    ValidationIssue(
                        code=IssueCode.CHECKSUM_MISMATCH,
                        severity=Severity.ERROR,
                        detail=f"expected {expected_sha256}, got {actual_sha256}",
                        relative_path=relative,
                    )
                )

        if parsed is None or expected_sha256 is None:
            return None, tuple(issues)

        resolution = resolve_position(parsed.impression, parsed.frgp)
        suffix = (
            resolution.position.label
            if resolution.position is not None
            else f"frgp{parsed.frgp:02d}"
        )
        metadata_ppi = header.ppi if header is not None else None

        record = ImageRecord(
            image_id=ImageId(
                compose_id(release, parsed.subject, parsed.impression.value, suffix)
            ),
            dataset_id=self.dataset_id,
            release=release,
            subject_id=SubjectId(parsed.subject),
            impression=parsed.impression,
            position=resolution.position,
            is_multi_finger=resolution.is_multi_finger,
            relative_path=relative,
            effective_ppi=layout.effective_ppi,
            expected_sha256=expected_sha256,
            metadata_ppi=metadata_ppi,
            checksum_status=checksum_status,
            metadata={
                "frgp": f"{parsed.frgp:02d}",
                "filename_ppi": str(parsed.ppi),
                "image_format": layout.image_format,
            },
            anomalies=tuple(
                issue.code for issue in issues if issue.severity is not Severity.ERROR
            ),
            blocking_issues=tuple(
                issue.code for issue in issues if issue.severity is Severity.ERROR
            ),
        )
        return record, tuple(issues)

    def _relative(self, path: Path) -> str:
        """Path from the dataset root, POSIX-style, so manifests stay portable."""
        return path.relative_to(self.root).as_posix()

    def _validate_layout(self, release: str) -> list[ValidationIssue]:
        layout = self.layout(release)
        issues: list[ValidationIssue] = []
        images_dir = layout.images_directory(self.root)
        if not images_dir.is_dir():
            raise DatasetLayoutError(
                f"{release}: expected image directory not found: {images_dir}"
            )
        for impression in Impression:
            directory = layout.impression_directory(self.root, impression)
            if not directory.is_dir():
                issues.append(
                    ValidationIssue(
                        code="missing_impression_directory",
                        severity=Severity.ERROR,
                        detail=f"{impression.value} directory not found",
                        relative_path=self._relative_or_none(directory),
                    )
                )
            checksum_path = layout.checksum_path(self.root, impression)
            if not checksum_path.is_file():
                issues.append(
                    ValidationIssue(
                        code=IssueCode.CHECKSUM_MANIFEST_MISSING,
                        severity=Severity.ERROR,
                        detail="NIST checksum manifest not present",
                        relative_path=self._relative_or_none(checksum_path),
                    )
                )
                continue
            try:
                expected = checksums.load_checksums(checksum_path)
            except DatasetLayoutError as exc:
                issues.append(
                    ValidationIssue(
                        code=IssueCode.CHECKSUM_MANIFEST_INVALID,
                        severity=Severity.ERROR,
                        detail=str(exc),
                        relative_path=self._relative_or_none(checksum_path),
                    )
                )
                continue
            if directory.is_dir():
                present = {
                    path.name
                    for path in iter_image_files(directory, layout.image_format)
                }
                for filename in sorted(set(expected) - present):
                    issues.append(
                        ValidationIssue(
                            code=IssueCode.CHECKSUM_DECLARED_FILE_MISSING,
                            severity=Severity.ERROR,
                            detail="file declared by NIST checksum manifest is missing",
                            relative_path=self._relative_or_none(directory / filename),
                        )
                    )
        return issues

    def _relative_or_none(self, path: Path) -> str | None:
        try:
            return self._relative(path)
        except ValueError:
            return None
