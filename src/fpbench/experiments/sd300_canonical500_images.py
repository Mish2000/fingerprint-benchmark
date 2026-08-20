"""The 3,000-image canonical 500 ppi materialisation, in four commands.

    python -m fpbench.experiments.sd300_canonical500_images prepare
    python -m fpbench.experiments.sd300_canonical500_images materialize [--max-new-images N]
    python -m fpbench.experiments.sd300_canonical500_images status
    python -m fpbench.experiments.sd300_canonical500_images finalize

They are separate for the same reason the SourceAFIS run's four are separate:
they answer to different failures. ``prepare`` is where a dirty working tree, an
unpinned resampler, an unverified source or an ambiguous PNG stops everything,
before a single pixel is computed. ``materialize`` can be run as many times as it
takes, and each invocation revalidates the pinned runtime on the way in and on
the way out. ``finalize`` is the only command that writes a manifest, a receipt
or a marker, and it does so only after re-reading every source file and
re-checking every artefact (docs/adr/0020, applied to preparation).

Nothing here compares anything. There is no algorithm in this module, no
threshold, no score and no metric — a canonical set is an *input*, and the entire
claim it makes is that every algorithm evaluated under it was handed the same
pixels (docs/adr/0031, docs/adr/0033).

One bookkeeping note. ``prepare`` writes a pointer at
``workspace/experiments/<experiment_id>/current-preparation.json`` so the later
commands can find the definition without being told its id. It is a bookmark, not
evidence: nothing downstream trusts anything in it, and every check re-derives
what it needs from the definition's own fingerprint.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.enums import PreparationStatus
from fpbench.core.errors import (
    ConfigurationError,
    ImagingError,
    PreparationDerivationError,
    PreparationFinalizationError,
    ResearchPreflightError,
    SourceImageContractError,
)
from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import (
    ImageTransformProfile,
    PreparationDefinition,
    PreparationTransformAudit,
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
)
from fpbench.core.models import ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.serialization import read_json, require_exact_int
from fpbench.core.json_io import write_json
from fpbench.experiments.preparation_receipt import (
    build_preparation_finalization_marker,
    build_preparation_receipt,
    verify_preparation_receipt,
    write_preparation_evidence_copy,
)
from fpbench.experiments.sd300_inputs import (
    EXPECTED_IMAGES_PER_RELEASE,
    EXPECTED_JOBS,
    EXPECTED_PARTICIPATING_IMAGES,
    EXPECTED_RELEASES,
    SD300Inputs,
    load_sd300_inputs,
    participating_image_ids,
    preparation_source_bundle,
    require_expected_shape,
)
from fpbench.imaging.canonical import canonicalise, read_source_raster
from fpbench.imaging.runtime import capture_transform_runtime, dependency_lock_sha256
from fpbench.imaging.source_records import resolve_source_path, source_record_fingerprint
from fpbench.imaging.status import PreparationState, inspect_preparation
from fpbench.imaging.transform_profile import load_transform_profile
from fpbench.imaging.verify import verify_prepared_image_set
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

__all__ = [
    "PreparationExperimentConfig",
    "PreparedMaterialisation",
    "MaterialisationSummary",
    "load_preparation_config",
    "prepare_canonical500_images",
    "materialize_canonical500_images",
    "inspect_canonical500_images",
    "finalize_canonical500_images",
    "EXPERIMENT_ID",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_ID = "sd300_canonical500_images_v1"
DEFAULT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "experiments" / f"{EXPERIMENT_ID}.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

_POINTER_NAME = "current-preparation.json"


# -------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class PreparationExperimentConfig:
    """The pinned description of this materialisation, read from YAML."""

    experiment_id: str
    dataset_config: Path
    protocol_config: Path
    transform_profile_config: Path

    require_verified_checksums: bool

    expected_total_images: int
    expected_images_per_release: int
    expected_releases: tuple[str, ...]
    expected_pairs: int
    expected_source_ppi: Mapping[str, int]


def load_preparation_config(
    path: Path = DEFAULT_CONFIG, *, repository_root: Path = REPOSITORY_ROOT
) -> PreparationExperimentConfig:
    """Read ``configs/experiments/sd300_canonical500_images_v1.yaml``."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"preparation config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    experiment = _section(document, "experiment", path)
    dataset = _section(document, "dataset", path)
    protocol = _section(document, "protocol", path)
    transform = _section(document, "transform", path)
    shape = _section(document, "expected_shape", path)

    if document.get("decisions") or document.get("thresholds"):
        raise ConfigurationError(
            f"{path}: a preparation applies no threshold and makes no decision"
        )

    root = Path(repository_root)
    return PreparationExperimentConfig(
        experiment_id=str(experiment["id"]),
        dataset_config=(root / str(dataset["ref"])).resolve(),
        protocol_config=(root / str(protocol["ref"])).resolve(),
        transform_profile_config=(root / str(transform["ref"])).resolve(),
        require_verified_checksums=bool(
            dataset.get("require_verified_checksums", True)
        ),
        expected_total_images=require_exact_int(
            shape["participating_images"], "participating_images"
        ),
        expected_images_per_release=require_exact_int(
            shape["images_per_release"], "images_per_release"
        ),
        expected_releases=tuple(str(item) for item in shape["releases"]),
        expected_pairs=require_exact_int(shape["comparisons"], "comparisons"),
        expected_source_ppi={
            str(key): require_exact_int(value, f"source_ppi[{key}]")
            for key, value in dict(shape["source_ppi"]).items()
        },
    )


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed '{key}' section")
    return value


