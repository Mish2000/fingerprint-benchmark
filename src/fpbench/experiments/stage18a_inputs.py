"""The inputs Stage 18A is allowed to run over, and the proof they are the right ones.

This module exists so that "the same 6,000 comparisons the other four algorithms
ran" is a checked fact rather than a claim in a README. Nothing here selects
anything: every identifier it reads is compared against a constant in
:mod:`fpbench.experiments.stage18a_identity`, and a mismatch raises before a run
exists.

What it reads:

.. code-block:: text

    workspace/prepared-images/prepset_be560e047991/
        manifest.json      the set's own identity, fingerprint and pair-manifest hash
        entries.parquet    3,000 rows: image_id -> relative_path, and the pixel digest

    workspace/manifests/protocols/sd300_50_subjects/cohorts/
        sd300_50_subjects_test_22f8d52a7478/pairs.parquet
                           6,000 rows in protocol order: pair_id, left, right, stage

The pair order is taken from the file and never sorted, because the other four
runs consumed it in exactly this order and an ordering difference is a difference
in what "pair 4,217" means.

Deliberately absent: any use of ``fpbench.protocols``, ``fpbench.execution`` or
the adapter registry. Section 9 of the requirements is explicit that Stage 18A is
not a production integration and must not be made to travel through ``BaseAdapter``
to reach a number. This reads two files that earlier finalised stages produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pyarrow.parquet as pq

from fpbench.core.errors import ConfigurationError
from fpbench.core.serialization import read_json
from fpbench.experiments import stage18a_identity as frozen

__all__ = [
    "REPOSITORY_ROOT",
    "DEFAULT_WORKSPACE",
    "PreparedImage",
    "ComparisonPair",
    "Stage18AInputs",
    "load_stage18a_inputs",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """One canonical 500 ppi image, as the preparation set published it."""

    ordinal: int
    image_id: str
    path: Path
    output_width: int
    output_height: int
    output_pixel_sha256: str
    output_encoded_sha256: str


@dataclass(frozen=True, slots=True)
class ComparisonPair:
    """One of the 6,000 comparisons, in protocol order. ``left`` is the probe."""

    ordinal: int
    pair_id: str
    release: str
    protocol_stage: str
    ground_truth: str
    left_image_id: str
    right_image_id: str


@dataclass(frozen=True, slots=True)
class Stage18AInputs:
    """Everything a reference run consumes, with its provenance attached."""

    preparation_set_id: str
    preparation_set_fingerprint: str
    pair_manifest_hash: str
    cohort_id: str
    protocol_id: str
    dataset_id: str
    transform_profile_id: str
    transform_profile_fingerprint: str

    images: tuple[PreparedImage, ...]
    pairs: tuple[ComparisonPair, ...]

    @property
    def images_by_id(self) -> Mapping[str, PreparedImage]:
        return {image.image_id: image for image in self.images}

    def describe(self) -> dict[str, object]:
        """The binding a receipt publishes. Identifiers only, never a score."""
        return {
            "preparation_set_id": self.preparation_set_id,
            "preparation_set_fingerprint": self.preparation_set_fingerprint,
            "pair_manifest_hash": self.pair_manifest_hash,
            "cohort_id": self.cohort_id,
            "protocol_id": self.protocol_id,
            "dataset_id": self.dataset_id,
            "transform_profile_id": self.transform_profile_id,
            "transform_profile_fingerprint": self.transform_profile_fingerprint,
            "image_count": len(self.images),
            "pair_count": len(self.pairs),
        }


def _require(actual: object, expected: object, what: str) -> None:
    if actual != expected:
        raise ConfigurationError(f"{what}: expected {expected!r}, workspace holds {actual!r}")


def _load_images(prepared_root: Path, workspace: Path) -> tuple[PreparedImage, ...]:
    table = pq.read_table(prepared_root / "entries.parquet")
    rows = table.to_pylist()
    images = []
    for row in rows:
        # relative_path is stored relative to the workspace, not to the set.
        images.append(
            PreparedImage(
                ordinal=int(row["ordinal"]),
                image_id=str(row["image_id"]),
                path=workspace / str(row["relative_path"]),
                output_width=int(row["output_width"]),
                output_height=int(row["output_height"]),
                output_pixel_sha256=str(row["output_pixel_sha256"]),
                output_encoded_sha256=str(row["output_encoded_sha256"]),
            )
        )
    images.sort(key=lambda image: image.ordinal)
    return tuple(images)


def _load_pairs(cohort_root: Path) -> tuple[ComparisonPair, ...]:
    table = pq.read_table(cohort_root / "pairs.parquet")
    rows = table.to_pylist()
    # No sort. The manifest's own row order is the protocol order, and it is what
    # the other four runs consumed.
    return tuple(
        ComparisonPair(
            ordinal=ordinal,
            pair_id=str(row["pair_id"]),
            release=str(row["release"]),
            protocol_stage=str(row["protocol_stage"]),
            ground_truth=str(row["ground_truth"]),
            left_image_id=str(row["left_image_id"]),
            right_image_id=str(row["right_image_id"]),
        )
        for ordinal, row in enumerate(rows)
    )


def load_stage18a_inputs(workspace: Path = DEFAULT_WORKSPACE) -> Stage18AInputs:
    """Read and verify the prepared set and the pair manifest.

    Raises :class:`ConfigurationError` on the first identifier that does not match
    the frozen constants. There is no tolerant mode: a run over a different
    preparation set or a different pair manifest is a different experiment, and
    the point of Stage 18A is that it is not.
    """
    prepared_root = workspace / "prepared-images" / frozen.REFERENCE_PREPARATION_SET_ID
    if not prepared_root.is_dir():
        raise ConfigurationError(f"no prepared image set at {prepared_root}")

    manifest = read_json(prepared_root / "manifest.json")
    _require(manifest["preparation_set_id"], frozen.REFERENCE_PREPARATION_SET_ID, "preparation set id")
    _require(
        manifest["preparation_set_fingerprint"],
        frozen.REFERENCE_PREPARATION_SET_FINGERPRINT,
        "preparation set fingerprint",
    )
    _require(manifest["pair_manifest_hash"], frozen.REFERENCE_PAIR_MANIFEST_HASH, "pair manifest hash")
    _require(manifest["cohort_id"], frozen.REFERENCE_COHORT_ID, "cohort id")
    _require(manifest["protocol_id"], frozen.REFERENCE_PROTOCOL_ID, "protocol id")
    _require(manifest["dataset_id"], frozen.REFERENCE_DATASET_ID, "dataset id")
    _require(int(manifest["total_images"]), frozen.EXPECTED_IMAGES, "prepared image count")

    cohort_root = (
        workspace / "manifests" / "protocols" / frozen.REFERENCE_PROTOCOL_ID / "cohorts" / frozen.REFERENCE_COHORT_ID
    )
    if not cohort_root.is_dir():
        raise ConfigurationError(f"no cohort at {cohort_root}")

    images = _load_images(prepared_root, workspace)
    _require(len(images), frozen.EXPECTED_IMAGES, "prepared image rows")

    pairs = _load_pairs(cohort_root)
    _require(len(pairs), frozen.EXPECTED_PAIR_OUTCOMES, "pair manifest rows")

    # Every pair must resolve to a prepared image on both sides. A pair whose
    # image is absent is a broken manifest, not a per-pair failure to record.
    known = {image.image_id for image in images}
    missing = sorted({side for pair in pairs for side in (pair.left_image_id, pair.right_image_id)} - known)
    if missing:
        raise ConfigurationError(f"{len(missing)} pair image ids are absent from the prepared set, first: {missing[0]}")

    return Stage18AInputs(
        preparation_set_id=str(manifest["preparation_set_id"]),
        preparation_set_fingerprint=str(manifest["preparation_set_fingerprint"]),
        pair_manifest_hash=str(manifest["pair_manifest_hash"]),
        cohort_id=str(manifest["cohort_id"]),
        protocol_id=str(manifest["protocol_id"]),
        dataset_id=str(manifest["dataset_id"]),
        transform_profile_id=str(manifest["transform_profile_id"]),
        transform_profile_fingerprint=str(manifest["transform_profile_fingerprint"]),
        images=images,
        pairs=pairs,
    )
