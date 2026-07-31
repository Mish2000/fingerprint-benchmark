"""Turning ``configs/imaging/*.yaml`` into an immutable transform profile.

The parser is deliberately unforgiving in one specific way: it has no defaults.
Every field of :class:`~fpbench.core.imaging_models.ImageTransformProfile` must
be present in the file, including the eleven operations the profile forbids.

That is not pedantry. A default is a decision made by whoever wrote the parser,
applied to an experiment they will never see, and recorded nowhere. If a profile
omits ``sharpen: true`` and the parser fills it in, then the *file* no longer
says what the transformation was, and two profiles that look different in git
can fingerprint the same. Absent means rejected (docs/adr/0031).

The one field allowed to be absent-shaped is ``reducing_gap``, whose value is
genuinely ``null``: Pillow's multi-step reduction shortcut is disabled, and
``null`` is how that is written down.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.errors import TransformProfileError
from fpbench.core.imaging_models import (
    FORBIDDEN_OPERATIONS,
    ImageTransformProfile,
    image_transform_profile_fingerprint,
)
from fpbench.core.serialization import require_exact_int

__all__ = [
    "load_transform_profile",
    "parse_transform_profile",
    "build_transform_profile",
    "CANONICAL_500_PROFILE_ID",
    "DEFAULT_PROFILE_PATH",
    "PIXELS_PER_METRE_AT_500_PPI",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

CANONICAL_500_PROFILE_ID = "canonical_gray8_500ppi_lanczos3_v1"

DEFAULT_PROFILE_PATH = (
    REPOSITORY_ROOT / "configs" / "imaging" / f"{CANONICAL_500_PROFILE_ID}.yaml"
)

#: ``int(500 / 0.0254 + 0.5)``. Written out because it is the number that ends
#: up in the file, and a reader should not have to redo the arithmetic to check
#: that a canonical PNG really claims 500 ppi.
PIXELS_PER_METRE_AT_500_PPI = 19685

_ALLOWED_ROUNDING = frozenset({"nearest_half_up"})


def load_transform_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> ImageTransformProfile:
    """Read and validate one profile file."""
    path = Path(path)
    if not path.is_file():
        raise TransformProfileError(f"transform profile not found: {path}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise TransformProfileError(f"{path}: unreadable YAML ({exc})") from exc
    if not isinstance(document, Mapping):
        raise TransformProfileError(f"{path}: expected a mapping at the top level")
    try:
        return parse_transform_profile(document)
    except TransformProfileError as exc:
        raise TransformProfileError(f"{path}: {exc}") from None


def parse_transform_profile(document: Mapping[str, Any]) -> ImageTransformProfile:
    """Build a profile from an already-parsed document."""
    profile = _section(document, "profile")
    source = _section(document, "input")
    resolution = _section(document, "resolution")
    pixel_transform = _section(document, "pixel_transform")
    forbidden = _section(document, "forbidden_operations")
    output = _section(document, "output")

    if _optional_bool(resolution, "upsampling_forbidden", default=True) is False:
        raise TransformProfileError(
            "resolution.upsampling must stay forbidden; a canonical set may not "
            "invent ridge detail that was never captured"
        )

    return build_transform_profile(
        profile_id=_text(profile, "profile_id"),
        profile_version=_text(profile, "profile_version"),
        input_media_type=_text(source, "media_type"),
        input_colour_model=_text(source, "colour_model"),
        input_bit_depth=_integer(source, "bit_depth"),
        input_frame_count=_integer(source, "frame_count"),
        input_alpha=_text(source, "alpha"),
        input_palette=_text(source, "palette"),
        source_ppi_field=_text(resolution, "source_ppi_field"),
        target_ppi=_integer(resolution, "target_ppi"),
        upsampling=_text(resolution, "upsampling"),
        dimension_rounding=_text(resolution, "dimension_rounding"),
        preserve_physical_extent=_boolean(resolution, "preserve_physical_extent"),
        identity_when_equal=_boolean(
            pixel_transform, "identity_when_source_ppi_equals_target"
        ),
        resize_when_above=_boolean(
            pixel_transform, "resize_when_source_ppi_above_target"
        ),
        resize_path=_text(pixel_transform, "resize_path"),
        resampler_engine=_text(pixel_transform, "resampler_engine"),
        resampler_filter=_text(pixel_transform, "resampler_filter"),
        resampler_radius=_integer(pixel_transform, "lanczos_radius"),
        reducing_gap=_nullable_text(pixel_transform, "reducing_gap"),
        forbidden_operations={
            str(key): _require_bool(value, f"forbidden_operations.{key}")
            for key, value in dict(forbidden).items()
        },
        output_media_type=_text(output, "media_type"),
        output_colour_model=_text(output, "colour_type"),
        output_bit_depth=_integer(output, "bit_depth"),
        output_interlaced=_boolean(output, "interlace"),
        output_compression_level=_integer(output, "compression_level"),
        output_optimize=_boolean(output, "optimize"),
        output_ppi=_integer(output, "ppi"),
        output_pixels_per_meter_x=_integer(output, "png_pixels_per_meter_x"),
        output_pixels_per_meter_y=_integer(output, "png_pixels_per_meter_y"),
        strip_text_chunks=_boolean(output, "strip_text_chunks"),
        strip_colour_management_chunks=_boolean(
            output, "strip_colour_management_chunks"
        ),
        timestamps=_text(output, "timestamps"),
    )


def build_transform_profile(
    *,
    profile_id: str,
    profile_version: str,
    input_media_type: str,
    input_colour_model: str,
    input_bit_depth: int,
    input_frame_count: int,
    input_alpha: str,
    input_palette: str,
    source_ppi_field: str,
    target_ppi: int,
    upsampling: str,
    dimension_rounding: str,
    preserve_physical_extent: bool,
    identity_when_equal: bool,
    resize_when_above: bool,
    resize_path: str,
    resampler_engine: str,
    resampler_filter: str,
    resampler_radius: int,
    reducing_gap: str | None,
    forbidden_operations: Mapping[str, bool],
    output_media_type: str,
    output_colour_model: str,
    output_bit_depth: int,
    output_interlaced: bool,
    output_compression_level: int,
    output_optimize: bool,
    output_ppi: int,
    output_pixels_per_meter_x: int,
    output_pixels_per_meter_y: int,
    strip_text_chunks: bool,
    strip_colour_management_chunks: bool,
    timestamps: str,
) -> ImageTransformProfile:
    """Check the semantic rules, then mint the profile and its fingerprint.

    Everything checked here is a rule about the *transformation*, not about the
    file it was written in. Several of them cannot be expressed in the dataclass
    because they involve fields the dataclass does not keep — ``alpha:
    forbidden`` is a contract on the input, not a property of the profile — and
    they must still be refused rather than dropped.
    """
    _require_choice(input_media_type, {"image/png"}, "input.media_type")
    _require_choice(input_colour_model, {"grayscale"}, "input.colour_model")
    _require_choice(input_alpha, {"forbidden"}, "input.alpha")
    _require_choice(input_palette, {"forbidden"}, "input.palette")
    if input_bit_depth != 8:
        raise TransformProfileError(
            f"input.bit_depth is {input_bit_depth}; a 16-bit source is not silently "
            "narrowed to 8, it needs a profile that says what happens to it"
        )
    if input_frame_count != 1:
        raise TransformProfileError("input.frame_count must be 1")

    _require_choice(upsampling, {"forbidden"}, "resolution.upsampling")
    if dimension_rounding not in _ALLOWED_ROUNDING:
        raise TransformProfileError(
            f"resolution.dimension_rounding is {dimension_rounding!r}; only "
            f"{sorted(_ALLOWED_ROUNDING)} is defined, because Python's round() "
            "breaks ties to even and would give two rules one name"
        )
    if not preserve_physical_extent:
        raise TransformProfileError(
            "resolution.preserve_physical_extent must be true; a resampling that "
            "changed the printed size of a finger would change the biometrics"
        )
    if not identity_when_equal:
        raise TransformProfileError(
            "pixel_transform.identity_when_source_ppi_equals_target must be true; a "
            "source already at the target is not resampled"
        )
    if not resize_when_above:
        raise TransformProfileError(
            "pixel_transform.resize_when_source_ppi_above_target must be true"
        )
    _require_choice(
        resize_path, {"direct_source_to_target"}, "pixel_transform.resize_path"
    )
    _require_choice(resampler_engine, {"pillow"}, "pixel_transform.resampler_engine")
    _require_choice(resampler_filter, {"lanczos"}, "pixel_transform.resampler_filter")
    if resampler_radius != 3:
        raise TransformProfileError(
            f"pixel_transform.lanczos_radius is {resampler_radius}; Pillow's LANCZOS "
            "is a 3-lobe kernel and the profile must say so rather than imply it"
        )
    if reducing_gap is not None:
        raise TransformProfileError(
            "pixel_transform.reducing_gap must be null; Pillow's reducing_gap "
            "silently inserts a box pre-reduction, which is a second resampling "
            "the profile did not ask for"
        )

    missing = [name for name in FORBIDDEN_OPERATIONS if name not in forbidden_operations]
    if missing:
        raise TransformProfileError(
            "forbidden_operations does not mention " + ", ".join(sorted(missing))
            + "; an operation nobody forbade is an operation an implementation is "
            "free to perform"
        )
    permitted = sorted(
        name for name, value in forbidden_operations.items() if not value
    )
    if permitted:
        raise TransformProfileError(
            "forbidden_operations permits " + ", ".join(permitted)
            + "; a canonical profile changes resolution and nothing else"
        )

    _require_choice(output_media_type, {"image/png"}, "output.media_type")
    _require_choice(output_colour_model, {"grayscale"}, "output.colour_type")
    if output_bit_depth != 8:
        raise TransformProfileError("output.bit_depth must be 8")
    if output_interlaced:
        raise TransformProfileError("output.interlace must be false")
    if output_optimize:
        raise TransformProfileError(
            "output.optimize must be false; Pillow's optimiser searches filter "
            "strategies and its choice is not pinned by anything in this profile"
        )
    if not 0 <= output_compression_level <= 9:
        raise TransformProfileError("output.compression_level must be between 0 and 9")
    if output_ppi != target_ppi:
        raise TransformProfileError(
            f"output.ppi is {output_ppi} but resolution.target_ppi is {target_ppi}; "
            "a file that declared a resolution it was not resampled to would be "
            "worse than one that declared none"
        )
    expected_ppm = int(target_ppi / 0.0254 + 0.5)
    for axis, value in (
        ("x", output_pixels_per_meter_x),
        ("y", output_pixels_per_meter_y),
    ):
        if value != expected_ppm:
            raise TransformProfileError(
                f"output.png_pixels_per_meter_{axis} is {value}; {target_ppi} ppi is "
                f"{expected_ppm} pixels per metre"
            )
    if not strip_text_chunks:
        raise TransformProfileError(
            "output.strip_text_chunks must be true; a text chunk is where a "
            "filename, a subject id or a timestamp leaks into a shareable artefact"
        )
    if not strip_colour_management_chunks:
        raise TransformProfileError(
            "output.strip_colour_management_chunks must be true"
        )
    _require_choice(timestamps, {"forbidden"}, "output.timestamps")

    draft = dict(
        profile_id=profile_id,
        profile_version=profile_version,
        input_media_type=input_media_type,
        input_colour_model=input_colour_model,
        input_bit_depth=input_bit_depth,
        input_frame_count=input_frame_count,
        target_ppi=target_ppi,
        source_ppi_field=source_ppi_field,
        allow_upsampling=False,
        dimension_rounding=dimension_rounding,
        resampler_engine=resampler_engine,
        resampler_filter=resampler_filter,
        resampler_radius=resampler_radius,
        reducing_gap=reducing_gap,
        direct_source_to_target=True,
        output_media_type=output_media_type,
        output_colour_model=output_colour_model,
        output_bit_depth=output_bit_depth,
        output_interlaced=output_interlaced,
        output_compression_level=output_compression_level,
        output_optimize=output_optimize,
        output_pixels_per_meter_x=output_pixels_per_meter_x,
        output_pixels_per_meter_y=output_pixels_per_meter_y,
        forbidden_operations=dict(forbidden_operations),
        metadata={
            "input_alpha": input_alpha,
            "input_palette": input_palette,
            "output_ppi": str(output_ppi),
            "preserve_physical_extent": "true",
            "resize_path": resize_path,
            "strip_colour_management_chunks": "true",
            "strip_text_chunks": "true",
            "timestamps": timestamps,
        },
    )

    # The fingerprint rule lives in exactly one place — the model re-derives it
    # and refuses anything that disagrees — so it is fed a stand-in here rather
    # than being copied.
    fingerprint = image_transform_profile_fingerprint(
        _Draft(**draft)  # type: ignore[arg-type]
    )
    try:
        return ImageTransformProfile(profile_fingerprint=fingerprint, **draft)
    except ValueError as exc:
        raise TransformProfileError(str(exc)) from exc


class _Draft:
    """A profile-shaped object used only to compute the fingerprint.

    :class:`ImageTransformProfile` validates its own fingerprint in
    ``__post_init__``, so it cannot be constructed before the fingerprint
    exists. Rather than duplicate the fingerprint rule here — which is exactly
    the kind of second copy that drifts — the rule is fed a lightweight stand-in
    carrying the same attributes.
    """

    __slots__ = (
        "profile_id",
        "profile_version",
        "input_media_type",
        "input_colour_model",
        "input_bit_depth",
        "input_frame_count",
        "target_ppi",
        "source_ppi_field",
        "allow_upsampling",
        "dimension_rounding",
        "resampler_engine",
        "resampler_filter",
        "resampler_radius",
        "reducing_gap",
        "direct_source_to_target",
        "output_media_type",
        "output_colour_model",
        "output_bit_depth",
        "output_interlaced",
        "output_compression_level",
        "output_optimize",
        "output_pixels_per_meter_x",
        "output_pixels_per_meter_y",
        "forbidden_operations",
        "metadata",
    )

    def __init__(self, **fields: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


# ----------------------------------------------------------------- internals


def _section(document: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise TransformProfileError(f"missing or malformed '{key}' section")
    return value


def _text(section: Mapping[str, Any], key: str) -> str:
    if key not in section:
        raise TransformProfileError(f"missing {key!r}")
    value = section[key]
    if not isinstance(value, str) or not value.strip():
        raise TransformProfileError(f"{key} must be a non-empty string, got {value!r}")
    return value.strip()


def _nullable_text(section: Mapping[str, Any], key: str) -> str | None:
    if key not in section:
        raise TransformProfileError(f"missing {key!r}")
    value = section[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TransformProfileError(f"{key} must be a string or null, got {value!r}")
    return value.strip()


def _integer(section: Mapping[str, Any], key: str) -> int:
    if key not in section:
        raise TransformProfileError(f"missing {key!r}")
    try:
        return require_exact_int(section[key], key)
    except ValueError as exc:
        raise TransformProfileError(str(exc)) from None


def _boolean(section: Mapping[str, Any], key: str) -> bool:
    if key not in section:
        raise TransformProfileError(f"missing {key!r}")
    return _require_bool(section[key], key)


def _optional_bool(section: Mapping[str, Any], key: str, *, default: bool) -> bool:
    if key not in section:
        return default
    return _require_bool(section[key], key)


def _require_bool(value: Any, key: str) -> bool:
    if type(value) is not bool:
        raise TransformProfileError(
            f"{key} must be true or false, got {type(value).__name__}"
        )
    return value


def _require_choice(value: str, allowed: set[str], key: str) -> str:
    if value not in allowed:
        raise TransformProfileError(
            f"{key} is {value!r}; this profile family defines only "
            f"{sorted(allowed)}. A different value is a different profile and "
            "needs its own id and its own ADR"
        )
    return value