# ------------------------------------------------------------ prepared state


@dataclass(frozen=True, slots=True)
class PreparedMaterialisation:
    """Everything ``materialize`` and ``finalize`` need, already checked."""

    config: PreparationExperimentConfig
    software: SoftwareProvenance

    inputs: SD300Inputs
    workspace: Path

    profile: ImageTransformProfile
    runtime: TransformRuntimeManifest
    definition: PreparationDefinition

    @property
    def store(self) -> PreparedImageSetStore:
        return PreparedImageSetStore(self.workspace)


@dataclass(frozen=True, slots=True)
class MaterialisationSummary:
    """What one ``materialize`` invocation did."""

    definition_id: str
    expected_images: int
    newly_materialised: int
    reused_existing: int
    remaining: int
    wall_seconds: float

    @property
    def complete(self) -> bool:
        return self.remaining == 0


# -------------------------------------------------------------------- prepare


def prepare_canonical500_images(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: PreparationExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    require_clean: bool = True,
) -> PreparedMaterialisation:
    """Pin the transformation, check every source, and write the promise.

    No output PNG is produced here. ``prepare`` exists precisely so that the
    expensive, irreversible part starts only after the cheap, fatal checks have
    all passed (spec section 43).

    Raises:
        ResearchPreflightError: the tree is dirty, the resampler is not pinned,
            or the protocol does not yield the expected shape.
        SourceImageContractError: a participating image is not the single-frame
            8-bit grayscale PNG the profile describes. The whole preparation
            stops; no ``FAILED`` entry is written and no partial set is built
            (spec section 13).
    """
    workspace = Path(workspace)
    config = config or load_preparation_config(repository_root=repository_root)

    # 1. Which code is about to run, and is all of it committed?
    software = _capture_provenance(repository_root, require_clean=require_clean)

    # 2-4. The transformation, the machine that will perform it, and the pin.
    profile = load_transform_profile(config.transform_profile_config)
    runtime = capture_transform_runtime(software=software)
    dependency_lock_sha256()  # raises when the pin is missing

    # 5-6. The experiment's own inputs, and the exact image set they name.
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=True,
    )
    require_expected_shape(
        cohort=inputs.cohort,
        pairs=inputs.pairs,
        images=inputs.images,
        expected_jobs=config.expected_pairs,
        expected_participating_images=config.expected_total_images,
    )
    image_ids = participating_image_ids(inputs.pairs)
    _require_expected_release_shape(config, image_ids, inputs)

    # 7. Every one of the 3,000 must be readable, unambiguous and at a
    # resolution this profile can reach, before anything is materialised.
    _source_preflight(
        image_ids=image_ids,
        inputs=inputs,
        profile=profile,
        config=config,
    )

    # 8-9. The immutable promise, and the three files that record it.
    definition = _build_definition(
        inputs=inputs,
        profile=profile,
        runtime=runtime,
        software=software,
        image_ids=image_ids,
    )
    store = PreparedImageSetStore(workspace)
    container = store.pending_dir(definition.definition_id)
    container.mkdir(parents=True, exist_ok=True)
    store.ensure_transform_profile(container, profile)
    store.ensure_runtime(container, runtime)
    store.ensure_definition(definition)

    _write_pointer(
        workspace,
        config.experiment_id,
        {
            "experiment_id": config.experiment_id,
            "definition_id": definition.definition_id,
            "definition_fingerprint": definition.definition_fingerprint,
            "transform_profile_id": profile.profile_id,
            "transform_runtime_id": runtime.runtime_id,
            "expected_images": definition.expected_total_images,
            "source_commit": software.source_revision,
            "prepared_utc": _utc_now(),
        },
    )

    return PreparedMaterialisation(
        config=config,
        software=software,
        inputs=inputs,
        workspace=workspace,
        profile=profile,
        runtime=runtime,
        definition=definition,
    )


# ----------------------------------------------------------------- materialize


