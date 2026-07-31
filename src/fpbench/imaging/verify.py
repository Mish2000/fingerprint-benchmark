"""Re-deriving a prepared-image set instead of believing it.

The store can check that a set is internally consistent: right ordinals, right
ordered hash, every artefact still hashing to its own name. It cannot check that
the artefacts are the *right* artefacts, because that means going back to the
source images and doing the transformation again.

This module does that. It is the difference between "these 3,000 files are
undisturbed" and "these 3,000 files are what
``canonical_gray8_500ppi_lanczos3_v1`` produces from this dataset", and only the
second is evidence (docs/adr/0033).

Two depths, named rather than implied:

``verify_prepared_artifacts``
    Everything reachable without the dataset: the manifest, the profile, the
    runtime, the definition, every entry hash, the ordered-entries hash, the set
    fingerprint, the receipt's claims, the marker's claims, and every canonical
    PNG's bytes, container and decoded raster. This is what a *run* checks before
    and after each batch, because a run has the workspace and does not need to
    re-hash 10 GB of NIST delivery to find out that a PNG moved.

``verify_prepared_image_set``
    All of the above, plus every source file: its digest against the manifest,
    its container against the profile's input contract, its raster against the
    entry's recorded source pixel hash, and — for the identity path — that the
    canonical raster is still byte for byte the source raster. This is what
    ``status`` and ``finalize`` run.

Neither re-runs the resampler by default. Re-deriving 3,000 Lanczos passes to
confirm they produce the pixel hashes already recorded is available behind
``recompute_pixels`` and is what the golden fixtures exercise cheaply on every
CI run; making it the default would turn verification into materialisation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fpbench.core.enums import ChecksumStatus
from fpbench.core.errors import ImagingError, StorageError
from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import (
    ImageTransformProfile,
    PreparationDefinition,
    PreparedImageEntry,
    PreparedImageSetManifest,
    TransformRuntimeManifest,
    ordered_prepared_entries_hash,
    preparation_finalization_fingerprint,
    preparation_receipt_content_hash,
    preparation_receipt_fingerprint,
    preparation_set_fingerprint,
    preparation_set_id,
    prepared_image_entry_hash,
)
from fpbench.core.models import ImageRecord
from fpbench.imaging.canonical import canonicalise, read_source_raster
from fpbench.imaging.source_records import (
    resolve_source_path,
    source_record_fingerprint,
)
from fpbench.storage.prepared_image_set_store import (
    PreparedImageSetStore,
    preparation_summary_content_hash,
)

__all__ = [
    "PreparedSetVerification",
    "verify_prepared_artifacts",
    "verify_prepared_image_set",
]


@dataclass(frozen=True, slots=True)
class PreparedSetVerification:
    """What a verification pass found. Never raises for a damaged set.

    The damage is the answer, in the same style as
    :meth:`RuntimeBundleStore.verify_bundle`. It raises only when the manifest
    itself cannot be read, because then there is no claim to check against.
    """

    preparation_set_id: str
    preparation_set_fingerprint: str

    total_entries: int
    verified_entries: int
    verified_sources: int
    recomputed_pixels: int

    checked_sources: bool
    checked_receipt: bool
    checked_finalization: bool

    issues: tuple[str, ...]
    inspected_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_valid(self) -> bool:
        return not self.issues


def verify_prepared_artifacts(
    *,
    store: PreparedImageSetStore,
    preparation_set_id_value: str,
    require_receipt: bool = True,
    require_finalization: bool = True,
) -> PreparedSetVerification:
    """Re-check everything that does not need the dataset."""
    return _verify(
        store=store,
        preparation_set_id_value=preparation_set_id_value,
        images=None,
        dataset_root=None,
        recompute_pixels=False,
        require_receipt=require_receipt,
        require_finalization=require_finalization,
    )


def verify_prepared_image_set(
    *,
    store: PreparedImageSetStore,
    preparation_set_id_value: str,
    images: Mapping[ImageId, ImageRecord],
    dataset_root: Path,
    recompute_pixels: bool = False,
    require_receipt: bool = True,
    require_finalization: bool = True,
) -> PreparedSetVerification:
    """Re-check everything, sources included.

    Args:
        recompute_pixels: Also re-run the transformation on every source and
            compare the resulting pixel hash. Correct and slow — 3,000 Lanczos
            passes — so it is off by default and on in the smoke tests, where
            the point is precisely to prove the resampler still agrees with what
            it wrote.
    """
    return _verify(
        store=store,
        preparation_set_id_value=preparation_set_id_value,
        images=dict(images),
        dataset_root=Path(dataset_root),
        recompute_pixels=recompute_pixels,
        require_receipt=require_receipt,
        require_finalization=require_finalization,
    )


# ----------------------------------------------------------------- internals


def _verify(
    *,
    store: PreparedImageSetStore,
    preparation_set_id_value: str,
    images: Mapping[ImageId, ImageRecord] | None,
    dataset_root: Path | None,
    recompute_pixels: bool,
    require_receipt: bool,
    require_finalization: bool,
) -> PreparedSetVerification:
    manifest = store.read_manifest(preparation_set_id_value)
    container = store.set_dir(preparation_set_id_value)

    issues: list[str] = []
    verified_entries = 0
    verified_sources = 0
    recomputed = 0

    try:
        profile = store.read_transform_profile(container)
        runtime = store.read_runtime(container)
        definition = store.read_definition(container)
        entries = store.read_entries(preparation_set_id_value)
    except StorageError as exc:
        return PreparedSetVerification(
            preparation_set_id=manifest.preparation_set_id,
            preparation_set_fingerprint=manifest.preparation_set_fingerprint,
            total_entries=0,
            verified_entries=0,
            verified_sources=0,
            recomputed_pixels=0,
            checked_sources=images is not None,
            checked_receipt=False,
            checked_finalization=False,
            issues=(str(exc),),
            inspected_utc=_utc_now(),
        )

    issues.extend(_check_identity(manifest, entries, profile, runtime, definition))

    for entry in entries:
        try:
            store.verify_entry(entry, profile=profile)
            verified_entries += 1
        except (StorageError, ImagingError) as exc:
            issues.append(str(exc))
            continue

        recomputed_hash = prepared_image_entry_hash(entry)
        if recomputed_hash != entry.entry_hash:  # pragma: no cover - the model checks
            issues.append(f"{entry.image_id}: entry hash does not cover its own fields")

        if images is None or dataset_root is None:
            continue

        source_issues, verified, recomputed_here = _check_source(
            entry=entry,
            images=images,
            dataset_root=dataset_root,
            profile=profile,
            recompute_pixels=recompute_pixels,
        )
        issues.extend(source_issues)
        verified_sources += verified
        recomputed += recomputed_here

    checked_receipt = False
    if require_receipt or store.has_receipt(preparation_set_id_value):
        checked_receipt = True
        issues.extend(
            _check_receipt(store, manifest, entries, profile, runtime, images)
        )

    checked_finalization = False
    if require_finalization or store.has_finalization(preparation_set_id_value):
        checked_finalization = True
        issues.extend(_check_finalization(store, manifest, profile, runtime))

    return PreparedSetVerification(
        preparation_set_id=manifest.preparation_set_id,
        preparation_set_fingerprint=manifest.preparation_set_fingerprint,
        total_entries=len(entries),
        verified_entries=verified_entries,
        verified_sources=verified_sources,
        recomputed_pixels=recomputed,
        checked_sources=images is not None,
        checked_receipt=checked_receipt,
        checked_finalization=checked_finalization,
        issues=tuple(issues),
        inspected_utc=_utc_now(),
    )


def _check_identity(
    manifest: PreparedImageSetManifest,
    entries: tuple[PreparedImageEntry, ...],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    definition: PreparationDefinition,
) -> list[str]:
    issues: list[str] = []

    if manifest.total_images != len(entries):
        issues.append(
            f"the manifest declares {manifest.total_images} images but the set "
            f"holds {len(entries)}"
        )

    ordered = ordered_prepared_entries_hash(entries)
    if ordered != manifest.ordered_entries_hash:
        issues.append(
            "the manifest's ordered-entries hash does not cover the stored entries"
        )

    fingerprint = preparation_set_fingerprint(
        dataset_id=manifest.dataset_id,
        image_manifest_hash=manifest.image_manifest_hash,
        protocol_id=manifest.protocol_id,
        cohort_id=manifest.cohort_id,
        cohort_fingerprint=manifest.cohort_fingerprint,
        pair_manifest_hash=manifest.pair_manifest_hash,
        transform_profile_fingerprint=manifest.transform_profile_fingerprint,
        transform_runtime_fingerprint=manifest.transform_runtime_fingerprint,
        entries=entries,
    )
    if fingerprint != manifest.preparation_set_fingerprint:
        issues.append(
            "the set does not fingerprint to the identity its manifest claims"
        )
    elif preparation_set_id(fingerprint) != manifest.preparation_set_id:
        issues.append("the manifest is stored under a foreign preparation-set id")

    if profile.profile_fingerprint != manifest.transform_profile_fingerprint:
        issues.append("the stored profile is not the profile the manifest names")
    if runtime.runtime_fingerprint != manifest.transform_runtime_fingerprint:
        issues.append("the stored runtime is not the runtime the manifest names")
    if definition.definition_fingerprint != _definition_fingerprint(definition):
        issues.append("the stored definition does not fingerprint to its own id")
    if list(definition.ordered_image_ids) != [entry.image_id for entry in entries]:
        issues.append(
            "the set does not hold exactly the images its definition promised"
        )

    missing = profile.missing_forbidden_operations()
    if missing:
        issues.append(
            "the stored profile does not forbid " + ", ".join(missing)
        )
    return issues


def _check_source(
    *,
    entry: PreparedImageEntry,
    images: Mapping[ImageId, ImageRecord],
    dataset_root: Path,
    profile: ImageTransformProfile,
    recompute_pixels: bool,
) -> tuple[list[str], int, int]:
    issues: list[str] = []
    record = images.get(entry.image_id)
    if record is None:
        return (
            [f"{entry.image_id}: the entry names an image that is not in the manifest"],
            0,
            0,
        )
    if source_record_fingerprint(record) != entry.source_record_fingerprint:
        issues.append(
            f"{entry.image_id}: the image manifest now describes a different record "
            "than the entry was produced from"
        )
    if record.expected_sha256 != entry.source_expected_sha256:
        issues.append(
            f"{entry.image_id}: the manifest's source digest is not the one the "
            "entry records"
        )
    if record.effective_ppi != entry.source_effective_ppi:
        issues.append(
            f"{entry.image_id}: the manifest records {record.effective_ppi} ppi, the "
            f"entry {entry.source_effective_ppi}"
        )
    if record.checksum_status is not ChecksumStatus.VERIFIED:
        issues.append(
            f"{entry.image_id}: the source carries no VERIFIED checksum evidence"
        )

    try:
        path = resolve_source_path(record, dataset_root)
        source = read_source_raster(path, profile=profile, image_label=str(entry.image_id))
    except (ImagingError, ValueError) as exc:
        return ([f"{entry.image_id}: {exc}"], 0, 0)

    if source.encoded_sha256 != entry.source_expected_sha256:
        issues.append(
            f"{entry.image_id}: the source file on disk hashes to "
            f"{source.encoded_sha256[:12]}..., the entry records "
            f"{entry.source_expected_sha256[:12]}..."
        )
    if source.size_bytes != entry.source_size_bytes:
        issues.append(
            f"{entry.image_id}: the source file is {source.size_bytes} bytes, the "
            f"entry records {entry.source_size_bytes}"
        )
    if (source.width, source.height) != (entry.source_width, entry.source_height):
        issues.append(
            f"{entry.image_id}: the source is {source.width}x{source.height}, the "
            f"entry records {entry.source_width}x{entry.source_height}"
        )
    if source.pixel_sha256 != entry.source_pixel_sha256:
        issues.append(
            f"{entry.image_id}: the source raster no longer hashes to what the entry "
            "records"
        )
    elif entry.is_identity and source.pixel_sha256 != entry.output_pixel_sha256:
        issues.append(
            f"{entry.image_id}: the identity path must preserve the raster exactly"
        )

    recomputed = 0
    if recompute_pixels and not issues:
        try:
            artifact = canonicalise(
                source,
                profile=profile,
                source_ppi=entry.source_effective_ppi,
                image_label=str(entry.image_id),
            )
        except ImagingError as exc:
            return (issues + [f"{entry.image_id}: {exc}"], 0, 0)
        recomputed = 1
        if artifact.pixel_sha256 != entry.output_pixel_sha256:
            issues.append(
                f"{entry.image_id}: re-running the transform produces raster "
                f"{artifact.pixel_sha256[:12]}..., the entry records "
                f"{entry.output_pixel_sha256[:12]}..."
            )
        if artifact.encoded_sha256 != entry.output_encoded_sha256:
            issues.append(
                f"{entry.image_id}: re-encoding produces a different file than the "
                "entry records; the encoder or its zlib changed"
            )
        if artifact.transform_action != entry.transform_action:
            issues.append(
                f"{entry.image_id}: re-running the transform names action "
                f"{artifact.transform_action!r}, the entry records "
                f"{entry.transform_action!r}"
            )

    return (issues, 1 if not issues else 0, recomputed)


def _check_receipt(
    store: PreparedImageSetStore,
    manifest: PreparedImageSetManifest,
    entries: tuple[PreparedImageEntry, ...],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    images: Mapping[ImageId, ImageRecord] | None,
) -> list[str]:
    """Re-derive the receipt and compare.

    One field cannot be re-derived without the image manifest: the per-release
    breakdown, because an entry deliberately carries no dataset semantics — it
    knows its source resolution, not which release the resolution came from. So
    an artefact-only pass checks every other field and requires the release
    counts to at least add up, while the deep pass, which has the manifest,
    re-derives them exactly.
    """
    from fpbench.experiments.preparation_receipt import (
        build_preparation_receipt,
        require_sanitised_receipt,
    )

    try:
        stored = store.read_receipt(manifest.preparation_set_id)
    except StorageError as exc:
        return [str(exc)]

    try:
        expected = build_preparation_receipt(
            manifest=manifest,
            entries=entries,
            profile=profile,
            runtime=runtime,
            images=images,
            created_utc=stored.created_utc,
        )
    except (ImagingError, ValueError) as exc:
        # A receipt that cannot even be re-derived from the set is a finding, not
        # a crash. The usual cause is a manifest and an entries table that no
        # longer agree with each other.
        return [f"the preparation receipt cannot be re-derived from the set ({exc})"]

    issues: list[str] = []
    if images is None:
        if sum(stored.counts_by_release.values()) != stored.total_images:
            issues.append(
                "the receipt's per-release counts do not add up to its total"
            )
        expected = _with_release_counts(expected, dict(stored.counts_by_release))

    if preparation_receipt_fingerprint(stored) != preparation_receipt_fingerprint(
        expected
    ):
        issues.append(
            "the stored preparation receipt does not match the set it claims to "
            "summarise"
        )
    try:
        require_sanitised_receipt(stored)
    except ImagingError as exc:
        issues.append(str(exc))
    return issues


def _with_release_counts(receipt, counts: Mapping[str, int]):
    """A copy of ``receipt`` with someone else's release breakdown substituted."""
    import dataclasses

    return dataclasses.replace(receipt, counts_by_release=dict(counts))


