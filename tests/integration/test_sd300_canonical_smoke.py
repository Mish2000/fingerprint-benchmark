"""Canonicalising a handful of real SD300 images, and checking the arithmetic.

A **compatibility smoke test**, not an experiment. It answers one question: does
the shared canonical transform actually work on this delivery — every release,
every resolution, both impressions — producing the dimensions the formula says
and the pixel identity SD300A is entitled to?

One subject, the first two fingers, plain and rolled, all three releases: twelve
images. Nothing is materialised into a set and nothing is stored; the point is
the transform, not the bookkeeping.

**No biometric conclusion may be drawn from any of this.** Twelve images are
resampled and hashed. Nothing is compared.

Skip policy: when the dataset or the workspace is absent, skip. When they are
present but wrong — a source that does not hash to its manifest digest, a PNG
that is not the format the profile describes — fail. A blanket ``except
Exception: skip`` would turn every real defect into a green run (spec section
106).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import ChecksumStatus, FingerprintPosition, Impression
from fpbench.core.imaging_models import scale_dimension
from fpbench.datasets import load_dataset_spec
from fpbench.imaging.canonical import canonicalise, read_source_raster
from fpbench.imaging.png_chunks import CANONICAL_ALLOWED_CHUNKS, parse_png_chunks
from fpbench.imaging.source_records import resolve_source_path
from fpbench.imaging.transform_profile import load_transform_profile
from fpbench.storage.manifest_store import ManifestStore

pytestmark = [pytest.mark.dataset, pytest.mark.imaging, pytest.mark.canonical500]

REPO = Path(__file__).resolve().parents[2]
DATASET_CONFIG = REPO / "configs" / "datasets" / "sd300.yaml"
WORKSPACE = REPO / "workspace"

RELEASES = ("SD300A", "SD300B", "SD300C")
EXPECTED_SOURCE_PPI = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
SMOKE_POSITIONS = (FingerprintPosition.RIGHT_THUMB, FingerprintPosition.RIGHT_INDEX)


@pytest.fixture(scope="module")
def dataset_root() -> Path:
    try:
        spec = load_dataset_spec(DATASET_CONFIG)
    except Exception as exc:  # noqa: BLE001 - only "no dataset configured" skips
        pytest.skip(f"SD300 is not configured here: {exc}")
    if not Path(spec.root).is_dir():
        pytest.skip(f"SD300 root {spec.root} is not present")
    return Path(spec.root)


@pytest.fixture(scope="module")
def smoke_images(dataset_root):
    """One subject, two fingers, both impressions, all three releases."""
    manifests = ManifestStore(WORKSPACE)
    for release in RELEASES:
        if not manifests.images_path("sd300", release).is_file():
            pytest.skip(
                f"no image manifest for {release}; run the research or preparation "
                "prepare command first"
            )

    selected = []
    for release in RELEASES:
        records = manifests.read_images("sd300", release)
        by_subject: dict[str, list] = {}
        for record in records:
            if record.position in SMOKE_POSITIONS and record.is_single_finger:
                by_subject.setdefault(str(record.subject_id), []).append(record)
        subject = sorted(by_subject)[0]
        for record in sorted(
            by_subject[subject], key=lambda item: (int(item.position), item.impression.value)
        ):
            selected.append(record)

    assert len(selected) == len(RELEASES) * len(SMOKE_POSITIONS) * len(Impression)
    return selected


def test_every_smoke_image_is_the_format_the_profile_describes(
    dataset_root, smoke_images
):
    profile = load_transform_profile()
    for record in smoke_images:
        assert record.checksum_status is ChecksumStatus.VERIFIED, (
            f"{record.image_id} carries no VERIFIED checksum evidence"
        )
        path = resolve_source_path(record, dataset_root)
        source = read_source_raster(path, profile=profile, image_label=str(record.image_id))
        assert source.encoded_sha256 == record.expected_sha256
        assert source.width > 0 and source.height > 0


def test_the_effective_resolution_is_the_manifest_one_not_the_header_one(smoke_images):
    """SD300C declares 5080 and is used at 2000 (docs/adr/0004, docs/adr/0032)."""
    for record in smoke_images:
        assert record.effective_ppi == EXPECTED_SOURCE_PPI[record.release]
    c_records = [r for r in smoke_images if r.release == "SD300C"]
    assert c_records
    declared = {r.metadata_ppi for r in c_records}
    assert declared <= {2000, 5080, None}


def test_sd300a_keeps_its_pixels_exactly(dataset_root, smoke_images):
    """The control invariant: 500 ppi in, the same raster out (spec section 84)."""
    profile = load_transform_profile()
    a_records = [record for record in smoke_images if record.release == "SD300A"]
    assert a_records

    for record in a_records:
        source = read_source_raster(
            resolve_source_path(record, dataset_root),
            profile=profile,
            image_label=str(record.image_id),
        )
        artifact = canonicalise(
            source,
            profile=profile,
            source_ppi=record.effective_ppi,
            image_label=str(record.image_id),
        )
        assert artifact.transform_action == "identity_pixels_reencode"
        assert artifact.pixel_sha256 == source.pixel_sha256
        assert (artifact.width, artifact.height) == (source.width, source.height)


def test_sd300b_halves_and_sd300c_quarters(dataset_root, smoke_images):
    profile = load_transform_profile()
    for release, action in (
        ("SD300B", "downsample_2x_lanczos3"),
        ("SD300C", "downsample_4x_lanczos3"),
    ):
        records = [record for record in smoke_images if record.release == release]
        assert records
        for record in records:
            source = read_source_raster(
                resolve_source_path(record, dataset_root),
                profile=profile,
                image_label=str(record.image_id),
            )
            artifact = canonicalise(
                source,
                profile=profile,
                source_ppi=record.effective_ppi,
                image_label=str(record.image_id),
            )
            assert artifact.transform_action == action
            assert artifact.width == scale_dimension(
                source.width, target_ppi=500, source_ppi=record.effective_ppi
            )
            assert artifact.height == scale_dimension(
                source.height, target_ppi=500, source_ppi=record.effective_ppi
            )


def test_every_output_is_a_conforming_canonical_png(dataset_root, smoke_images):
    profile = load_transform_profile()
    for record in smoke_images:
        source = read_source_raster(
            resolve_source_path(record, dataset_root),
            profile=profile,
            image_label=str(record.image_id),
        )
        artifact = canonicalise(
            source,
            profile=profile,
            source_ppi=record.effective_ppi,
            image_label=str(record.image_id),
        )
        inventory = parse_png_chunks(artifact.encoded_bytes)
        assert inventory.canonical_violations() == ()
        assert set(inventory.chunk_types) <= CANONICAL_ALLOWED_CHUNKS
        assert inventory.header.bit_depth == 8
        assert inventory.header.colour_type == 0
        assert not inventory.header.is_interlaced
        assert inventory.phys.pixels_per_unit_x == 19685
        assert inventory.phys.pixels_per_unit_y == 19685
        assert inventory.phys.unit_specifier == 1


def test_the_same_source_transforms_identically_twice(dataset_root, smoke_images):
    """Determinism on real data, which is what makes a set reusable."""
    profile = load_transform_profile()
    record = smoke_images[-1]
    path = resolve_source_path(record, dataset_root)
    first = canonicalise(
        read_source_raster(path, profile=profile),
        profile=profile,
        source_ppi=record.effective_ppi,
    )
    second = canonicalise(
        read_source_raster(path, profile=profile),
        profile=profile,
        source_ppi=record.effective_ppi,
    )
    assert first.pixel_sha256 == second.pixel_sha256
    assert first.encoded_sha256 == second.encoded_sha256
