"""Decoding, resampling and re-encoding one image, with nothing left implicit.

This is the only place in the project where a fingerprint's pixels change, and
it is deliberately a long way from any adapter. Everything an algorithm is
handed under a canonical profile came through here, so a matcher cannot
advantage itself with a better downsampler and a comparison between two matchers
stays a comparison between two matchers (docs/adr/0031).

Three passes, in this order, and none of them is optional:

**Preflight** reads the container before the decoder does. A palette, an alpha
channel or a colour-management chunk makes "what is this pixel's grey value?" a
question with more than one answer, and an ambiguous source is refused rather
than resolved by whichever library is installed. The declared ``pHYs`` is read
and recorded, and then ignored: the scale comes from the manifest's effective
ppi, because SD300C's header says 5080 and SD300C is 2000 (docs/adr/0032).

**Transform** is one resampling from the source raster to the final size, or no
resampling at all. SD300A is already at 500 ppi and its raster is preserved byte
for byte — but it is still decoded and re-encoded, so that all three releases
reach an adapter through the same encoder with the same metadata. Copying the
file would be faster and would leave SD300A carrying NIST's PNG encoding while
B and C carried ours.

**Verification** re-reads what was written. ``Image.save()`` returning without
raising is not evidence that the file on disk decodes to the raster that went
in; the pixel hash computed before encoding is compared against one computed
after decoding, and the chunk policy is re-checked against the actual bytes.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fpbench.core.errors import ImagingError, SourceImageContractError
from fpbench.core.imaging_models import (
    TRANSFORM_ACTION_DOWNSAMPLE_PREFIX,
    TRANSFORM_ACTION_IDENTITY,
    ImageTransformProfile,
    canonical_pixel_hash,
    dimension_rounding_error_halves,
    extent_error_ppm,
    scale_dimension,
)
from fpbench.imaging.png_chunks import (
    PngChunkInventory,
    parse_png_chunks,
    read_png_inventory,
)

__all__ = [
    "SourceRaster",
    "CanonicalArtifact",
    "read_source_raster",
    "transform_action_for",
    "canonicalise",
    "encode_canonical_png",
    "verify_canonical_png",
    "MAX_ROUNDING_ERROR_HALF_PIXELS",
]

#: The most nearest-half-up rounding can be off by, per axis: half an output
#: pixel. Expressed in the integer units :func:`dimension_rounding_error_halves`
#: returns, that limit is exactly ``source_ppi``.
MAX_ROUNDING_ERROR_HALF_PIXELS = 1


@dataclass(frozen=True, slots=True)
class SourceRaster:
    """One decoded source image, and what its container declared.

    ``raster`` is row-major, one byte per pixel, with no stride and no padding —
    the same layout :func:`canonical_pixel_hash` is defined over.
    """

    width: int
    height: int
    raster: bytes
    pixel_sha256: str

    encoded_sha256: str
    size_bytes: int

    declared_ppi: str | None
    inventory: PngChunkInventory


@dataclass(frozen=True, slots=True)
class CanonicalArtifact:
    """One canonical image, in memory, with both of its identities.

    Produced before anything is written, so that a materialisation can compare
    what it is about to store against what it later reads back.
    """

    width: int
    height: int
    raster: bytes

    pixel_sha256: str
    encoded_bytes: bytes
    encoded_sha256: str
    size_bytes: int

    transform_action: str
    scale_numerator: int
    scale_denominator: int

    extent_error_ppm_x: int
    extent_error_ppm_y: int


# --------------------------------------------------------------------- decode


def read_source_raster(
    path: Path, *, profile: ImageTransformProfile, image_label: str = ""
) -> SourceRaster:
    """Read one source PNG and prove it is the input the profile describes.

    Raises:
        SourceImageContractError: the file is not a single-frame, 8-bit,
            non-interlaced, palette-free, alpha-free grayscale PNG, or it
            carries a chunk that makes its grey values ambiguous. Never
            converted: an RGB image flattened quietly, or a 16-bit image
            narrowed quietly, would change what the experiment measured without
            changing anything the experiment records (spec section 14).
    """
    from PIL import Image

    label = image_label or Path(path).name
    data = Path(path).read_bytes()
    try:
        inventory = parse_png_chunks(data)
    except ImagingError as exc:
        raise SourceImageContractError(f"{label}: {exc}") from None

    header = inventory.header
    if header.colour_type != 0:
        raise SourceImageContractError(
            f"{label}: PNG colour type is {header.colour_type}, expected 0 "
            "(grayscale). A colour or paletted source is not converted silently; "
            "it needs a profile that says what happens to it"
        )
    if header.bit_depth != profile.input_bit_depth:
        raise SourceImageContractError(
            f"{label}: PNG bit depth is {header.bit_depth}, expected "
            f"{profile.input_bit_depth}. Narrowing 16-bit samples to 8 discards "
            "information and is a decision a profile has to make explicitly"
        )
    if header.is_interlaced:
        raise SourceImageContractError(
            f"{label}: the source is interlaced; the canonical raster is defined "
            "over a progressive row-major scan"
        )
    ambiguities = inventory.source_ambiguities()
    if ambiguities:
        raise SourceImageContractError(
            f"{label}: carries {', '.join(ambiguities)}, which change what a sample "
            "means or how it should be interpreted. This profile defines no "
            "handling for them, and guessing would put the guess in every score"
        )

    with Image.open(io.BytesIO(data)) as opened:
        frames = getattr(opened, "n_frames", 1)
        if frames != profile.input_frame_count:
            raise SourceImageContractError(
                f"{label}: the source holds {frames} frames, expected "
                f"{profile.input_frame_count}"
            )
        if opened.mode != "L":
            raise SourceImageContractError(
                f"{label}: Pillow decoded mode {opened.mode!r}, expected 'L'. The "
                "container and the decoder disagree, and neither is overruled here"
            )
        opened.load()
        if opened.size != (header.width, header.height):
            raise SourceImageContractError(
                f"{label}: IHDR declares {header.width}x{header.height} but the "
                f"decoder produced {opened.size[0]}x{opened.size[1]}"
            )
        raster = opened.tobytes()

    expected_bytes = header.width * header.height
    if len(raster) != expected_bytes:
        raise SourceImageContractError(
            f"{label}: decoded to {len(raster)} bytes, expected {expected_bytes} for "
            f"a {header.width}x{header.height} gray8 raster"
        )

    phys = inventory.phys
    declared = None
    if phys is not None:
        declared = (
            f"{phys.pixels_per_unit_x}x{phys.pixels_per_unit_y}"
            f"/unit{phys.unit_specifier}"
        )

    return SourceRaster(
        width=header.width,
        height=header.height,
        raster=raster,
        pixel_sha256=canonical_pixel_hash(
            width=header.width, height=header.height, raster=raster
        ),
        encoded_sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        declared_ppi=declared,
        inventory=inventory,
    )


# ------------------------------------------------------------------ transform


def transform_action_for(*, source_ppi: int, target_ppi: int, profile) -> str:
    """Name the operation, so a stored entry says what was done to it.

    ``identity_pixels_reencode`` when nothing is resampled, otherwise
    ``downsample_<ratio>_<filter><radius>``. The ratio is written as an integer
    multiple where the resolutions divide exactly — which they do for all three
    SD300 releases — and as the rational ``n_over_d`` otherwise, so the name
    never rounds.
    """
    if source_ppi == target_ppi:
        return TRANSFORM_ACTION_IDENTITY
    if source_ppi < target_ppi:
        raise ImagingError(
            f"upsampling {source_ppi} to {target_ppi} ppi is forbidden by every "
            "canonical profile"
        )
    filter_name = f"{profile.resampler_filter}{profile.resampler_radius}"
    if source_ppi % target_ppi == 0:
        ratio = f"{source_ppi // target_ppi}x"
    else:  # pragma: no cover - no SD300 release needs it, but the name must not lie
        ratio = f"{source_ppi}_over_{target_ppi}"
    return f"{TRANSFORM_ACTION_DOWNSAMPLE_PREFIX}_{ratio}_{filter_name}"


def canonicalise(
    source: SourceRaster,
    *,
    profile: ImageTransformProfile,
    source_ppi: int,
    image_label: str = "",
) -> CanonicalArtifact:
    """Produce the canonical raster and its encoded PNG, without writing anything.

    Raises:
        ImagingError: the source is below the target resolution, or the rounding
            error of an axis exceeds half an output pixel. The second cannot
            happen with nearest-half-up arithmetic and is checked anyway,
            because the day it does happen the geometry rule has changed under
            the profile's feet.
    """
    from PIL import Image

    label = image_label or "image"
    target = profile.target_ppi
    if source_ppi < target:
        raise ImagingError(
            f"{label}: the source is {source_ppi} ppi and the target {target}; "
            "upsampling is forbidden"
        )

    action = transform_action_for(
        source_ppi=source_ppi, target_ppi=target, profile=profile
    )
    output_width = scale_dimension(
        source.width, target_ppi=target, source_ppi=source_ppi
    )
    output_height = scale_dimension(
        source.height, target_ppi=target, source_ppi=source_ppi
    )

    for axis, source_pixels, output_pixels in (
        ("x", source.width, output_width),
        ("y", source.height, output_height),
    ):
        error = dimension_rounding_error_halves(
            source_pixels, output_pixels, target_ppi=target, source_ppi=source_ppi
        )
        if error > MAX_ROUNDING_ERROR_HALF_PIXELS * source_ppi:
            raise ImagingError(  # pragma: no cover - unreachable with half-up
                f"{label}: the {axis} axis rounds by more than half an output pixel"
            )

    if action == TRANSFORM_ACTION_IDENTITY:
        # No resize call at all. Not `resize()` to the same size — Pillow would
        # still run the filter, and a filter applied at scale 1 is not the
        # identity for every kernel (spec section 19).
        if (output_width, output_height) != (source.width, source.height):
            raise ImagingError(  # pragma: no cover - arithmetic forbids it
                f"{label}: the identity path changed the dimensions"
            )
        raster = source.raster
    else:
        with Image.frombytes(
            "L", (source.width, source.height), source.raster
        ) as decoded:
            resized = decoded.resize(
                (output_width, output_height),
                resample=Image.Resampling.LANCZOS,
                reducing_gap=None,
            )
            try:
                raster = resized.tobytes()
            finally:
                resized.close()

    pixel_sha256 = canonical_pixel_hash(
        width=output_width, height=output_height, raster=raster
    )
    if action == TRANSFORM_ACTION_IDENTITY and pixel_sha256 != source.pixel_sha256:
        raise ImagingError(  # pragma: no cover - the raster is the same object
            f"{label}: the identity path did not preserve the raster"
        )

    encoded = encode_canonical_png(
        width=output_width, height=output_height, raster=raster, profile=profile
    )

    return CanonicalArtifact(
        width=output_width,
        height=output_height,
        raster=raster,
        pixel_sha256=pixel_sha256,
        encoded_bytes=encoded,
        encoded_sha256=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        transform_action=action,
        scale_numerator=target,
        scale_denominator=source_ppi,
        extent_error_ppm_x=extent_error_ppm(
            source.width, output_width, target_ppi=target, source_ppi=source_ppi
        ),
        extent_error_ppm_y=extent_error_ppm(
            source.height, output_height, target_ppi=target, source_ppi=source_ppi
        ),
    )


# --------------------------------------------------------------------- encode


def encode_canonical_png(
    *, width: int, height: int, raster: bytes, profile: ImageTransformProfile
) -> bytes:
    """Encode a gray8 raster as the canonical PNG this profile defines.

    Written to memory rather than to a path, so the bytes can be hashed and
    policy-checked before any file exists. The only metadata is ``pHYs``: no
    creation time, no software name, no source filename, no image id. A text
    chunk is exactly where a dataset inventory leaks out of a workspace and into
    something shareable (spec section 27).
    """
    from PIL import Image

    if profile.output_colour_model != "grayscale" or profile.output_bit_depth != 8:
        raise ImagingError(  # pragma: no cover - the parser forbids it
            "this encoder writes 8-bit grayscale only"
        )

    buffer = io.BytesIO()
    with Image.frombytes("L", (width, height), raster) as image:
        image.save(
            buffer,
            format="PNG",
            optimize=profile.output_optimize,
            compress_level=profile.output_compression_level,
            # Pillow converts this to pHYs as int(dpi / 0.0254 + 0.5), which for
            # 500 is exactly the 19685 pixels per metre the profile pins. The
            # result is verified below rather than assumed.
            dpi=(profile.target_ppi, profile.target_ppi),
        )
    encoded = buffer.getvalue()

    inventory = parse_png_chunks(encoded)
    _require_canonical_container(
        inventory, profile=profile, width=width, height=height, label="the new PNG"
    )
    return encoded


# --------------------------------------------------------------------- verify


def verify_canonical_png(
    path: Path,
    *,
    profile: ImageTransformProfile,
    expected_width: int,
    expected_height: int,
    expected_pixel_sha256: str,
    expected_encoded_sha256: str | None = None,
    expected_size_bytes: int | None = None,
    image_label: str = "",
) -> Mapping[str, object]:
    """Re-read a written canonical PNG and re-derive everything about it.

    ``Image.save()`` not raising says the encoder ran, not that the file on disk
    decodes to the raster that went into it. So the bytes are re-read, the
    container is re-parsed, the raster is re-decoded and re-hashed, and the
    result is compared with what was computed before encoding (spec section 29).

    Raises:
        ImagingError: any of it disagrees.
    """
    from PIL import Image

    label = image_label or Path(path).name
    file_path = Path(path)
    if file_path.is_symlink():
        raise ImagingError(
            f"{label}: the canonical artefact is a symlink; a prepared set owns its "
            "bytes rather than pointing at someone else's"
        )
    if not file_path.is_file():
        raise ImagingError(f"{label}: the canonical artefact is missing: {file_path}")

    data = file_path.read_bytes()
    encoded_sha256 = hashlib.sha256(data).hexdigest()
    size_bytes = len(data)
    if expected_encoded_sha256 is not None and encoded_sha256 != expected_encoded_sha256:
        raise ImagingError(
            f"{label}: the stored file hashes to {encoded_sha256[:12]}..., expected "
            f"{expected_encoded_sha256[:12]}..."
        )
    if expected_size_bytes is not None and size_bytes != expected_size_bytes:
        raise ImagingError(
            f"{label}: the stored file is {size_bytes} bytes, expected "
            f"{expected_size_bytes}"
        )

    inventory = parse_png_chunks(data)
    _require_canonical_container(
        inventory,
        profile=profile,
        width=expected_width,
        height=expected_height,
        label=label,
    )

    with Image.open(io.BytesIO(data)) as opened:
        if opened.mode != "L":
            raise ImagingError(
                f"{label}: decoded mode is {opened.mode!r}, expected 'L'"
            )
        opened.load()
        raster = opened.tobytes()

    pixel_sha256 = canonical_pixel_hash(
        width=expected_width, height=expected_height, raster=raster
    )
    if pixel_sha256 != expected_pixel_sha256:
        raise ImagingError(
            f"{label}: the file decodes to raster {pixel_sha256[:12]}..., but the "
            f"entry records {expected_pixel_sha256[:12]}...; the encoder and the "
            "decoder disagree about these pixels"
        )

    return {
        "encoded_sha256": encoded_sha256,
        "size_bytes": size_bytes,
        "pixel_sha256": pixel_sha256,
        "width": expected_width,
        "height": expected_height,
        "chunk_counts": dict(inventory.counts()),
    }


# ----------------------------------------------------------------- internals


def _require_canonical_container(
    inventory: PngChunkInventory,
    *,
    profile: ImageTransformProfile,
    width: int,
    height: int,
    label: str,
) -> None:
    problems = list(inventory.canonical_violations())

    header = inventory.header
    if (header.width, header.height) != (width, height):
        problems.append(
            f"declares {header.width}x{header.height}, expected {width}x{height}"
        )
    if header.colour_type != 0:
        problems.append(
            f"declares PNG colour type {header.colour_type}, expected 0 (grayscale)"
        )
    if header.bit_depth != profile.output_bit_depth:
        problems.append(
            f"declares bit depth {header.bit_depth}, expected {profile.output_bit_depth}"
        )
    if header.is_interlaced != profile.output_interlaced:
        problems.append("is interlaced" if header.is_interlaced else "is not interlaced")

    phys = inventory.phys
    if phys is None:
        problems.append("declares no pHYs resolution")
    else:
        if not phys.declares_metre:
            problems.append(
                f"declares pHYs unit {phys.unit_specifier}, expected 1 (metre)"
            )
        if phys.pixels_per_unit_x != profile.output_pixels_per_meter_x:
            problems.append(
                f"declares {phys.pixels_per_unit_x} pixels per metre on x, expected "
                f"{profile.output_pixels_per_meter_x}"
            )
        if phys.pixels_per_unit_y != profile.output_pixels_per_meter_y:
            problems.append(
                f"declares {phys.pixels_per_unit_y} pixels per metre on y, expected "
                f"{profile.output_pixels_per_meter_y}"
            )

    if problems:
        raise ImagingError(f"{label}: " + "; ".join(problems))


def inventory_of(path: Path) -> PngChunkInventory:
    """Read one file's chunk inventory. A thin re-export for callers and tests."""
    return read_png_inventory(path)