def materialize_canonical500_images(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: PreparationExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    definition_id: str | None = None,
    max_new_images: int | None = None,
    require_clean: bool = True,
) -> MaterialisationSummary:
    """Produce canonical artefacts, in definition order, resumably.

    The runtime fingerprint is captured before the first image and again after
    the last, and the two must be identical. A Pillow upgrade half way through
    would leave a set whose first half and second half came from different
    resamplers, and no amount of re-running finishes such a set — it is
    abandoned and a new one is materialised (spec section 52).
    """
    prepared = _load_prepared(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        definition_id=definition_id,
        require_clean=require_clean,
    )
    store = prepared.store
    definition = prepared.definition
    started = time.monotonic()

    before = capture_transform_runtime(software=prepared.software)
    if before.runtime_fingerprint != definition.transform_runtime_fingerprint:
        raise PreparationDerivationError(
            f"this machine now fingerprints as {before.runtime_id}, but the "
            f"preparation was defined under {definition.transform_runtime_id}. A "
            "set may not be half produced by one resampler and half by another; "
            "prepare a new one"
        )

    newly = 0
    reused = 0
    for ordinal, image_id in enumerate(definition.ordered_image_ids):
        if store.has_entry(definition.definition_id, str(image_id)):
            # An existing entry is fully re-verified before it is trusted, and
            # never repaired: a damaged one invalidates the set (spec section 53).
            entry = store.read_entry_by_image_id(definition.definition_id, str(image_id))
            if entry.ordinal != ordinal:
                raise PreparationDerivationError(
                    f"{image_id} is recorded at ordinal {entry.ordinal}, but this "
                    f"definition places it at {ordinal}"
                )
            store.verify_entry(entry, profile=prepared.profile)
            reused += 1
            continue

        if max_new_images is not None and newly >= max_new_images:
            break

        entry = _materialise_one(
            image_id=image_id,
            ordinal=ordinal,
            prepared=prepared,
            store=store,
        )
        store.ensure_entry(definition.definition_id, entry)
        newly += 1

    after = capture_transform_runtime(software=prepared.software)
    if after.runtime_fingerprint != before.runtime_fingerprint:
        raise PreparationDerivationError(
            "the transform runtime changed while images were being materialised; "
            "this preparation set is void and cannot be completed by re-running"
        )
    verifier = _capture_provenance(repository_root, require_clean=require_clean)
    if verifier.source_revision != prepared.software.source_revision:
        raise PreparationDerivationError(
            "the fpbench source revision changed during materialisation"
        )

    materialised = sum(
        1
        for image_id in definition.ordered_image_ids
        if store.has_entry(definition.definition_id, str(image_id))
    )
    return MaterialisationSummary(
        definition_id=definition.definition_id,
        expected_images=definition.expected_total_images,
        newly_materialised=newly,
        reused_existing=reused,
        remaining=definition.expected_total_images - materialised,
        wall_seconds=round(time.monotonic() - started, 3),
    )


def _materialise_one(
    *,
    image_id: ImageId,
    ordinal: int,
    prepared: PreparedMaterialisation,
    store: PreparedImageSetStore,
) -> PreparedImageEntry:
    """Transform one image and write it, verifying the file that lands on disk."""
    record = prepared.inputs.images[image_id]
    path = resolve_source_path(record, prepared.inputs.dataset_root)
    source = read_source_raster(
        path, profile=prepared.profile, image_label=str(image_id)
    )
    if source.encoded_sha256 != record.expected_sha256:
        raise PreparationDerivationError(
            f"{image_id}: the source file hashes to {source.encoded_sha256[:12]}..., "
            f"but the manifest records {record.expected_sha256[:12]}..."
        )

    artifact = canonicalise(
        source,
        profile=prepared.profile,
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
        transform_profile_id=prepared.profile.profile_id,
        transform_profile_fingerprint=prepared.profile.profile_fingerprint,
        transform_runtime_fingerprint=prepared.runtime.runtime_fingerprint,
        transform_action=artifact.transform_action,
        scale_numerator=artifact.scale_numerator,
        scale_denominator=artifact.scale_denominator,
        output_width=artifact.width,
        output_height=artifact.height,
        output_effective_ppi=prepared.profile.target_ppi,
        output_pixel_sha256=artifact.pixel_sha256,
        output_encoded_sha256=artifact.encoded_sha256,
        output_size_bytes=artifact.size_bytes,
        output_media_type=prepared.profile.output_media_type,
        relative_path=outcome.relative_path,
    )
    entry = PreparedImageEntry(
        entry_hash=prepared_image_entry_hash(_EntryDraft(**draft)), **draft
    )
    # Read the file back from its final path before recording it. `save()` not
    # raising is not evidence that the bytes on disk decode to the raster that
    # went in (spec section 29).
    store.verify_entry(entry, profile=prepared.profile)
    return entry


