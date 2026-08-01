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
    re-read the 4.9 GB of NIST delivery behind the SD300 set to find out that a
    PNG moved. (The canonical artefacts it does re-read come to 662 MB.)

``verify_prepared_image_set``
    All of the above, plus every source file: its digest against the manifest,
    its container against the profile's input contract, its raster against the
    entry's recorded source pixel hash, and a fresh execution of the pinned
    transform whose dimensions, action, pixel hash and encoded hash must all
    agree. This is what ``status`` and ``finalize`` run by default. A caller may
    disable recomputation only for a faster diagnostic inspection.
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
    PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION,
    ImageTransformProfile,
    PreparationDefinition,
    PreparationSourceBundle,
    PreparationTransformAudit,
    PreparedImageEntry,
    PreparedImageSetManifest,
    TransformRuntimeManifest,
    ordered_prepared_entries_hash,
    preparation_finalization_fingerprint,
    preparation_receipt_content_hash,
    preparation_receipt_fingerprint,
    preparation_set_fingerprint,
    preparation_set_id,
    preparation_transform_audit_content_hash,
    preparation_transform_audit_fingerprint,
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
    "preparation_source_binding_issues",
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

    transform_audit: PreparationTransformAudit | None

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
    check_existing_publication: bool = True,
) -> PreparedSetVerification:
    """Re-check everything that does not need the dataset."""
    return _verify(
        store=store,
        preparation_set_id_value=preparation_set_id_value,
        images=None,
        dataset_root=None,
        source_bundle=None,
        recompute_pixels=False,
        require_receipt=require_receipt,
        require_finalization=require_finalization,
        check_existing_publication=check_existing_publication,
    )


def verify_prepared_image_set(
    *,
    store: PreparedImageSetStore,
    preparation_set_id_value: str,
    images: Mapping[ImageId, ImageRecord],
    dataset_root: Path,
    source_bundle: PreparationSourceBundle,
    recompute_pixels: bool = True,
    require_receipt: bool = True,
    require_finalization: bool = True,
    check_existing_publication: bool = True,
) -> PreparedSetVerification:
    """Re-check everything, sources included.

    Args:
        recompute_pixels: Re-run the transformation on every source and compare
            dimensions, action, pixel hash and encoded hash. This is on by
            default and mandatory for finalization; callers may disable it only
            for a faster diagnostic inspection.
    """
    return _verify(
        store=store,
        preparation_set_id_value=preparation_set_id_value,
        images=dict(images),
        dataset_root=Path(dataset_root),
        source_bundle=source_bundle,
        recompute_pixels=recompute_pixels,
        require_receipt=require_receipt,
        require_finalization=require_finalization,
        check_existing_publication=check_existing_publication,
    )


# ----------------------------------------------------------------- internals


