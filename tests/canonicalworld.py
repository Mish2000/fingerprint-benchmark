"""A synthetic canonical world: sources, a prepared set, and a run over it.

Building one by hand in every test would mean ten slightly different notions of
what a prepared-image set is, and the tests that matter most here are the ones
that check two artefacts agree with each other. So there is one builder.

Everything it produces is genuine: real PNGs written by the real encoder, real
entries with real hashes, a real store, a real definition and a real manifest.
The only thing invented is the *content* — a handful of small synthetic rasters
instead of 3,000 fingerprints — because the properties under test are about the
pipeline rather than about ridges.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from fpbench.core.enums import ChecksumStatus, FingerprintPosition, Impression
from fpbench.core.identifiers import ImageId, SubjectId, compose_id
from fpbench.core.imaging_models import (
    ImageTransformProfile,
    PreparationDefinition,
    PreparedImageEntry,
    PreparedImageSetManifest,
    TransformRuntimeManifest,
    ordered_image_ids_hash,
    ordered_prepared_entries_hash,
    preparation_definition_fingerprint,
    preparation_definition_id,
    preparation_set_fingerprint,
    preparation_set_id,
    prepared_image_entry_hash,
    transform_runtime_fingerprint,
    transform_runtime_id,
)
from fpbench.core.models import ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.imaging.canonical import canonicalise, encode_canonical_png, read_source_raster
from fpbench.imaging.source_records import source_record_fingerprint
from fpbench.imaging.transform_profile import load_transform_profile
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

__all__ = [
    "CanonicalWorld",
    "build_canonical_world",
    "synthetic_raster",
    "make_runtime",
    "SOURCE_PPI_BY_RELEASE",
]

#: The three resolutions SD300 is delivered at, reused so a synthetic world
#: exercises the identity path, the halving path and the quartering path.
SOURCE_PPI_BY_RELEASE: Mapping[str, int] = {
    "SD300A": 500,
    "SD300B": 1000,
    "SD300C": 2000,
}

_HASH_STUB = "0" * 64


def synthetic_raster(width: int, height: int, *, seed: int = 0) -> bytes:
    """A deterministic, non-constant gray8 raster.

    Non-constant matters: a flat image survives any resampler, so a test built on
    one would pass with a downsampler that did nothing at all.
    """
    return bytes(
        (x * 29 + y * 11 + seed * 7) % 256 for y in range(height) for x in range(width)
    )


@dataclass(frozen=True, slots=True)
class CanonicalWorld:
    """A workspace holding one finished, verifiable prepared-image set."""

    workspace: Path
    dataset_root: Path

    profile: ImageTransformProfile
    runtime: TransformRuntimeManifest
    definition: PreparationDefinition
    manifest: PreparedImageSetManifest

    images: Mapping[ImageId, ImageRecord]
    entries: tuple[PreparedImageEntry, ...]

    @property
    def store(self) -> PreparedImageSetStore:
        return PreparedImageSetStore(self.workspace)

    @property
    def preparation_set_id(self) -> str:
        return self.manifest.preparation_set_id

    @property
    def preparation_set_fingerprint(self) -> str:
        return self.manifest.preparation_set_fingerprint

    def entry_for(self, image_id: ImageId) -> PreparedImageEntry:
        return next(entry for entry in self.entries if entry.image_id == image_id)

    def artifact_path(self, entry: PreparedImageEntry) -> Path:
        return self.workspace / entry.relative_path


def make_runtime(
    *,
    software: SoftwareProvenance | None = None,
    pillow_version: str = "12.3.0",
    distribution_fingerprint: str = "a" * 64,
    lock_sha256: str = "b" * 64,
    file_count: int = 123,
    zlib_version: str = "1.3.1.zlib-ng",
) -> TransformRuntimeManifest:
    """A runtime manifest built from stated values rather than this machine's.

    Tests about *what a runtime fingerprint covers* have to be able to change one
    term at a time, which capturing the real environment cannot do.
    """
    software = software or SoftwareProvenance(
        provenance_kind="git",
        source_revision="c" * 40,
        source_tree_clean=True,
        package_version="0.1.0",
        python_version="3.12.13",
        python_implementation="CPython",
        dependency_versions={"pyarrow": "15.0.0", "pyyaml": "6.0"},
    )
    from fpbench.core.provenance_models import software_provenance_fingerprint

    fields = dict(
        software_fingerprint=software_provenance_fingerprint(software),
        dependency_lock_sha256=lock_sha256,
        pillow_version=pillow_version,
        pillow_distribution_fingerprint=distribution_fingerprint,
        pillow_file_count=file_count,
        python_version=software.python_version,
        python_implementation=software.python_implementation,
        platform_system="Linux",
        platform_machine="x86_64",
        zlib_runtime_version=zlib_version,
        source_revision=software.source_revision,
        source_tree_clean=software.source_tree_clean,
    )
    fingerprint = transform_runtime_fingerprint(_RuntimeDraft(**fields))
    return TransformRuntimeManifest(
        runtime_id=transform_runtime_id(fingerprint),
        runtime_fingerprint=fingerprint,
        created_utc=_utc_now(),
        **fields,
    )


class _RuntimeDraft:
    __slots__ = (
        "software_fingerprint",
        "dependency_lock_sha256",
        "pillow_version",
        "pillow_distribution_fingerprint",
        "pillow_file_count",
        "python_version",
        "python_implementation",
        "platform_system",
        "platform_machine",
        "zlib_runtime_version",
        "source_revision",
        "source_tree_clean",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


class _EntryDraft:
    __slots__ = (
        "ordinal",
        "image_id",
        "source_record_fingerprint",
        "source_expected_sha256",
        "source_size_bytes",
        "source_effective_ppi",
        "source_declared_ppi",
        "source_width",
        "source_height",
        "source_pixel_sha256",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_fingerprint",
        "transform_action",
        "scale_numerator",
        "scale_denominator",
        "output_width",
        "output_height",
        "output_effective_ppi",
        "output_pixel_sha256",
        "output_encoded_sha256",
        "output_size_bytes",
        "output_media_type",
        "relative_path",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


class _DefinitionDraft:
    __slots__ = (
        "dataset_id",
        "image_manifest_hash",
        "protocol_id",
        "cohort_id",
        "cohort_fingerprint",
        "pair_manifest_hash",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_id",
        "transform_runtime_fingerprint",
        "expected_total_images",
        "ordered_image_ids",
        "ordered_image_ids_hash",
        "source_commit",
        "source_tree_clean",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def build_canonical_world(
    root: Path,
    *,
    releases: Sequence[str] = ("SD300A", "SD300B", "SD300C"),
    subjects: int = 2,
    fingers: Sequence[int] = (1, 2),
    base_size: tuple[int, int] = (48, 40),
    runtime: TransformRuntimeManifest | None = None,
    profile: ImageTransformProfile | None = None,
    finalise: bool = True,
    raster_builder=None,
) -> CanonicalWorld:
    """Write synthetic sources, transform them, and publish a prepared set.

    Args:
        finalise: When false the entries and images exist but no manifest is
            written, which is what a half-finished materialisation looks like.
        raster_builder: ``(width, height, seed) -> bytes``. Defaults to a cheap
            deterministic pattern; the real-Java test supplies ridge-shaped
            prints instead, because a matcher has to be given something it could
            plausibly extract a template from.
    """
    builder = raster_builder or (
        lambda width, height, seed: synthetic_raster(width, height, seed=seed)
    )
    root = Path(root)
    workspace = root / "workspace"
    dataset_root = root / "dataset"
    workspace.mkdir(parents=True, exist_ok=True)
    dataset_root.mkdir(parents=True, exist_ok=True)

    profile = profile or load_transform_profile()
    runtime = runtime or make_runtime()
    store = PreparedImageSetStore(workspace)

    images: dict[ImageId, ImageRecord] = {}
    seed = 0
    for release in releases:
        source_ppi = SOURCE_PPI_BY_RELEASE[release]
        scale = source_ppi // profile.target_ppi
        width = base_size[0] * scale
        height = base_size[1] * scale
        for subject_index in range(subjects):
            subject = SubjectId(f"s{subject_index + 1:04d}")
            for finger in fingers:
                for impression in (Impression.PLAIN, Impression.ROLL):
                    seed += 1
                    image_id = ImageId(
                        compose_id(
                            release,
                            str(subject),
                            impression.value,
                            f"f{finger:02d}",
                        )
                    )
                    raster = builder(width, height, seed)
                    encoded = encode_canonical_png(
                        width=width, height=height, raster=raster, profile=profile
                    )
                    relative = f"{release.lower()}/{image_id}.png"
                    path = dataset_root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(encoded)

                    import hashlib

                    images[image_id] = ImageRecord(
                        image_id=image_id,
                        dataset_id="sd300",
                        release=release,
                        subject_id=subject,
                        impression=impression,
                        position=FingerprintPosition(finger),
                        is_multi_finger=False,
                        relative_path=relative,
                        effective_ppi=source_ppi,
                        expected_sha256=hashlib.sha256(encoded).hexdigest(),
                        metadata_ppi=5080 if release == "SD300C" else source_ppi,
                        checksum_status=ChecksumStatus.VERIFIED,
                    )

    ordered_ids = tuple(sorted(images))
    definition = _definition(
        ordered_ids=ordered_ids, profile=profile, runtime=runtime
    )
    container = store.pending_dir(definition.definition_id)
    container.mkdir(parents=True, exist_ok=True)
    store.ensure_transform_profile(container, profile)
    store.ensure_runtime(container, runtime)
    store.ensure_definition(definition)

    entries: list[PreparedImageEntry] = []
    for ordinal, image_id in enumerate(ordered_ids):
        record = images[image_id]
        source = read_source_raster(
            dataset_root / record.relative_path,
            profile=profile,
            image_label=str(image_id),
        )
        artifact = canonicalise(
            source,
            profile=profile,
            source_ppi=record.effective_ppi,
            image_label=str(image_id),
        )
        outcome = store.ensure_image(
            encoded_bytes=artifact.encoded_bytes,
            encoded_sha256=artifact.encoded_sha256,
        )
        draft = dict(
            ordinal=ordinal,
            image_id=image_id,
            source_record_fingerprint=source_record_fingerprint(record),
            source_expected_sha256=record.expected_sha256,
            source_size_bytes=source.size_bytes,
            source_effective_ppi=record.effective_ppi,
            source_declared_ppi=source.declared_ppi,
            source_width=source.width,
            source_height=source.height,
            source_pixel_sha256=source.pixel_sha256,
            transform_profile_id=profile.profile_id,
            transform_profile_fingerprint=profile.profile_fingerprint,
            transform_runtime_fingerprint=runtime.runtime_fingerprint,
            transform_action=artifact.transform_action,
            scale_numerator=artifact.scale_numerator,
            scale_denominator=artifact.scale_denominator,
            output_width=artifact.width,
            output_height=artifact.height,
            output_effective_ppi=profile.target_ppi,
            output_pixel_sha256=artifact.pixel_sha256,
            output_encoded_sha256=artifact.encoded_sha256,
            output_size_bytes=artifact.size_bytes,
            output_media_type=profile.output_media_type,
            relative_path=outcome.relative_path,
        )
        entry = PreparedImageEntry(
            entry_hash=prepared_image_entry_hash(_EntryDraft(**draft)), **draft
        )
        store.ensure_entry(definition.definition_id, entry)
        entries.append(entry)

    manifest = _manifest(definition=definition, entries=tuple(entries))
    if finalise:
        store.ensure_manifest(
            manifest=manifest,
            entries=tuple(entries),
            profile=profile,
            runtime=runtime,
            definition=definition,
        )

    return CanonicalWorld(
        workspace=workspace,
        dataset_root=dataset_root,
        profile=profile,
        runtime=runtime,
        definition=definition,
        manifest=manifest,
        images=images,
        entries=tuple(entries),
    )


def publish_receipt_and_marker(world: CanonicalWorld) -> None:
    """Finish the chain: summary, receipt and the marker that makes it count."""
    from fpbench.experiments.preparation_receipt import (
        build_preparation_finalization_marker,
        build_preparation_receipt,
    )
    from fpbench.storage.prepared_image_set_store import (
        preparation_summary_content_hash,
    )

    store = world.store
    set_id = world.preparation_set_id
    summary = {
        "preparation_set_id": set_id,
        "total_images": len(world.entries),
        "generated_utc": _utc_now(),
    }
    store.ensure_summary(preparation_set_id=set_id, summary=summary)
    receipt = build_preparation_receipt(
        manifest=world.manifest,
        entries=world.entries,
        profile=world.profile,
        runtime=world.runtime,
        images=world.images,
    )
    store.ensure_receipt(preparation_set_id=set_id, receipt=receipt)
    marker = build_preparation_finalization_marker(
        manifest=world.manifest,
        profile=world.profile,
        runtime=world.runtime,
        receipt=store.read_receipt(set_id),
        entries_table_content_hash=store.entries_table_content_hash(set_id),
        summary_content_hash=preparation_summary_content_hash(
            store.read_summary(set_id)
        ),
    )
    store.ensure_finalization(preparation_set_id=set_id, marker=marker)


# ----------------------------------------------------------------- internals


def _definition(
    *,
    ordered_ids: Sequence[ImageId],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
) -> PreparationDefinition:
    draft = dict(
        dataset_id="sd300",
        image_manifest_hash="1" * 64,
        protocol_id="sd300_50_subjects",
        cohort_id="sd300_50_subjects_test_22f8d52a7478",
        cohort_fingerprint="2" * 64,
        pair_manifest_hash="3" * 64,
        transform_profile_id=profile.profile_id,
        transform_profile_fingerprint=profile.profile_fingerprint,
        transform_runtime_id=runtime.runtime_id,
        transform_runtime_fingerprint=runtime.runtime_fingerprint,
        expected_total_images=len(ordered_ids),
        ordered_image_ids=tuple(ordered_ids),
        ordered_image_ids_hash=ordered_image_ids_hash(ordered_ids),
        source_commit=runtime.source_revision,
        source_tree_clean=runtime.source_tree_clean,
    )
    fingerprint = preparation_definition_fingerprint(_DefinitionDraft(**draft))
    return PreparationDefinition(
        definition_id=preparation_definition_id(fingerprint),
        definition_fingerprint=fingerprint,
        created_utc=_utc_now(),
        **draft,
    )


def _manifest(
    *, definition: PreparationDefinition, entries: Iterable[PreparedImageEntry]
) -> PreparedImageSetManifest:
    ordered = tuple(entries)
    fingerprint = preparation_set_fingerprint(
        dataset_id=definition.dataset_id,
        image_manifest_hash=definition.image_manifest_hash,
        protocol_id=definition.protocol_id,
        cohort_id=definition.cohort_id,
        cohort_fingerprint=definition.cohort_fingerprint,
        pair_manifest_hash=definition.pair_manifest_hash,
        transform_profile_fingerprint=definition.transform_profile_fingerprint,
        transform_runtime_fingerprint=definition.transform_runtime_fingerprint,
        entries=ordered,
    )
    return PreparedImageSetManifest(
        preparation_set_id=preparation_set_id(fingerprint),
        preparation_set_fingerprint=fingerprint,
        dataset_id=definition.dataset_id,
        image_manifest_hash=definition.image_manifest_hash,
        protocol_id=definition.protocol_id,
        cohort_id=definition.cohort_id,
        cohort_fingerprint=definition.cohort_fingerprint,
        pair_manifest_hash=definition.pair_manifest_hash,
        transform_profile_id=definition.transform_profile_id,
        transform_profile_fingerprint=definition.transform_profile_fingerprint,
        transform_runtime_id=definition.transform_runtime_id,
        transform_runtime_fingerprint=definition.transform_runtime_fingerprint,
        total_images=len(ordered),
        ordered_entries_hash=ordered_prepared_entries_hash(ordered),
        created_utc=_utc_now(),
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