class _EntryDraft:
    """An entry-shaped stand-in used only to compute ``entry_hash``.

    :class:`PreparedImageEntry` re-derives and checks its own hash, so it cannot
    be built before one exists. Feeding the rule a stand-in keeps the rule in one
    place instead of copying it here.
    """

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

    def __init__(self, **fields: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


# --------------------------------------------------------------------- status


def inspect_canonical500_images(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: PreparationExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    definition_id: str | None = None,
    with_sources: bool = True,
    recompute_pixels: bool = True,
) -> PreparationState:
    """Report how far along the evidence chain the preparation is. Never writes."""
    prepared = _load_prepared(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        definition_id=definition_id,
        require_clean=False,
        require_runtime_match=False,
    )
    return inspect_preparation(
        store=prepared.store,
        definition=prepared.definition,
        images=prepared.inputs.images if with_sources else None,
        dataset_root=prepared.inputs.dataset_root if with_sources else None,
        source_bundle=(
            preparation_source_bundle(prepared.inputs) if with_sources else None
        ),
        recompute_pixels=recompute_pixels,
    )


# ------------------------------------------------------------------- finalize


def finalize_canonical500_images(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: PreparationExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    definition_id: str | None = None,
    require_clean: bool = True,
) -> PreparationState:
    """Re-verify everything, then publish one last immutable commit marker.

    A failure may leave idempotent intermediate artefacts, but never the marker.
    Only a marker matching the freshly revalidated chain is authoritative, so
    interruption at any earlier write is safely retryable and cannot produce
    ``PREPARATION_READY`` (docs/adr/0020).
    """
    prepared = _load_prepared(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        definition_id=definition_id,
        require_clean=require_clean,
        require_runtime_match=False,
    )
    store = prepared.store
    definition = prepared.definition

    # 1-4. Every source, every entry, in order and with no gaps.
    entries = _collect_entries(store, definition)

    # 5. Every canonical artefact, re-read from disk.
    for entry in entries:
        store.verify_entry(entry, profile=prepared.profile)

    # 6-7. The identity, derived rather than assumed.
    ordered_hash = ordered_prepared_entries_hash(entries)
    fingerprint = preparation_set_fingerprint(
        dataset_id=prepared.inputs.protocol.dataset_id,
        image_manifest_hash=definition.image_manifest_hash,
        protocol_id=definition.protocol_id,
        cohort_id=definition.cohort_id,
        cohort_fingerprint=definition.cohort_fingerprint,
        pair_manifest_hash=definition.pair_manifest_hash,
        transform_profile_fingerprint=prepared.profile.profile_fingerprint,
        transform_runtime_fingerprint=prepared.runtime.runtime_fingerprint,
        entries=entries,
    )
    manifest = PreparedImageSetManifest(
        preparation_set_id=preparation_set_id(fingerprint),
        preparation_set_fingerprint=fingerprint,
        dataset_id=definition.dataset_id,
        image_manifest_hash=definition.image_manifest_hash,
        protocol_id=definition.protocol_id,
        cohort_id=definition.cohort_id,
        cohort_fingerprint=definition.cohort_fingerprint,
        pair_manifest_hash=definition.pair_manifest_hash,
        transform_profile_id=prepared.profile.profile_id,
        transform_profile_fingerprint=prepared.profile.profile_fingerprint,
        transform_runtime_id=prepared.runtime.runtime_id,
        transform_runtime_fingerprint=prepared.runtime.runtime_fingerprint,
        total_images=len(entries),
        ordered_entries_hash=ordered_hash,
        created_utc=_utc_now(),
    )

    # 8-9. Publish idempotent intermediates, then read them back.
    store.ensure_manifest(
        manifest=manifest,
        entries=entries,
        profile=prepared.profile,
        runtime=prepared.runtime,
        definition=definition,
    )
    stored_manifest = store.read_manifest(manifest.preparation_set_id)
    stored_entries = store.read_entries(manifest.preparation_set_id)
    if [entry.entry_hash for entry in stored_entries] != [
        entry.entry_hash for entry in entries
    ]:
        raise PreparationFinalizationError(
            "the entries read back from the set are not the entries written to it"
        )

    # 10. Re-read every source and re-run every transform. This independent
    # audit is the load-bearing proof that each stored B/C output is the direct
    # Lanczos result of the authoritative source, not merely a self-consistent
    # PNG with freshly recomputed hashes.
    audit, verifier_runtime = _run_transform_audit_with_provenance(
        prepared=prepared,
        manifest=manifest,
        repository_root=Path(repository_root),
        require_clean=require_clean,
    )
    store.ensure_transform_audit(
        preparation_set_id=manifest.preparation_set_id, audit=audit
    )
    store.ensure_audit_runtime(
        preparation_set_id=manifest.preparation_set_id,
        runtime=verifier_runtime,
    )
    stored_audit = store.read_transform_audit(manifest.preparation_set_id)
    stored_verifier_runtime = store.read_audit_runtime(
        manifest.preparation_set_id,
        verifier_runtime.runtime_fingerprint,
    )

    # 11-14. Summary, then the sanitised receipt, then both re-read.
    summary = _build_summary(
        manifest=stored_manifest,
        entries=stored_entries,
        images=prepared.inputs.images,
        profile=prepared.profile,
        runtime=prepared.runtime,
    )
    store.ensure_summary(
        preparation_set_id=manifest.preparation_set_id, summary=summary
    )
    receipt = build_preparation_receipt(
        manifest=stored_manifest,
        entries=stored_entries,
        profile=prepared.profile,
        runtime=prepared.runtime,
        audit=stored_audit,
        verifier_runtime=stored_verifier_runtime,
        images=prepared.inputs.images,
    )
    store.ensure_receipt(
        preparation_set_id=manifest.preparation_set_id, receipt=receipt
    )
    stored_receipt = store.read_receipt(manifest.preparation_set_id)
    stored_summary = store.read_summary(manifest.preparation_set_id)
    verify_preparation_receipt(
        receipt=stored_receipt,
        manifest=stored_manifest,
        entries=stored_entries,
        profile=prepared.profile,
        runtime=prepared.runtime,
        audit=stored_audit,
        verifier_runtime=stored_verifier_runtime,
        images=prepared.inputs.images,
    )

    # 15. Commit point: deliberately the final authoritative workspace write.
    from fpbench.storage.prepared_image_set_store import (
        preparation_summary_content_hash,
    )

    marker = build_preparation_finalization_marker(
        manifest=stored_manifest,
        profile=prepared.profile,
        runtime=prepared.runtime,
        receipt=stored_receipt,
        audit=stored_audit,
        verifier_runtime=stored_verifier_runtime,
        entries_table_content_hash=store.entries_table_content_hash(
            manifest.preparation_set_id
        ),
        summary_content_hash=preparation_summary_content_hash(stored_summary),
    )
    store.ensure_finalization(
        preparation_set_id=manifest.preparation_set_id, marker=marker
    )

    # 16-17. Status, derived from the files that now exist.
    state = inspect_preparation(
        store=store,
        definition=definition,
        preparation_set_id_value=manifest.preparation_set_id,
        images=prepared.inputs.images,
        dataset_root=prepared.inputs.dataset_root,
        source_bundle=preparation_source_bundle(prepared.inputs),
        recompute_pixels=True,
    )
    if not state.is_preparation_ready:
        raise PreparationFinalizationError(
            f"preparation set {manifest.preparation_set_id} finalised but did not "
            f"reach PREPARATION_READY: {state.status.value} {list(state.issues)[:3]}"
        )

    # 18. Evidence, last, because writing it makes the tree dirty.
    write_preparation_evidence_copy(
        stored_receipt, repository_root=Path(repository_root)
    )
    return state


# ------------------------------------------------------------------- internals


def _run_transform_audit_with_provenance(
    *,
    prepared: PreparedMaterialisation,
    manifest: PreparedImageSetManifest,
    repository_root: Path,
    require_clean: bool,
) -> tuple[PreparationTransformAudit, TransformRuntimeManifest]:
    """Run the semantic audit between two identical verifier-runtime captures."""
    before_software = _capture_provenance(
        repository_root, require_clean=require_clean
    )
    if not before_software.is_research_grade:
        raise PreparationFinalizationError(
            "the transform audit verifier must be a committed, clean source tree"
        )
    if before_software.source_revision != prepared.software.source_revision:
        raise PreparationFinalizationError(
            "the fpbench source revision changed before the transform audit began"
        )
    before_runtime = capture_transform_runtime(software=before_software)

    verification = verify_prepared_image_set(
        store=prepared.store,
        preparation_set_id_value=manifest.preparation_set_id,
        images=prepared.inputs.images,
        dataset_root=prepared.inputs.dataset_root,
        source_bundle=preparation_source_bundle(prepared.inputs),
        recompute_pixels=True,
        require_receipt=False,
        require_finalization=False,
        # An older receipt/marker may be present. They are upgraded only after
        # the new attributed audit succeeds; the final status pass verifies the
        # complete new publication from disk.
        check_existing_publication=False,
    )

    after_software = _capture_provenance(
        repository_root, require_clean=require_clean
    )
    if not after_software.is_research_grade:
        raise PreparationFinalizationError(
            "the transform audit verifier became uncommitted or dirty"
        )
    after_runtime = capture_transform_runtime(software=after_software)
    if after_runtime.runtime_fingerprint != before_runtime.runtime_fingerprint:
        raise PreparationFinalizationError(
            "the verifier transform runtime changed while the full audit was "
            "running; no finalization marker may be issued"
        )

    audit = verification.transform_audit
    if not verification.is_valid or audit is None or not audit.is_clean:
        raise PreparationFinalizationError(
            f"preparation set {manifest.preparation_set_id} failed its full "
            f"transform audit: {list(verification.issues)[:3]}"
        )
    return audit, before_runtime


def _capture_provenance(
    repository_root: Path, *, require_clean: bool
) -> SoftwareProvenance:
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=require_clean
    )