def _verify(
    *,
    store: PreparedImageSetStore,
    preparation_set_id_value: str,
    images: Mapping[ImageId, ImageRecord] | None,
    dataset_root: Path | None,
    source_bundle: PreparationSourceBundle | None,
    recompute_pixels: bool,
    require_receipt: bool,
    require_finalization: bool,
    check_existing_publication: bool,
) -> PreparedSetVerification:
    manifest = store.read_manifest(preparation_set_id_value)
    container = store.set_dir(preparation_set_id_value)

    issues: list[str] = []
    verified_entries = 0
    verified_sources = 0
    recomputed = 0
    matching_dimensions = 0
    matching_actions = 0
    matching_pixels = 0
    matching_encoded = 0
    audit_issues: list[str] = []

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
            transform_audit=None,
            issues=(str(exc),),
            inspected_utc=_utc_now(),
        )

    issues.extend(_check_identity(manifest, entries, profile, runtime, definition))

    if images is not None or dataset_root is not None or source_bundle is not None:
        if images is None or dataset_root is None or source_bundle is None:
            issue = (
                "deep verification requires images, dataset_root and an "
                "authoritative source_bundle together"
            )
            issues.append(issue)
            audit_issues.append(issue)
        else:
            binding_issues = preparation_source_binding_issues(
                manifest=manifest,
                definition=definition,
                source_bundle=source_bundle,
            )
            issues.extend(binding_issues)
            audit_issues.extend(binding_issues)

    for entry in entries:
        try:
            store.verify_entry(entry, profile=profile)
            verified_entries += 1
        except (StorageError, ImagingError) as exc:
            issue = str(exc)
            issues.append(issue)
            if images is not None:
                audit_issues.append(issue)
            continue

        recomputed_hash = prepared_image_entry_hash(entry)
        if recomputed_hash != entry.entry_hash:  # pragma: no cover - the model checks
            issues.append(f"{entry.image_id}: entry hash does not cover its own fields")

        if images is None or dataset_root is None:
            continue

        source_check = _check_source(
            entry=entry,
            images=images,
            dataset_root=dataset_root,
            profile=profile,
            recompute_pixels=recompute_pixels,
        )
        issues.extend(source_check.issues)
        audit_issues.extend(source_check.issues)
        verified_sources += source_check.verified_source
        recomputed += source_check.recomputed_transform
        matching_dimensions += source_check.matching_output_dimensions
        matching_actions += source_check.matching_transform_action
        matching_pixels += source_check.matching_pixel_hash
        matching_encoded += source_check.matching_encoded_hash

    current_audit = None
    if (
        images is not None
        and dataset_root is not None
        and source_bundle is not None
        and recompute_pixels
    ):
        current_audit = _build_transform_audit(
            manifest=manifest,
            planned_images=len(entries),
            verified_sources=verified_sources,
            recomputed_transforms=recomputed,
            matching_output_dimensions=matching_dimensions,
            matching_transform_actions=matching_actions,
            matching_pixel_hashes=matching_pixels,
            matching_encoded_hashes=matching_encoded,
            issues=audit_issues,
        )

    stored_audit = None
    if (
        require_receipt
        or require_finalization
        or (
            check_existing_publication
            and store.has_transform_audit(preparation_set_id_value)
        )
    ):
        try:
            stored_audit = store.read_transform_audit(preparation_set_id_value)
        except StorageError as exc:
            issues.append(str(exc))
        else:
            if not stored_audit.is_clean:
                issues.append("the stored preparation transform audit is not clean")
            if (
                current_audit is not None
                and stored_audit.audit_fingerprint != current_audit.audit_fingerprint
            ):
                issues.append(
                    "the stored preparation transform audit does not match the "
                    "fresh source-to-output re-derivation"
                )

    checked_receipt = False
    if require_receipt or (
        check_existing_publication and store.has_receipt(preparation_set_id_value)
    ):
        checked_receipt = True
        issues.extend(
            _check_receipt(
                store, manifest, entries, profile, runtime, images, stored_audit
            )
        )

    checked_finalization = False
    if require_finalization or (
        check_existing_publication
        and store.has_finalization(preparation_set_id_value)
    ):
        checked_finalization = True
        issues.extend(
            _check_finalization(store, manifest, profile, runtime, stored_audit)
        )

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
        transform_audit=current_audit or stored_audit,
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


def preparation_source_binding_issues(
    *,
    manifest: PreparedImageSetManifest,
    definition: PreparationDefinition,
    source_bundle: PreparationSourceBundle,
) -> list[str]:
    """Compare stored identities to independently derived source manifests."""
    issues: list[str] = []
    expected = {
        "dataset_id": source_bundle.dataset_id,
        "image_manifest_hash": source_bundle.image_manifest_hash,
        "protocol_id": source_bundle.protocol_id,
        "cohort_id": source_bundle.cohort_id,
        "cohort_fingerprint": source_bundle.cohort_fingerprint,
        "pair_manifest_hash": source_bundle.pair_manifest_hash,
    }
    for field_name, expected_value in expected.items():
        definition_value = getattr(definition, field_name)
        manifest_value = getattr(manifest, field_name)
        if definition_value != expected_value:
            issues.append(
                f"the preparation definition's {field_name} does not match the "
                "authoritative source bundle"
            )
        if manifest_value != expected_value:
            issues.append(
                f"the prepared-set manifest's {field_name} does not match the "
                "authoritative source bundle"
            )
    actual_ids = tuple(definition.ordered_image_ids)
    if actual_ids != source_bundle.ordered_image_ids:
        issues.append(
            "the preparation definition's ordered participating image ids do not "
            "match the authoritative pair manifest"
        )
    return issues


