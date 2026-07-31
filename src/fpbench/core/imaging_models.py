"""What a shared canonical image set is, written down so it can be checked.

Everything here describes an *input* to an experiment, never an output of one.
There is no algorithm in this module, no score, no threshold and no adapter: a
prepared-image set is materialised once and handed unchanged to every algorithm
evaluated under the same profile, which is the whole of docs/adr/0031 and
docs/adr/0033.

Four identities are kept apart on purpose, because collapsing any two of them
would make a real difference invisible:

``profile_fingerprint``
    What transformation was asked for — target resolution, resampler, rounding
    rule, output pixel format, forbidden operations. Semantics only. The
    installed Pillow version is deliberately *not* in here (spec section 11).

``runtime_fingerprint``
    What actually computed it — the exact Pillow distribution bytes, the
    interpreter, the dependency lock, the fpbench commit. Two runtimes under one
    profile are two sets, because Lanczos is a specification and an
    implementation, and only the specification is in the profile.

``pixel_sha256``
    Whether the raster is the same. Independent of PNG compression: re-encoding
    the same pixels at a different compression level must not look like new
    data (docs/adr/0034).

``encoded_sha256``
    Whether the exact file the adapter opened is the same. That is a different
    question, and both are load-bearing.

Why the dataclasses live in ``core`` rather than in ``fpbench.imaging``: the
storage layer persists them and ``storage`` may only import ``core``. The rules
for *producing* them — decoding, resampling, encoding, verifying — stay in
:mod:`fpbench.imaging`, which re-exports the containers so callers can import
model and factory from one place.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Iterable, Mapping

from fpbench.core.identifiers import ImageId, validate_id
from fpbench.core.serialization import (
    freeze_str_mapping,
    require_exact_int,
    stable_hash,
)

__all__ = [
    "IMAGING_SCHEMA_VERSION",
    "TRANSFORM_PROFILE_SCHEMA_VERSION",
    "TRANSFORM_RUNTIME_SCHEMA_VERSION",
    "PREPARED_ENTRY_SCHEMA_VERSION",
    "PREPARATION_SET_SCHEMA_VERSION",
    "PREPARATION_RECEIPT_SCHEMA_VERSION",
    "PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION",
    "PREPARATION_FINALIZATION_SCHEMA_VERSION",
    "PIXEL_HASH_MAGIC",
    "TRANSFORM_ACTION_IDENTITY",
    "TRANSFORM_ACTION_DOWNSAMPLE_PREFIX",
    "FORBIDDEN_OPERATIONS",
    "PREPARATION_SET_ID_LENGTH",
    "scale_dimension",
    "dimension_rounding_error_halves",
    "extent_error_ppm",
    "canonical_pixel_hash",
    "ImageTransformProfile",
    "image_transform_profile_fingerprint",
    "TransformRuntimeManifest",
    "transform_runtime_fingerprint",
    "transform_runtime_id",
    "PreparationDefinition",
    "PreparationSourceBundle",
    "preparation_definition_fingerprint",
    "preparation_definition_id",
    "ordered_image_ids_hash",
    "PreparedImageEntry",
    "prepared_image_entry_hash",
    "PreparedImageSetManifest",
    "ordered_prepared_entries_hash",
    "preparation_set_fingerprint",
    "preparation_set_id",
    "PreparationReceipt",
    "preparation_receipt_fingerprint",
    "preparation_receipt_content_hash",
    "PreparationTransformAudit",
    "preparation_transform_audit_fingerprint",
    "preparation_transform_audit_content_hash",
    "PreparationFinalizationMarker",
    "preparation_finalization_fingerprint",
    "NO_RESOLUTION_CONCLUSION_STATEMENT",
]

#: Bumped when the meaning of any imaging record changes. Inside every
#: fingerprint below, so a bump separates new artefacts from old rather than
#: silently reusing their identities.
IMAGING_SCHEMA_VERSION = "1"
TRANSFORM_PROFILE_SCHEMA_VERSION = "1"
TRANSFORM_RUNTIME_SCHEMA_VERSION = "1"
PREPARED_ENTRY_SCHEMA_VERSION = "1"
PREPARATION_SET_SCHEMA_VERSION = "1"
PREPARATION_RECEIPT_SCHEMA_VERSION = "2"
PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION = "1"
PREPARATION_FINALIZATION_SCHEMA_VERSION = "2"

#: Twelve hex characters, matching ``run_id``, ``plan_id`` and ``result_set_id``.
PREPARATION_SET_ID_LENGTH = 12

#: Prefixed onto the raster before hashing so that a bare byte string can never
#: be mistaken for a canonical raster, and so that a future v2 raster layout
#: cannot collide with a v1 one (spec section 26).
PIXEL_HASH_MAGIC = b"fpbench.gray8.v1\x00"

#: The source was already at the target resolution: decoded, checked and
#: re-encoded canonically, with the raster preserved byte for byte.
TRANSFORM_ACTION_IDENTITY = "identity_pixels_reencode"

#: Every reducing action starts with this. The suffix names the ratio and the
#: filter, e.g. ``downsample_4x_lanczos3``.
TRANSFORM_ACTION_DOWNSAMPLE_PREFIX = "downsample"

#: Operations a canonical profile must declare forbidden, by name. Listed here
#: rather than left implicit so that a profile which simply forgets one is
#: rejected instead of quietly permitting it (spec section 8).
FORBIDDEN_OPERATIONS: tuple[str, ...] = (
    "binarize",
    "contrast_normalize",
    "crop",
    "denoise",
    "gamma_transform",
    "histogram_equalize",
    "invert",
    "mirror",
    "pad",
    "rotate",
    "sharpen",
)

#: Printed on a preparation receipt. A canonical set proves that every
#: algorithm was handed the same pixels; it says nothing at all about whether
#: those pixels match better.
NO_RESOLUTION_CONCLUSION_STATEMENT = (
    "This receipt proves that one shared canonical input set was materialised "
    "and verified. It contains no comparison, no threshold, no metric and no "
    "claim about resolution."
)

_HEX = frozenset("0123456789abcdef")


# ---------------------------------------------------------------- validation


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_empty(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _require_positive_int(value: object, field_name: str) -> int:
    number = require_exact_int(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} must be positive, got {number}")
    return number


def _require_non_negative_int(value: object, field_name: str) -> int:
    number = require_exact_int(value, field_name)
    if number < 0:
        raise ValueError(f"{field_name} must not be negative, got {number}")
    return number


def _require_relative_path(value: str, field_name: str) -> str:
    text = _require_non_empty(value, field_name)
    if PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute():
        raise ValueError(f"{field_name} must be workspace-relative, got {text!r}")
    if ".." in PurePosixPath(text.replace("\\", "/")).parts:
        raise ValueError(f"{field_name} must not escape the workspace, got {text!r}")
    return text


def _freeze_bool_mapping(
    value: Mapping[str, bool], field_name: str
) -> Mapping[str, bool]:
    frozen: dict[str, bool] = {}
    for key, item in sorted(dict(value).items()):
        if type(item) is not bool:
            raise ValueError(
                f"{field_name}[{key}] must be a bool, got {type(item).__name__}"
            )
        frozen[str(key)] = item
    return MappingProxyType(frozen)


# ------------------------------------------------------------------- geometry


def scale_dimension(source_pixels: int, *, target_ppi: int, source_ppi: int) -> int:
    """One axis, resampled to ``target_ppi``, rounded half up.

    Pure integer arithmetic. ``round()`` is deliberately not used: Python rounds
    ties to even, so a 1001-pixel axis at 1000 ppi would become 500 while a
    999-pixel one became 500 as well, and two images differing by two pixels
    would silently land on the same size by different rules. Half-up is one
    rule, stated once, and reproducible in any language::

        scaled  = source_pixels x target_ppi / source_ppi
        output  = floor(scaled + 1/2)
                = (2 x source_pixels x target_ppi + source_ppi)
                  // (2 x source_ppi)

    Raises:
        ValueError: any input is not an exact positive integer, or the result
            would round away to nothing. A zero-pixel image is not a smaller
            image, it is an absent one.
    """
    pixels = _require_positive_int(source_pixels, "source_pixels")
    target = _require_positive_int(target_ppi, "target_ppi")
    source = _require_positive_int(source_ppi, "source_ppi")

    numerator = 2 * pixels * target + source
    denominator = 2 * source
    output = numerator // denominator
    if output < 1:
        raise ValueError(
            f"scaling {pixels}px from {source} to {target} ppi rounds to "
            f"{output}px; a canonical image must keep at least one pixel per axis"
        )
    return output


def dimension_rounding_error_halves(
    source_pixels: int, output_pixels: int, *, target_ppi: int, source_ppi: int
) -> int:
    """``|2 x (output - exact)| x source_ppi``, as an exact integer.

    The rounding error of one axis, expressed so it can be compared against a
    limit without a float ever appearing. Half an output pixel — the most
    nearest-half-up rounding can ever be off by — is exactly ``source_ppi``.
    """
    pixels = _require_positive_int(source_pixels, "source_pixels")
    output = _require_positive_int(output_pixels, "output_pixels")
    target = _require_positive_int(target_ppi, "target_ppi")
    source = _require_positive_int(source_ppi, "source_ppi")
    return abs(2 * output * source - 2 * pixels * target)


def extent_error_ppm(
    source_pixels: int, output_pixels: int, *, target_ppi: int, source_ppi: int
) -> int:
    """How far the physical extent moved, in parts per million, rounded half up.

    ``source_pixels / source_ppi`` inches in, ``output_pixels / target_ppi``
    inches out. Computed from the rational components rather than from two
    floats, so the number recorded on one machine is the number recorded on
    every other (spec section 18).
    """
    pixels = _require_positive_int(source_pixels, "source_pixels")
    output = _require_positive_int(output_pixels, "output_pixels")
    target = _require_positive_int(target_ppi, "target_ppi")
    source = _require_positive_int(source_ppi, "source_ppi")

    # |output/target - pixels/source| / (pixels/source) = |output*source - pixels*target| / (pixels*target)
    numerator = abs(output * source - pixels * target) * 1_000_000
    denominator = pixels * target
    return (2 * numerator + denominator) // (2 * denominator)


# --------------------------------------------------------------- raster identity


def canonical_pixel_hash(*, width: int, height: int, raster: bytes) -> str:
    """The scientific identity of a grayscale raster, independent of its file.

    ``sha256(magic || width || height || raster)`` with both dimensions as
    unsigned 64-bit big-endian integers. The dimensions are inside the digest so
    that a 4x6 raster and a 6x4 raster holding the same bytes in a different
    shape are not the same image (spec section 26).

    Raises:
        ValueError: the raster is not exactly ``width * height`` bytes. One byte
            per pixel, row-major, no padding and no stride — anything else is a
            different raster layout and must not be hashed as if it were this
            one.
    """
    columns = _require_positive_int(width, "width")
    rows = _require_positive_int(height, "height")
    payload = bytes(raster)
    expected = columns * rows
    if len(payload) != expected:
        raise ValueError(
            f"a {columns}x{rows} gray8 raster is {expected} bytes, got {len(payload)}"
        )
    digest = hashlib.sha256()
    digest.update(PIXEL_HASH_MAGIC)
    digest.update(columns.to_bytes(8, "big"))
    digest.update(rows.to_bytes(8, "big"))
    digest.update(payload)
    return digest.hexdigest()


# ------------------------------------------------------------ transform profile


@dataclass(frozen=True, slots=True)
class ImageTransformProfile:
    """The immutable description of one shared canonical transformation.

    Semantics, not implementation. Everything here is a rule a second
    implementation in a second language could follow to produce the same pixels;
    nothing here is a fact about the machine that happened to run it. That split
    is what lets ``profile_fingerprint`` stay stable across a Pillow upgrade
    while ``runtime_fingerprint`` correctly does not (spec section 11).
    """

    profile_id: str
    profile_fingerprint: str
    profile_version: str

    input_media_type: str
    input_colour_model: str
    input_bit_depth: int
    input_frame_count: int

    target_ppi: int
    source_ppi_field: str
    allow_upsampling: bool
    dimension_rounding: str

    resampler_engine: str
    resampler_filter: str
    resampler_radius: int
    reducing_gap: str | None
    direct_source_to_target: bool

    output_media_type: str
    output_colour_model: str
    output_bit_depth: int
    output_interlaced: bool
    output_compression_level: int
    output_optimize: bool
    output_pixels_per_meter_x: int
    output_pixels_per_meter_y: int

    forbidden_operations: Mapping[str, bool] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.profile_id)
        object.__setattr__(
            self,
            "profile_fingerprint",
            _require_digest(self.profile_fingerprint, "profile_fingerprint"),
        )
        for name in (
            "profile_version",
            "input_media_type",
            "input_colour_model",
            "source_ppi_field",
            "dimension_rounding",
            "resampler_engine",
            "resampler_filter",
            "output_media_type",
            "output_colour_model",
        ):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        for name in (
            "input_bit_depth",
            "input_frame_count",
            "target_ppi",
            "resampler_radius",
            "output_bit_depth",
            "output_pixels_per_meter_x",
            "output_pixels_per_meter_y",
        ):
            object.__setattr__(
                self, name, _require_positive_int(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "output_compression_level",
            _require_non_negative_int(
                self.output_compression_level, "output_compression_level"
            ),
        )
        for name in (
            "allow_upsampling",
            "direct_source_to_target",
            "output_interlaced",
            "output_optimize",
        ):
            value = getattr(self, name)
            if type(value) is not bool:
                raise ValueError(f"{name} must be a bool, got {type(value).__name__}")
        if self.reducing_gap is not None:
            object.__setattr__(
                self, "reducing_gap", _require_non_empty(self.reducing_gap, "reducing_gap")
            )
        object.__setattr__(
            self,
            "forbidden_operations",
            _freeze_bool_mapping(self.forbidden_operations, "forbidden_operations"),
        )
        object.__setattr__(self, "metadata", freeze_str_mapping(self.metadata))

        if self.output_compression_level > 9:
            raise ValueError("output_compression_level must be between 0 and 9")
        if self.input_frame_count != 1:
            raise ValueError(
                "a canonical transform reads exactly one frame; an animated or "
                "multi-page source is a different contract"
            )

        expected = image_transform_profile_fingerprint(self)
        if self.profile_fingerprint != expected:
            raise ValueError(
                "profile_fingerprint does not cover this profile: expected "
                f"{expected}, got {self.profile_fingerprint}"
            )

    @property
    def transform_action_for_identity(self) -> str:
        return TRANSFORM_ACTION_IDENTITY

    def forbids(self, operation: str) -> bool:
        return bool(self.forbidden_operations.get(operation, False))

    def missing_forbidden_operations(self) -> tuple[str, ...]:
        """Operations this profile neither permits nor forbids, by name.

        A profile that simply omits ``sharpen`` has not permitted sharpening —
        it has failed to say, and a rule nobody wrote down is a rule every
        implementation gets to invent.
        """
        return tuple(
            name
            for name in FORBIDDEN_OPERATIONS
            if not self.forbidden_operations.get(name, False)
        )


def image_transform_profile_fingerprint(profile: ImageTransformProfile) -> str:
    """A 64-character digest of everything the transformation *means*.

    Deliberately excludes the file it was read from, when it was read, the
    display title, the installed Pillow version and the machine's architecture.
    A profile is a specification: two machines reading the same specification
    must agree on its identity even when they cannot agree on anything else
    (spec section 11).
    """
    return stable_hash(
        {
            "schema": "image_transform_profile_fingerprint_v1",
            "imaging_schema_version": IMAGING_SCHEMA_VERSION,
            "transform_profile_schema_version": TRANSFORM_PROFILE_SCHEMA_VERSION,
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "input": {
                "media_type": profile.input_media_type,
                "colour_model": profile.input_colour_model,
                "bit_depth": profile.input_bit_depth,
                "frame_count": profile.input_frame_count,
            },
            "resolution": {
                "source_ppi_field": profile.source_ppi_field,
                "target_ppi": profile.target_ppi,
                "allow_upsampling": profile.allow_upsampling,
                "dimension_rounding": profile.dimension_rounding,
            },
            "resampler": {
                "engine": profile.resampler_engine,
                "filter": profile.resampler_filter,
                "radius": profile.resampler_radius,
                "reducing_gap": profile.reducing_gap,
                "direct_source_to_target": profile.direct_source_to_target,
            },
            "output": {
                "media_type": profile.output_media_type,
                "colour_model": profile.output_colour_model,
                "bit_depth": profile.output_bit_depth,
                "interlaced": profile.output_interlaced,
                "compression_level": profile.output_compression_level,
                "optimize": profile.output_optimize,
                "pixels_per_meter_x": profile.output_pixels_per_meter_x,
                "pixels_per_meter_y": profile.output_pixels_per_meter_y,
            },
            "forbidden_operations": dict(profile.forbidden_operations),
            "metadata": dict(profile.metadata),
        },
        length=64,
    )


# ------------------------------------------------------------ transform runtime


@dataclass(frozen=True, slots=True)
class TransformRuntimeManifest:
    """What actually computed the pixels, pinned by content.

    ``Lanczos3`` names a mathematical kernel; it does not name the code that
    evaluated it. Two Pillow builds can disagree in the last bit of a
    coefficient, and a benchmark whose inputs differ in the last bit is a
    benchmark nobody can reproduce. So the *installed distribution's bytes* are
    fingerprinted, not merely its version string (spec section 24).

    ``created_utc`` is stored and is deliberately outside
    :func:`transform_runtime_fingerprint`: capturing the same environment twice
    an hour apart is the same runtime.
    """

    runtime_id: str
    runtime_fingerprint: str

    software_fingerprint: str
    dependency_lock_sha256: str

    pillow_version: str
    pillow_distribution_fingerprint: str
    pillow_file_count: int

    python_version: str
    python_implementation: str
    platform_system: str
    platform_machine: str
    zlib_runtime_version: str

    source_revision: str
    source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.runtime_id)
        for name in (
            "runtime_fingerprint",
            "software_fingerprint",
            "dependency_lock_sha256",
            "pillow_distribution_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in (
            "pillow_version",
            "python_version",
            "python_implementation",
            "platform_system",
            "platform_machine",
            "zlib_runtime_version",
            "source_revision",
            "created_utc",
        ):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "pillow_file_count",
            _require_positive_int(self.pillow_file_count, "pillow_file_count"),
        )
        if type(self.source_tree_clean) is not bool:
            raise ValueError("source_tree_clean must be a bool")

        expected = transform_runtime_fingerprint(self)
        if self.runtime_fingerprint != expected:
            raise ValueError(
                "runtime_fingerprint does not cover this runtime: expected "
                f"{expected}, got {self.runtime_fingerprint}"
            )
        expected_id = transform_runtime_id(expected)
        if self.runtime_id != expected_id:
            raise ValueError(
                f"runtime_id must be derived from the fingerprint: expected "
                f"{expected_id}, got {self.runtime_id!r}"
            )


def transform_runtime_fingerprint(runtime: TransformRuntimeManifest) -> str:
    """A digest of the machine and the code, with no timestamp in it."""
    return stable_hash(
        {
            "schema": "transform_runtime_fingerprint_v1",
            "imaging_schema_version": IMAGING_SCHEMA_VERSION,
            "transform_runtime_schema_version": TRANSFORM_RUNTIME_SCHEMA_VERSION,
            "software_fingerprint": runtime.software_fingerprint,
            "dependency_lock_sha256": runtime.dependency_lock_sha256,
            "pillow_version": runtime.pillow_version,
            "pillow_distribution_fingerprint": runtime.pillow_distribution_fingerprint,
            "pillow_file_count": runtime.pillow_file_count,
            "python_version": runtime.python_version,
            "python_implementation": runtime.python_implementation,
            "platform_system": runtime.platform_system,
            "platform_machine": runtime.platform_machine,
            "zlib_runtime_version": runtime.zlib_runtime_version,
            "source_revision": runtime.source_revision,
            "source_tree_clean": runtime.source_tree_clean,
        },
        length=64,
    )


def transform_runtime_id(fingerprint: str) -> str:
    """``imgruntime_<12 chars of the runtime fingerprint>``."""
    digest = _require_digest(fingerprint, "runtime_fingerprint")
    return f"imgruntime_{digest[:PREPARATION_SET_ID_LENGTH]}"


# ---------------------------------------------------------- preparation intent


@dataclass(frozen=True, slots=True)
class PreparationSourceBundle:
    """Authoritative external identities a prepared set must be derived from.

    This is intentionally smaller than an experiment's complete input object.
    It carries only the identities that a deep verifier must compare against the
    stored definition and manifest, plus the exact ordered participating image
    ids.  Recomputing a self-consistent prepared set cannot change this object,
    because it is derived independently from the dataset, protocol, cohort and
    pair manifests.
    """

    dataset_id: str
    image_manifest_hash: str
    protocol_id: str
    cohort_id: str
    cohort_fingerprint: str
    pair_manifest_hash: str
    ordered_image_ids: tuple[ImageId, ...]

    def __post_init__(self) -> None:
        for name in ("dataset_id", "protocol_id", "cohort_id"):
            validate_id(getattr(self, name))
        for name in (
            "image_manifest_hash",
            "cohort_fingerprint",
            "pair_manifest_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        ordered = tuple(ImageId(validate_id(str(item))) for item in self.ordered_image_ids)
        if not ordered:
            raise ValueError("a preparation source bundle must name at least one image")
        if len(set(ordered)) != len(ordered):
            raise ValueError("a preparation source bundle names an image more than once")
        object.__setattr__(self, "ordered_image_ids", ordered)


@dataclass(frozen=True, slots=True)
class PreparationDefinition:
    """What a materialisation promised to produce, written before it produced any.

    A set's own fingerprint cannot exist until every image has been transformed,
    because it covers every entry hash. That leaves a gap: between ``prepare``
    and the last write there is a body of work with no identity, and an
    interrupted materialisation resumed under a different profile, a different
    runtime or a different image list would quietly become a mixture.

    The definition closes that gap. It is written first, it names exactly which
    images will be produced and under what, and every later invocation checks
    itself against it before touching a byte (spec sections 43 and 53).
    """

    definition_id: str
    definition_fingerprint: str

    dataset_id: str
    image_manifest_hash: str

    protocol_id: str
    cohort_id: str
    cohort_fingerprint: str
    pair_manifest_hash: str

    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_id: str
    transform_runtime_fingerprint: str

    expected_total_images: int
    ordered_image_ids: tuple[ImageId, ...]
    ordered_image_ids_hash: str

    source_commit: str
    source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "definition_id",
            "dataset_id",
            "protocol_id",
            "cohort_id",
            "transform_profile_id",
            "transform_runtime_id",
        ):
            validate_id(getattr(self, name))
        for name in (
            "definition_fingerprint",
            "image_manifest_hash",
            "cohort_fingerprint",
            "pair_manifest_hash",
            "transform_profile_fingerprint",
            "transform_runtime_fingerprint",
            "ordered_image_ids_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("source_commit", "created_utc"):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        if type(self.source_tree_clean) is not bool:
            raise ValueError("source_tree_clean must be a bool")

        ordered = tuple(ImageId(validate_id(str(item))) for item in self.ordered_image_ids)
        object.__setattr__(self, "ordered_image_ids", ordered)
        object.__setattr__(
            self,
            "expected_total_images",
            _require_positive_int(self.expected_total_images, "expected_total_images"),
        )
        if len(ordered) != self.expected_total_images:
            raise ValueError(
                f"the definition lists {len(ordered)} images but expects "
                f"{self.expected_total_images}"
            )
        if len(set(ordered)) != len(ordered):
            raise ValueError(
                "the definition lists an image twice; a canonical set holds one "
                "artefact per source image"
            )
        if list(ordered) != sorted(ordered):
            raise ValueError(
                "the definition's image ids are not in ascending order; the "
                "materialisation order is part of the set's identity and must not "
                "depend on how a filesystem happened to enumerate a directory"
            )
        expected_ids_hash = ordered_image_ids_hash(ordered)
        if self.ordered_image_ids_hash != expected_ids_hash:
            raise ValueError(
                "ordered_image_ids_hash does not cover these image ids"
            )

        expected = preparation_definition_fingerprint(self)
        if self.definition_fingerprint != expected:
            raise ValueError(
                "definition_fingerprint does not cover this definition: expected "
                f"{expected}, got {self.definition_fingerprint}"
            )
        expected_id = preparation_definition_id(expected)
        if self.definition_id != expected_id:
            raise ValueError(
                f"definition_id must be derived from the fingerprint: expected "
                f"{expected_id}, got {self.definition_id!r}"
            )

    def covers(self, image_id: ImageId) -> bool:
        return image_id in set(self.ordered_image_ids)

    def ordinal_of(self, image_id: ImageId) -> int:
        try:
            return list(self.ordered_image_ids).index(image_id)
        except ValueError:
            raise KeyError(
                f"{image_id} is not one of the {self.expected_total_images} images "
                "this preparation was defined over"
            ) from None


def ordered_image_ids_hash(image_ids: Iterable[ImageId]) -> str:
    """A digest of the exact image list, in materialisation order."""
    return stable_hash(
        {
            "schema": "preparation_ordered_image_ids_v1",
            "image_ids": [str(item) for item in image_ids],
        },
        length=64,
    )


def preparation_definition_fingerprint(definition: PreparationDefinition) -> str:
    """A digest of the promise, with no timestamp in it."""
    return stable_hash(
        {
            "schema": "preparation_definition_fingerprint_v1",
            "imaging_schema_version": IMAGING_SCHEMA_VERSION,
            "preparation_set_schema_version": PREPARATION_SET_SCHEMA_VERSION,
            "dataset_id": definition.dataset_id,
            "image_manifest_hash": definition.image_manifest_hash,
            "protocol_id": definition.protocol_id,
            "cohort_id": definition.cohort_id,
            "cohort_fingerprint": definition.cohort_fingerprint,
            "pair_manifest_hash": definition.pair_manifest_hash,
            "transform_profile_fingerprint": definition.transform_profile_fingerprint,
            "transform_runtime_fingerprint": definition.transform_runtime_fingerprint,
            "expected_total_images": definition.expected_total_images,
            "ordered_image_ids_hash": definition.ordered_image_ids_hash,
        },
        length=64,
    )


def preparation_definition_id(fingerprint: str) -> str:
    """``prepdef_<12 chars of the definition fingerprint>``."""
    digest = _require_digest(fingerprint, "definition_fingerprint")
    return f"prepdef_{digest[:PREPARATION_SET_ID_LENGTH]}"


# --------------------------------------------------------------- prepared entry


@dataclass(frozen=True, slots=True)
class PreparedImageEntry:
    """One source image and the canonical artefact it produced.

    Carries both ends of the transformation, because a canonical image that
    could not name the exact source bytes it came from would be an assertion
    rather than evidence. Both raster identities are kept: the source's, so the
    identity path can be proved to have preserved it, and the output's, so a
    later run can prove it is comparing the same pixels (docs/adr/0034).

    ``relative_path`` is workspace-relative and is deliberately outside
    :func:`prepared_image_entry_hash`: where a workspace sits on one machine is
    not a property of the image.
    """

    ordinal: int
    image_id: ImageId

    source_record_fingerprint: str
    source_expected_sha256: str
    source_size_bytes: int

    source_effective_ppi: int
    source_declared_ppi: str | None

    source_width: int
    source_height: int
    source_pixel_sha256: str

    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str

    transform_action: str
    scale_numerator: int
    scale_denominator: int

    output_width: int
    output_height: int
    output_effective_ppi: int

    output_pixel_sha256: str
    output_encoded_sha256: str
    output_size_bytes: int
    output_media_type: str

    relative_path: str
    entry_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _require_non_negative_int(self.ordinal, "ordinal")
        )
        object.__setattr__(
            self, "image_id", ImageId(validate_id(str(self.image_id)))
        )
        validate_id(self.transform_profile_id)

        for name in (
            "source_record_fingerprint",
            "source_expected_sha256",
            "source_pixel_sha256",
            "transform_profile_fingerprint",
            "transform_runtime_fingerprint",
            "output_pixel_sha256",
            "output_encoded_sha256",
            "entry_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        for name in (
            "source_size_bytes",
            "source_effective_ppi",
            "source_width",
            "source_height",
            "scale_numerator",
            "scale_denominator",
            "output_width",
            "output_height",
            "output_effective_ppi",
            "output_size_bytes",
        ):
            object.__setattr__(
                self, name, _require_positive_int(getattr(self, name), name)
            )

        object.__setattr__(
            self,
            "transform_action",
            _require_non_empty(self.transform_action, "transform_action"),
        )
        object.__setattr__(
            self,
            "output_media_type",
            _require_non_empty(self.output_media_type, "output_media_type"),
        )
        if self.source_declared_ppi is not None:
            object.__setattr__(
                self,
                "source_declared_ppi",
                _require_non_empty(self.source_declared_ppi, "source_declared_ppi"),
            )
        object.__setattr__(
            self,
            "relative_path",
            _require_relative_path(self.relative_path, "relative_path"),
        )

        if self.output_media_type != "image/png":
            raise ValueError(
                "a canonical artefact is a PNG; a different container is a "
                f"different profile, got {self.output_media_type!r}"
            )

        # The scale is a rational number named by its two components, and both
        # ends have to agree with what the entry claims about the resolutions.
        if self.scale_numerator != self.output_effective_ppi:
            raise ValueError(
                f"scale_numerator ({self.scale_numerator}) must be the output "
                f"resolution ({self.output_effective_ppi})"
            )
        if self.scale_denominator != self.source_effective_ppi:
            raise ValueError(
                f"scale_denominator ({self.scale_denominator}) must be the source "
                f"resolution ({self.source_effective_ppi})"
            )
        if self.source_effective_ppi < self.output_effective_ppi:
            raise ValueError(
                f"{self.image_id}: the source is {self.source_effective_ppi} ppi and "
                f"the target {self.output_effective_ppi}; upsampling invents ridge "
                "detail that was never captured and is forbidden"
            )

        expected_width = scale_dimension(
            self.source_width,
            target_ppi=self.output_effective_ppi,
            source_ppi=self.source_effective_ppi,
        )
        expected_height = scale_dimension(
            self.source_height,
            target_ppi=self.output_effective_ppi,
            source_ppi=self.source_effective_ppi,
        )
        if (self.output_width, self.output_height) != (expected_width, expected_height):
            raise ValueError(
                f"{self.image_id}: {self.source_width}x{self.source_height} at "
                f"{self.source_effective_ppi} ppi scales to "
                f"{expected_width}x{expected_height} at {self.output_effective_ppi} "
                f"ppi, not {self.output_width}x{self.output_height}"
            )

        if self.source_effective_ppi == self.output_effective_ppi:
            if self.transform_action != TRANSFORM_ACTION_IDENTITY:
                raise ValueError(
                    f"{self.image_id}: a source already at "
                    f"{self.output_effective_ppi} ppi is not resampled; the action "
                    f"must be {TRANSFORM_ACTION_IDENTITY!r}, got "
                    f"{self.transform_action!r}"
                )
            if self.source_pixel_sha256 != self.output_pixel_sha256:
                raise ValueError(
                    f"{self.image_id}: the identity path must preserve the raster "
                    "exactly, but the source and output pixel hashes differ"
                )
        else:
            if not self.transform_action.startswith(
                TRANSFORM_ACTION_DOWNSAMPLE_PREFIX
            ):
                raise ValueError(
                    f"{self.image_id}: reducing "
                    f"{self.source_effective_ppi} to {self.output_effective_ppi} ppi "
                    f"is a {TRANSFORM_ACTION_DOWNSAMPLE_PREFIX} action, got "
                    f"{self.transform_action!r}"
                )

        expected_hash = prepared_image_entry_hash(self)
        if self.entry_hash != expected_hash:
            raise ValueError(
                f"{self.image_id}: entry_hash does not cover this entry: expected "
                f"{expected_hash}, got {self.entry_hash}"
            )

    @property
    def is_identity(self) -> bool:
        return self.transform_action == TRANSFORM_ACTION_IDENTITY

    @property
    def scale_text(self) -> str:
        return f"{self.scale_numerator}/{self.scale_denominator}"


def prepared_image_entry_hash(entry: PreparedImageEntry) -> str:
    """A digest of what this image *is*, not of where it sits in a list.

    Excludes ``ordinal`` and ``relative_path``. The ordinal describes a position
    in one particular set and belongs to the ordered-set hash; the path
    describes one machine's directory layout. Including either would mean the
    same canonical image, materialised into a second set or a second workspace,
    hashed differently — and then nothing could be reused (spec section 33).
    """
    return stable_hash(
        {
            "schema": "prepared_image_entry_hash_v1",
            "imaging_schema_version": IMAGING_SCHEMA_VERSION,
            "prepared_entry_schema_version": PREPARED_ENTRY_SCHEMA_VERSION,
            "image_id": str(entry.image_id),
            "source": {
                "record_fingerprint": entry.source_record_fingerprint,
                "expected_sha256": entry.source_expected_sha256,
                "size_bytes": entry.source_size_bytes,
                "effective_ppi": entry.source_effective_ppi,
                "declared_ppi": entry.source_declared_ppi,
                "width": entry.source_width,
                "height": entry.source_height,
                "pixel_sha256": entry.source_pixel_sha256,
            },
            "transform": {
                "profile_fingerprint": entry.transform_profile_fingerprint,
                "runtime_fingerprint": entry.transform_runtime_fingerprint,
                "action": entry.transform_action,
                "scale_numerator": entry.scale_numerator,
                "scale_denominator": entry.scale_denominator,
            },
            "output": {
                "width": entry.output_width,
                "height": entry.output_height,
                "effective_ppi": entry.output_effective_ppi,
                "pixel_sha256": entry.output_pixel_sha256,
                "encoded_sha256": entry.output_encoded_sha256,
                "size_bytes": entry.output_size_bytes,
                "media_type": entry.output_media_type,
            },
        },
        length=64,
    )


# ----------------------------------------------------------------- prepared set


@dataclass(frozen=True, slots=True)
class PreparedImageSetManifest:
    """The identity of one immutable, reusable canonical input set.

    It names the pair manifest it was derived for, even though nothing about the
    transformation depends on pairing. That is on purpose: a canonical set is
    only interchangeable with another set if both cover exactly the images the
    same experiment needs, and a set silently missing thirty images would
    otherwise look complete (spec section 35).
    """

    preparation_set_id: str
    preparation_set_fingerprint: str

    dataset_id: str
    image_manifest_hash: str

    protocol_id: str
    cohort_id: str
    cohort_fingerprint: str
    pair_manifest_hash: str

    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_id: str
    transform_runtime_fingerprint: str

    total_images: int
    ordered_entries_hash: str

    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "preparation_set_id",
            "dataset_id",
            "protocol_id",
            "cohort_id",
            "transform_profile_id",
            "transform_runtime_id",
        ):
            validate_id(getattr(self, name))
        for name in (
            "preparation_set_fingerprint",
            "image_manifest_hash",
            "cohort_fingerprint",
            "pair_manifest_hash",
            "transform_profile_fingerprint",
            "transform_runtime_fingerprint",
            "ordered_entries_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self, "total_images", _require_positive_int(self.total_images, "total_images")
        )
        object.__setattr__(
            self, "created_utc", _require_non_empty(self.created_utc, "created_utc")
        )

        expected_id = preparation_set_id(self.preparation_set_fingerprint)
        if self.preparation_set_id != expected_id:
            raise ValueError(
                f"preparation_set_id must be derived from the fingerprint: expected "
                f"{expected_id}, got {self.preparation_set_id!r}"
            )


def ordered_prepared_entries_hash(entries: Iterable[PreparedImageEntry]) -> str:
    """A digest of the entries *in materialisation order*.

    The ordinal enters here and nowhere else. Order is part of the set's
    identity because it is how a partially materialised set is described
    precisely, and because a resumed materialisation that produced the same
    images in a different order is not the same set.
    """
    return stable_hash(
        {
            "schema": "prepared_image_set_ordered_entries_v1",
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "image_id": str(entry.image_id),
                    "entry_hash": entry.entry_hash,
                }
                for entry in entries
            ],
        },
        length=64,
    )


def preparation_set_fingerprint(
    *,
    dataset_id: str,
    image_manifest_hash: str,
    protocol_id: str,
    cohort_id: str,
    cohort_fingerprint: str,
    pair_manifest_hash: str,
    transform_profile_fingerprint: str,
    transform_runtime_fingerprint: str,
    entries: Iterable[PreparedImageEntry],
) -> str:
    """The digest behind ``preparation_set_id``.

    Carries no timestamp and no output directory. The same 3,000 images
    materialised again tomorrow, into a different workspace, under the same
    profile and the same runtime, are the same set — that is the whole reason a
    prepared-image set is reusable evidence rather than a build artefact
    (docs/adr/0033).
    """
    ordered = list(entries)
    return stable_hash(
        {
            "schema": "preparation_set_fingerprint_v1",
            "imaging_schema_version": IMAGING_SCHEMA_VERSION,
            "preparation_set_schema_version": PREPARATION_SET_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "image_manifest_hash": image_manifest_hash,
            "protocol_id": protocol_id,
            "cohort_id": cohort_id,
            "cohort_fingerprint": cohort_fingerprint,
            "pair_manifest_hash": pair_manifest_hash,
            "transform_profile_fingerprint": transform_profile_fingerprint,
            "transform_runtime_fingerprint": transform_runtime_fingerprint,
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "image_id": str(entry.image_id),
                    "entry_hash": entry.entry_hash,
                }
                for entry in ordered
            ],
            "total_images": len(ordered),
        },
        length=64,
    )


def preparation_set_id(fingerprint: str) -> str:
    """``prepset_<12 chars of the preparation-set fingerprint>``."""
    digest = _require_digest(fingerprint, "preparation_set_fingerprint")
    return f"prepset_{digest[:PREPARATION_SET_ID_LENGTH]}"


# --------------------------------------------------------------------- receipt


@dataclass(frozen=True, slots=True)
class PreparationTransformAudit:
    """A full source-to-transform-to-output re-derivation pass.

    Counts are kept instead of per-image details so the artefact can be shared
    without publishing an inventory of the redistribution-restricted dataset.
    A clean audit has every count equal to ``planned_images`` and no issues.
    """

    schema_version: str
    preparation_set_id: str
    preparation_set_fingerprint: str

    planned_images: int
    verified_sources: int
    recomputed_transforms: int
    matching_output_dimensions: int
    matching_transform_actions: int
    matching_pixel_hashes: int
    matching_encoded_hashes: int

    issues: tuple[str, ...]
    audit_fingerprint: str
    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.preparation_set_id)
        object.__setattr__(
            self,
            "preparation_set_fingerprint",
            _require_digest(
                self.preparation_set_fingerprint, "preparation_set_fingerprint"
            ),
        )
        for name in ("schema_version", "created_utc"):
            object.__setattr__(self, name, _require_non_empty(getattr(self, name), name))
        if self.schema_version != PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported preparation transform audit schema {self.schema_version!r}"
            )
        for name in (
            "planned_images",
            "verified_sources",
            "recomputed_transforms",
            "matching_output_dimensions",
            "matching_transform_actions",
            "matching_pixel_hashes",
            "matching_encoded_hashes",
        ):
            object.__setattr__(
                self, name, _require_non_negative_int(getattr(self, name), name)
            )
        if self.planned_images <= 0:
            raise ValueError("planned_images must be positive")
        for name in (
            "verified_sources",
            "recomputed_transforms",
            "matching_output_dimensions",
            "matching_transform_actions",
            "matching_pixel_hashes",
            "matching_encoded_hashes",
        ):
            if getattr(self, name) > self.planned_images:
                raise ValueError(f"{name} cannot exceed planned_images")
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))
        object.__setattr__(
            self,
            "audit_fingerprint",
            _require_digest(self.audit_fingerprint, "audit_fingerprint"),
        )
        expected = preparation_transform_audit_fingerprint(self.claims())
        if self.audit_fingerprint != expected:
            raise ValueError(
                "audit_fingerprint does not cover the transform audit: expected "
                f"{expected}, got {self.audit_fingerprint}"
            )

    @property
    def is_clean(self) -> bool:
        expected = self.planned_images
        return not self.issues and all(
            getattr(self, name) == expected
            for name in (
                "verified_sources",
                "recomputed_transforms",
                "matching_output_dimensions",
                "matching_transform_actions",
                "matching_pixel_hashes",
                "matching_encoded_hashes",
            )
        )

    def claims(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "preparation_set_id": self.preparation_set_id,
            "preparation_set_fingerprint": self.preparation_set_fingerprint,
            "planned_images": self.planned_images,
            "verified_sources": self.verified_sources,
            "recomputed_transforms": self.recomputed_transforms,
            "matching_output_dimensions": self.matching_output_dimensions,
            "matching_transform_actions": self.matching_transform_actions,
            "matching_pixel_hashes": self.matching_pixel_hashes,
            "matching_encoded_hashes": self.matching_encoded_hashes,
            "issues": list(self.issues),
        }


def preparation_transform_audit_fingerprint(
    claims: Mapping[str, object],
) -> str:
    """Digest the durable claims of one full transform audit."""
    return stable_hash(
        {"schema": "preparation_transform_audit_fingerprint_v1", "claims": dict(claims)},
        length=64,
    )


def preparation_transform_audit_content_hash(
    audit: PreparationTransformAudit,
) -> str:
    """Digest the exact stored audit, including its timestamp."""
    from fpbench.core.serialization import to_plain

    return stable_hash(
        {"schema": "preparation_transform_audit_content_hash_v1", "audit": to_plain(audit)},
        length=64,
    )


@dataclass(frozen=True, slots=True)
class PreparationReceipt:
    """The one file from a preparation that is meant to leave the workspace.

    It proves a set exists, is complete and is reproducible — without publishing
    an inventory of a redistribution-restricted dataset. There is no image id,
    no subject id, no filename and no per-image hash anywhere in it, and the
    absence is checked rather than intended (spec section 49).
    """

    schema_version: str

    preparation_set_id: str
    preparation_set_fingerprint: str

    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_id: str
    transform_runtime_fingerprint: str

    dataset_id: str
    image_manifest_hash: str
    protocol_id: str
    cohort_id: str
    cohort_fingerprint: str
    pair_manifest_hash: str

    source_commit: str
    source_tree_clean: bool
    transform_audit_fingerprint: str

    total_images: int
    counts_by_release: Mapping[str, int]
    counts_by_source_ppi: Mapping[str, int]
    counts_by_transform_action: Mapping[str, int]

    total_source_bytes: int
    total_output_bytes: int

    statement: str
    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "preparation_set_id",
            "transform_profile_id",
            "transform_runtime_id",
            "dataset_id",
            "protocol_id",
            "cohort_id",
        ):
            validate_id(getattr(self, name))
        for name in (
            "preparation_set_fingerprint",
            "transform_profile_fingerprint",
            "transform_runtime_fingerprint",
            "image_manifest_hash",
            "cohort_fingerprint",
            "pair_manifest_hash",
            "transform_audit_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("schema_version", "source_commit", "statement", "created_utc"):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        if self.schema_version != PREPARATION_RECEIPT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported preparation receipt schema {self.schema_version!r}"
            )
        object.__setattr__(
            self, "total_images", _require_positive_int(self.total_images, "total_images")
        )
        for name in ("total_source_bytes", "total_output_bytes"):
            object.__setattr__(
                self, name, _require_positive_int(getattr(self, name), name)
            )
        if type(self.source_tree_clean) is not bool:
            raise ValueError("source_tree_clean must be a bool")
        for name in (
            "counts_by_release",
            "counts_by_source_ppi",
            "counts_by_transform_action",
        ):
            mapping = dict(getattr(self, name))
            frozen = {
                str(key): _require_non_negative_int(value, f"{name}[{key}]")
                for key, value in sorted(mapping.items())
            }
            object.__setattr__(self, name, MappingProxyType(frozen))

        if sum(self.counts_by_release.values()) != self.total_images:
            raise ValueError(
                "the per-release counts do not add up to the total image count"
            )
        if sum(self.counts_by_source_ppi.values()) != self.total_images:
            raise ValueError(
                "the per-resolution counts do not add up to the total image count"
            )
        if sum(self.counts_by_transform_action.values()) != self.total_images:
            raise ValueError(
                "the per-action counts do not add up to the total image count"
            )


def preparation_receipt_fingerprint(receipt: PreparationReceipt) -> str:
    """A digest of the receipt's claims, with ``created_utc`` excluded.

    Two finalisations of the same verified set produce the same fingerprint, so
    re-finalising is a no-op rather than a conflict.
    """
    from fpbench.core.serialization import to_plain

    payload = dict(to_plain(receipt))
    payload.pop("created_utc", None)
    return stable_hash(
        {"schema": "preparation_receipt_fingerprint_v1", "receipt": payload},
        length=64,
    )


def preparation_receipt_content_hash(receipt: PreparationReceipt) -> str:
    """A digest of the exact receipt, ``created_utc`` included.

    This is what the finalization marker binds: the bytes actually written, not
    a semantically equivalent rendering of them.
    """
    from fpbench.core.serialization import to_plain

    return stable_hash(
        {"schema": "preparation_receipt_content_hash_v1", "receipt": to_plain(receipt)},
        length=64,
    )


# ---------------------------------------------------------------------- marker


@dataclass(frozen=True, slots=True)
class PreparationFinalizationMarker:
    """The last file written, and the only one that makes the rest authoritative.

    Everything before it is idempotent and retryable. A crash between the
    entries table and the receipt leaves a visibly unfinished directory that a
    second attempt completes; a marker, once written, must keep naming exactly
    the chain it was issued over (docs/adr/0020, applied to preparation).
    """

    schema_version: str

    finalization_id: str
    finalization_fingerprint: str

    preparation_set_id: str
    preparation_set_fingerprint: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str

    entries_table_content_hash: str
    summary_content_hash: str

    receipt_fingerprint: str
    receipt_content_hash: str

    transform_audit_fingerprint: str
    transform_audit_content_hash: str

    source_commit: str
    source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.finalization_id)
        validate_id(self.preparation_set_id)
        for name in (
            "finalization_fingerprint",
            "preparation_set_fingerprint",
            "transform_profile_fingerprint",
            "transform_runtime_fingerprint",
            "entries_table_content_hash",
            "summary_content_hash",
            "receipt_fingerprint",
            "receipt_content_hash",
            "transform_audit_fingerprint",
            "transform_audit_content_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("schema_version", "source_commit", "created_utc"):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        if self.schema_version != PREPARATION_FINALIZATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported preparation finalization schema {self.schema_version!r}"
            )
        if type(self.source_tree_clean) is not bool:
            raise ValueError("source_tree_clean must be a bool")

        expected = preparation_finalization_fingerprint(self.claims())
        if self.finalization_fingerprint != expected:
            raise ValueError(
                "finalization_fingerprint does not cover these claims: expected "
                f"{expected}, got {self.finalization_fingerprint}"
            )
        if self.finalization_id != f"prepfinal_{expected[:PREPARATION_SET_ID_LENGTH]}":
            raise ValueError(
                "finalization_id must be derived from the finalization fingerprint"
            )

    def claims(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "preparation_set_id": self.preparation_set_id,
            "preparation_set_fingerprint": self.preparation_set_fingerprint,
            "transform_profile_fingerprint": self.transform_profile_fingerprint,
            "transform_runtime_fingerprint": self.transform_runtime_fingerprint,
            "entries_table_content_hash": self.entries_table_content_hash,
            "summary_content_hash": self.summary_content_hash,
            "receipt_fingerprint": self.receipt_fingerprint,
            "receipt_content_hash": self.receipt_content_hash,
            "transform_audit_fingerprint": self.transform_audit_fingerprint,
            "transform_audit_content_hash": self.transform_audit_content_hash,
            "source_commit": self.source_commit,
            "source_tree_clean": self.source_tree_clean,
        }


def preparation_finalization_fingerprint(claims: Mapping[str, object]) -> str:
    """A digest of exactly the claims a marker makes. No timestamp."""
    return stable_hash(
        {
            "schema": "preparation_finalization_fingerprint_v1",
            "claims": dict(claims),
        },
        length=64,
    )