def _require_expected_release_shape(
    config: PreparationExperimentConfig,
    image_ids: Sequence[ImageId],
    inputs: SD300Inputs,
) -> None:
    """The counts of spec section 6, enforced here rather than in the imaging core.

    ``fpbench.imaging`` must stay true for any dataset at any resolution. "1,000
    images per release, 500 plain and 500 rolled" is true only of this
    experiment, so it is asserted by this experiment.
    """
    per_release: dict[str, int] = {}
    per_release_impression: dict[tuple[str, str], int] = {}
    for image_id in image_ids:
        record = inputs.images[image_id]
        per_release[record.release] = per_release.get(record.release, 0) + 1
        key = (record.release, record.impression.value)
        per_release_impression[key] = per_release_impression.get(key, 0) + 1

    if tuple(sorted(per_release)) != tuple(sorted(config.expected_releases)):
        raise ResearchPreflightError(
            f"the participating images cover {sorted(per_release)}, expected "
            f"{sorted(config.expected_releases)}"
        )
    for release, count in sorted(per_release.items()):
        if count != config.expected_images_per_release:
            raise ResearchPreflightError(
                f"{release} contributes {count} participating images, expected "
                f"{config.expected_images_per_release}"
            )
    half = config.expected_images_per_release // 2
    for (release, impression), count in sorted(per_release_impression.items()):
        if count != half:
            raise ResearchPreflightError(
                f"{release} contributes {count} {impression} images, expected {half}"
            )