@dataclass(frozen=True, slots=True)
class _SourceCheck:
    issues: tuple[str, ...]
    verified_source: int = 0
    recomputed_transform: int = 0
    matching_output_dimensions: int = 0
    matching_transform_action: int = 0
    matching_pixel_hash: int = 0
    matching_encoded_hash: int = 0


def _check_source(
    *,
    entry: PreparedImageEntry,
    images: Mapping[ImageId, ImageRecord],
    dataset_root: Path,
    profile: ImageTransformProfile,
    recompute_pixels: bool,
) -> _SourceCheck:
    source_issues: list[str] = []
    record = images.get(entry.image_id)
    if record is None:
        return _SourceCheck(
            issues=(
                f"{entry.image_id}: the entry names an image that is not in the manifest",
            )
        )
    if source_record_fingerprint(record) != entry.source_record_fingerprint:
        source_issues.append(
            f"{entry.image_id}: the image manifest now describes a different record "
            "than the entry was produced from"
        )
    if record.expected_sha256 != entry.source_expected_sha256:
        source_issues.append(
            f"{entry.image_id}: the manifest's source digest is not the one the "
            "entry records"
        )
    if record.effective_ppi != entry.source_effective_ppi:
        source_issues.append(
            f"{entry.image_id}: the manifest records {record.effective_ppi} ppi, the "
            f"entry {entry.source_effective_ppi}"
        )
    if record.checksum_status is not ChecksumStatus.VERIFIED:
        source_issues.append(
            f"{entry.image_id}: the source carries no VERIFIED checksum evidence"
        )

    try:
        path = resolve_source_path(record, dataset_root)
        source = read_source_raster(path, profile=profile, image_label=str(entry.image_id))
    except (ImagingError, ValueError) as exc:
        return _SourceCheck(issues=(f"{entry.image_id}: {exc}",))

    if source.encoded_sha256 != entry.source_expected_sha256:
        source_issues.append(
            f"{entry.image_id}: the source file on disk hashes to "
            f"{source.encoded_sha256[:12]}..., the entry records "
            f"{entry.source_expected_sha256[:12]}..."
        )
    if source.size_bytes != entry.source_size_bytes:
        source_issues.append(
            f"{entry.image_id}: the source file is {source.size_bytes} bytes, the "
            f"entry records {entry.source_size_bytes}"
        )
    if (source.width, source.height) != (entry.source_width, entry.source_height):
        source_issues.append(
            f"{entry.image_id}: the source is {source.width}x{source.height}, the "
            f"entry records {entry.source_width}x{entry.source_height}"
        )
    if source.pixel_sha256 != entry.source_pixel_sha256:
        source_issues.append(
            f"{entry.image_id}: the source raster no longer hashes to what the entry "
            "records"
        )
    elif entry.is_identity and source.pixel_sha256 != entry.output_pixel_sha256:
        source_issues.append(
            f"{entry.image_id}: the identity path must preserve the raster exactly"
        )

    if source_issues:
        return _SourceCheck(issues=tuple(source_issues))
    if not recompute_pixels:
        return _SourceCheck(issues=(), verified_source=1)

    try:
        artifact = canonicalise(
            source,
            profile=profile,
            source_ppi=entry.source_effective_ppi,
            image_label=str(entry.image_id),
        )
    except ImagingError as exc:
        return _SourceCheck(
            issues=(f"{entry.image_id}: {exc}",), verified_source=1
        )

    transform_issues: list[str] = []
    dimensions_match = (artifact.width, artifact.height) == (
        entry.output_width,
        entry.output_height,
    )
    if not dimensions_match:
        transform_issues.append(
            f"{entry.image_id}: re-running the transform produces "
            f"{artifact.width}x{artifact.height}, the entry records "
            f"{entry.output_width}x{entry.output_height}"
        )
    action_matches = artifact.transform_action == entry.transform_action
    if not action_matches:
        transform_issues.append(
            f"{entry.image_id}: re-running the transform names action "
            f"{artifact.transform_action!r}, the entry records "
            f"{entry.transform_action!r}"
        )
    pixel_matches = artifact.pixel_sha256 == entry.output_pixel_sha256
    if not pixel_matches:
        transform_issues.append(
            f"{entry.image_id}: re-running the transform produces raster "
            f"{artifact.pixel_sha256[:12]}..., the entry records "
            f"{entry.output_pixel_sha256[:12]}..."
        )
    encoded_matches = artifact.encoded_sha256 == entry.output_encoded_sha256
    if not encoded_matches:
        transform_issues.append(
            f"{entry.image_id}: re-encoding produces a different file than the "
            "entry records; the encoder or its zlib changed"
        )
    return _SourceCheck(
        issues=tuple(transform_issues),
        verified_source=1,
        recomputed_transform=1,
        matching_output_dimensions=int(dimensions_match),
        matching_transform_action=int(action_matches),
        matching_pixel_hash=int(pixel_matches),
        matching_encoded_hash=int(encoded_matches),
    )