def _check_finalization(
    store: PreparedImageSetStore,
    manifest: PreparedImageSetManifest,
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
) -> list[str]:
    try:
        marker = store.read_finalization(manifest.preparation_set_id)
        receipt = store.read_receipt(manifest.preparation_set_id)
        summary = store.read_summary(manifest.preparation_set_id)
        entries_hash = store.entries_table_content_hash(manifest.preparation_set_id)
    except StorageError as exc:
        return [str(exc)]

    issues: list[str] = []
    expected = {
        "preparation_set_id": manifest.preparation_set_id,
        "preparation_set_fingerprint": manifest.preparation_set_fingerprint,
        "transform_profile_fingerprint": profile.profile_fingerprint,
        "transform_runtime_fingerprint": runtime.runtime_fingerprint,
        "entries_table_content_hash": entries_hash,
        "summary_content_hash": preparation_summary_content_hash(summary),
        "receipt_fingerprint": preparation_receipt_fingerprint(receipt),
        "receipt_content_hash": preparation_receipt_content_hash(receipt),
        "source_commit": runtime.source_revision,
        "source_tree_clean": runtime.source_tree_clean,
    }
    for name, value in expected.items():
        actual = getattr(marker, name)
        if actual != value:
            issues.append(
                f"the finalization marker's {name} is {actual!r}, expected {value!r}"
            )
    if not issues:
        recomputed = preparation_finalization_fingerprint(marker.claims())
        if recomputed != marker.finalization_fingerprint:  # pragma: no cover
            issues.append("the finalization marker does not cover its own claims")
    return issues


def _definition_fingerprint(definition: PreparationDefinition) -> str:
    from fpbench.core.imaging_models import preparation_definition_fingerprint

    return preparation_definition_fingerprint(definition)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