def _source_preflight(
    *,
    image_ids: Sequence[ImageId],
    inputs: SD300Inputs,
    profile: ImageTransformProfile,
    config: PreparationExperimentConfig,
) -> None:
    """Every source, checked before the first output is written.

    Reads and decodes all 3,000 files. That is slow and it is the point: an
    ambiguous PNG discovered after 2,900 images have been materialised is an
    abandoned set, and an ambiguous PNG that was never discovered is a silent
    conversion inside every score (spec section 13).
    """
    for image_id in image_ids:
        record = inputs.images.get(image_id)
        if record is None:
            raise PreparationDerivationError(
                f"{image_id} is named by the pair manifest but is not in the image "
                "manifest"
            )
        expected_ppi = config.expected_source_ppi.get(record.release)
        if expected_ppi is None:
            raise ResearchPreflightError(
                f"{record.release} has no declared source resolution in this "
                "experiment's configuration"
            )
        if record.effective_ppi != expected_ppi:
            raise ResearchPreflightError(
                f"{image_id}: the manifest records {record.effective_ppi} ppi, but "
                f"{record.release} is used at {expected_ppi} (docs/adr/0004)"
            )
        if record.effective_ppi < profile.target_ppi:
            raise ResearchPreflightError(
                f"{image_id}: {record.effective_ppi} ppi is below the profile's "
                f"target of {profile.target_ppi}; upsampling is forbidden"
            )

        path = resolve_source_path(record, inputs.dataset_root)
        source = read_source_raster(path, profile=profile, image_label=str(image_id))
        if source.encoded_sha256 != record.expected_sha256:
            raise SourceImageContractError(
                f"{image_id}: the source file hashes to "
                f"{source.encoded_sha256[:12]}..., but the manifest records "
                f"{record.expected_sha256[:12]}..."
            )


def _build_definition(
    *,
    inputs: SD300Inputs,
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    software: SoftwareProvenance,
    image_ids: Sequence[ImageId],
) -> PreparationDefinition:
    ordered = tuple(image_ids)
    draft = dict(
        dataset_id=inputs.protocol.dataset_id,
        image_manifest_hash=_combined_image_manifest_hash(inputs),
        protocol_id=inputs.protocol.protocol_id,
        cohort_id=str(inputs.cohort.cohort_id),
        cohort_fingerprint=_cohort_fingerprint(inputs),
        pair_manifest_hash=inputs.pair_manifest_hash,
        transform_profile_id=profile.profile_id,
        transform_profile_fingerprint=profile.profile_fingerprint,
        transform_runtime_id=runtime.runtime_id,
        transform_runtime_fingerprint=runtime.runtime_fingerprint,
        expected_total_images=len(ordered),
        ordered_image_ids=ordered,
        ordered_image_ids_hash=ordered_image_ids_hash(ordered),
        source_commit=software.source_revision,
        source_tree_clean=software.source_tree_clean,
    )
    fingerprint = preparation_definition_fingerprint(_DefinitionDraft(**draft))
    return PreparationDefinition(
        definition_id=preparation_definition_id(fingerprint),
        definition_fingerprint=fingerprint,
        created_utc=_utc_now(),
        **draft,
    )