def _build_transform_audit(
    *,
    manifest: PreparedImageSetManifest,
    planned_images: int,
    verified_sources: int,
    recomputed_transforms: int,
    matching_output_dimensions: int,
    matching_transform_actions: int,
    matching_pixel_hashes: int,
    matching_encoded_hashes: int,
    issues: list[str],
) -> PreparationTransformAudit:
    claims = {
        "schema_version": PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION,
        "preparation_set_id": manifest.preparation_set_id,
        "preparation_set_fingerprint": manifest.preparation_set_fingerprint,
        "planned_images": planned_images,
        "verified_sources": verified_sources,
        "recomputed_transforms": recomputed_transforms,
        "matching_output_dimensions": matching_output_dimensions,
        "matching_transform_actions": matching_transform_actions,
        "matching_pixel_hashes": matching_pixel_hashes,
        "matching_encoded_hashes": matching_encoded_hashes,
        "issues": tuple(issues),
    }
    return PreparationTransformAudit(
        **claims,
        audit_fingerprint=preparation_transform_audit_fingerprint(claims),
        created_utc=_utc_now(),
    )


def _check_receipt(
    store: PreparedImageSetStore,
    manifest: PreparedImageSetManifest,
    entries: tuple[PreparedImageEntry, ...],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    images: Mapping[ImageId, ImageRecord] | None,
    audit: PreparationTransformAudit | None,
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
        verifier_runtime = store.read_audit_runtime(
            manifest.preparation_set_id,
            stored.verifier_transform_runtime_fingerprint,
        )
    except StorageError as exc:
        return [str(exc)]

    if audit is None:
        return ["the preparation receipt has no verified transform audit to cite"]

    try:
        expected = build_preparation_receipt(
            manifest=manifest,
            entries=entries,
            profile=profile,
            runtime=runtime,
            audit=audit,
            verifier_runtime=verifier_runtime,
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
    audit: PreparationTransformAudit | None,
) -> list[str]:
    if audit is None:
        return ["the preparation finalization has no transform audit to bind"]
    try:
        marker = store.read_finalization(manifest.preparation_set_id)
        receipt = store.read_receipt(manifest.preparation_set_id)
        summary = store.read_summary(manifest.preparation_set_id)
        entries_hash = store.entries_table_content_hash(manifest.preparation_set_id)
        verifier_runtime = store.read_audit_runtime(
            manifest.preparation_set_id,
            marker.verifier_transform_runtime_fingerprint,
        )
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
        "transform_audit_fingerprint": audit.audit_fingerprint,
        "transform_audit_content_hash": preparation_transform_audit_content_hash(
            audit
        ),
        "source_commit": runtime.source_revision,
        "source_tree_clean": runtime.source_tree_clean,
        "verifier_source_commit": verifier_runtime.source_revision,
        "verifier_source_tree_clean": verifier_runtime.source_tree_clean,
        "verifier_transform_runtime_fingerprint": (
            verifier_runtime.runtime_fingerprint
        ),
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