class _DefinitionDraft:
    """A definition-shaped stand-in used only to compute the fingerprint."""

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

    def __init__(self, **fields: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def _combined_image_manifest_hash(inputs: SD300Inputs) -> str:
    """One digest over all three releases' image manifests.

    The set covers three releases, and a change to any of them changes what was
    materialised. Naming them separately in the set fingerprint would be
    equivalent; folding them into one keeps the manifest a fixed shape.
    """
    return preparation_source_bundle(inputs).image_manifest_hash


def _cohort_fingerprint(inputs: SD300Inputs) -> str:
    return preparation_source_bundle(inputs).cohort_fingerprint


def _collect_entries(
    store: PreparedImageSetStore, definition: PreparationDefinition
) -> tuple[PreparedImageEntry, ...]:
    entries: list[PreparedImageEntry] = []
    missing: list[str] = []
    for ordinal, image_id in enumerate(definition.ordered_image_ids):
        if not store.has_entry(definition.definition_id, str(image_id)):
            missing.append(str(image_id))
            continue
        entry = store.read_entry_by_image_id(definition.definition_id, str(image_id))
        if entry.ordinal != ordinal:
            raise PreparationFinalizationError(
                f"{image_id} is recorded at ordinal {entry.ordinal}, but the "
                f"definition places it at {ordinal}"
            )
        entries.append(entry)
    if missing:
        raise PreparationFinalizationError(
            f"{len(missing)} of {definition.expected_total_images} images have not "
            f"been materialised, starting with {missing[:3]}"
        )
    return tuple(entries)


def _build_summary(
    *,
    manifest: PreparedImageSetManifest,
    entries: tuple[PreparedImageEntry, ...],
    images: Mapping[ImageId, ImageRecord],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
) -> dict[str, Any]:
    """Operational counts, regenerable and never part of the set's identity.

    Every number here is derivable from the entries, so the verifier recomputes
    it rather than believing it (spec section 36).
    """
    by_release: dict[str, int] = {}
    by_impression: dict[str, int] = {}
    by_source_ppi: dict[str, int] = {}
    by_action: dict[str, int] = {}
    source_bytes = 0
    output_bytes = 0

    for entry in entries:
        record = images.get(entry.image_id)
        release = record.release if record else "unknown"
        by_release[release] = by_release.get(release, 0) + 1
        if record is not None:
            impression = record.impression.value
            by_impression[impression] = by_impression.get(impression, 0) + 1
        key = str(entry.source_effective_ppi)
        by_source_ppi[key] = by_source_ppi.get(key, 0) + 1
        by_action[entry.transform_action] = by_action.get(entry.transform_action, 0) + 1
        source_bytes += entry.source_size_bytes
        output_bytes += entry.output_size_bytes

    return {
        "preparation_set_id": manifest.preparation_set_id,
        "preparation_set_fingerprint": manifest.preparation_set_fingerprint,
        "transform_profile_id": profile.profile_id,
        "transform_runtime_id": runtime.runtime_id,
        "total_images": len(entries),
        "images_by_release": dict(sorted(by_release.items())),
        "images_by_impression": dict(sorted(by_impression.items())),
        "images_by_source_ppi": dict(sorted(by_source_ppi.items())),
        "images_by_transform_action": dict(sorted(by_action.items())),
        "total_source_bytes": source_bytes,
        "total_output_bytes": output_bytes,
        "generated_utc": _utc_now(),
    }


def _load_prepared(
    *,
    workspace: Path,
    dataset_root: Path | None,
    config: PreparationExperimentConfig | None,
    repository_root: Path,
    definition_id: str | None,
    require_clean: bool,
    require_runtime_match: bool = True,
) -> PreparedMaterialisation:
    """Reconstruct what ``prepare`` already wrote. Never re-derives it."""
    workspace = Path(workspace)
    config = config or load_preparation_config(repository_root=repository_root)
    software = _capture_provenance(repository_root, require_clean=require_clean)

    resolved = definition_id or _read_pointer(workspace, config.experiment_id)
    store = PreparedImageSetStore(workspace)
    container = store.pending_dir(resolved)
    definition = store.read_definition(container)
    profile = store.read_transform_profile(container)
    runtime = store.read_runtime(container)

    if profile.profile_fingerprint != definition.transform_profile_fingerprint:
        raise PreparationDerivationError(
            "the stored profile is not the profile this preparation was defined "
            "under"
        )
    if runtime.runtime_fingerprint != definition.transform_runtime_fingerprint:
        raise PreparationDerivationError(
            "the stored runtime is not the runtime this preparation was defined "
            "under"
        )
    if require_runtime_match and definition.source_commit != software.source_revision:
        raise PreparationDerivationError(
            f"this preparation was defined from commit "
            f"{definition.source_commit[:12]} but this invocation is running "
            f"{software.source_revision[:12]}. A materialisation cannot be resumed "
            "under different code (docs/adr/0017)"
        )

    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
    )
    if inputs.pair_manifest_hash != definition.pair_manifest_hash:
        raise PreparationDerivationError(
            "the pair manifest has changed since this preparation was defined"
        )
    return PreparedMaterialisation(
        config=config,
        software=software,
        inputs=inputs,
        workspace=workspace,
        profile=profile,
        runtime=runtime,
        definition=definition,
    )


def _pointer_path(workspace: Path, experiment_id: str) -> Path:
    return Path(workspace) / "experiments" / experiment_id / _POINTER_NAME


def _write_pointer(
    workspace: Path, experiment_id: str, payload: Mapping[str, Any]
) -> Path:
    return write_json(_pointer_path(workspace, experiment_id), dict(payload))


def _read_pointer(workspace: Path, experiment_id: str) -> str:
    path = _pointer_path(workspace, experiment_id)
    if not path.is_file():
        raise ResearchPreflightError(
            f"no prepared materialisation for {experiment_id} in this workspace; "
            "run 'prepare' first, or pass --definition-id"
        )
    payload = read_json(path)
    resolved = str(payload.get("definition_id") or "")
    if not resolved:
        raise ResearchPreflightError(f"{path} names no preparation definition")
    return resolved


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sd300_canonical500_images",
        description=(
            "Materialise the shared canonical 500 ppi input set for SD300. "
            "Produces images and provenance; compares nothing and measures nothing."
        ),
    )
    parser.add_argument(
        "command", choices=("prepare", "materialize", "status", "finalize")
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Overrides FPBENCH_SD300_ROOT for this invocation.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--max-new-images",
        type=int,
        default=None,
        help="Stop after this many new images. Existing entries are verified and "
        "skipped without counting against the budget.",
    )
    parser.add_argument("--definition-id", default=None)
    parser.add_argument(
        "--recompute-pixels",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="During status, re-run every transform (default: enabled).",
    )
    parser.add_argument(
        "--no-sources",
        action="store_true",
        help="During status, check only what is reachable from the workspace.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    config = load_preparation_config(arguments.config)
    shared = {
        "workspace": arguments.workspace,
        "dataset_root": arguments.dataset_root,
        "config": config,
    }

    try:
        if arguments.command == "prepare":
            prepared = prepare_canonical500_images(**shared)
            print(f"definition   {prepared.definition.definition_id}")
            print(f"profile      {prepared.profile.profile_id}")
            print(f"runtime      {prepared.runtime.runtime_id} "
                  f"(Pillow {prepared.runtime.pillow_version})")
            print(f"images       {prepared.definition.expected_total_images}")
            print(f"source       {prepared.software.source_revision[:12]}")
            return 0

        if arguments.command == "materialize":
            summary = materialize_canonical500_images(
                **shared,
                definition_id=arguments.definition_id,
                max_new_images=arguments.max_new_images,
            )
            print(f"definition   {summary.definition_id}")
            print(f"materialised {summary.newly_materialised}")
            print(f"reused       {summary.reused_existing}")
            print(f"remaining    {summary.remaining} of {summary.expected_images}")
            print(f"wall         {summary.wall_seconds}s")
            if summary.complete:
                print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_canonical500_images(
                **shared,
                definition_id=arguments.definition_id,
                with_sources=not arguments.no_sources,
                recompute_pixels=arguments.recompute_pixels,
            )
            print(f"definition   {state.definition_id}")
            print(f"set          {state.preparation_set_id or '-'}")
            print(f"status       {state.status.value}")
            print(f"images       {state.materialised_images} of "
                  f"{state.expected_images} ({state.missing_images} missing)")
            print(f"manifest     {'valid' if state.manifest_valid else 'no'}")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            print(f"marker       {'valid' if state.finalization_valid else 'no'}")
            for issue in state.issues[:10]:
                print(f"  issue      {issue}")
            return 0

        state = finalize_canonical500_images(
            **shared, definition_id=arguments.definition_id
        )
        print(f"set          {state.preparation_set_id}")
        print(f"status       {state.status.value}")
        print(f"images       {state.materialised_images}")
        print(
            "receipt      evidence/sd300-canonical500-images/"
            f"{state.preparation_set_id}.json"
        )
        return 0
    except (
        ResearchPreflightError,
        ConfigurationError,
        ImagingError,
        PreparationDerivationError,
        PreparationFinalizationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
