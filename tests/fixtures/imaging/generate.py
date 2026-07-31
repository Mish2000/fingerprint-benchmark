"""Regenerate the golden imaging fixtures and their expected values.

    python tests/fixtures/imaging/generate.py

Run this only when the transform profile or the pinned resampler deliberately
changes — and when it does, review the diff to ``expected.json`` line by line. A
golden hash that moved without anybody intending it to move is the single most
useful signal this project has that the canonical pixels are not what they were.

Nothing here is a fingerprint. The fixtures are checkerboards, gradients,
impulses and ridge-shaped stripes: small, synthetic, and safe to commit into a
repository that deliberately holds no imagery (see ``.gitignore``).

Each fixture names the resolution it is to be read *as*. That is the whole
point of docs/adr/0032: a 41x27 image is 41x27 pixels whatever its header says,
and whether it becomes 41x27, 21x14 or 10x7 depends entirely on the effective
ppi the manifest assigns it.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.core.imaging_models import canonical_pixel_hash  # noqa: E402
from fpbench.imaging.canonical import (  # noqa: E402
    canonicalise,
    encode_canonical_png,
    read_source_raster,
)
from fpbench.imaging.png_chunks import parse_png_chunks  # noqa: E402
from fpbench.imaging.runtime import (  # noqa: E402
    pillow_distribution_fingerprint,
    pillow_zlib_version,
)
from fpbench.imaging.transform_profile import load_transform_profile  # noqa: E402

FIXTURE_DIRECTORY = Path(__file__).resolve().parent
EXPECTED = FIXTURE_DIRECTORY / "expected.json"


def _checkerboard(width: int, height: int) -> bytes:
    """Alternating single pixels: the highest spatial frequency an image can hold.

    The case a bad downsampler mangles most visibly, and the case where the
    difference between one Lanczos pass and two chained ones is largest.
    """
    return bytes(
        0 if (x + y) % 2 == 0 else 255 for y in range(height) for x in range(width)
    )


def _horizontal_ridges(width: int, height: int, period: int = 8) -> bytes:
    return bytes(
        0 if (y % period) < period // 2 else 255
        for y in range(height)
        for _ in range(width)
    )


def _vertical_ridges(width: int, height: int, period: int = 8) -> bytes:
    row = bytes(0 if (x % period) < period // 2 else 255 for x in range(width))
    return row * height


def _impulse(width: int, height: int) -> bytes:
    data = bytearray(b"\x00" * (width * height))
    data[(height // 2) * width + (width // 2)] = 255
    return bytes(data)


def _constant(width: int, height: int, value: int) -> bytes:
    return bytes([value]) * (width * height)


def _gradient(width: int, height: int) -> bytes:
    return bytes(
        (x * 255) // max(width - 1, 1) for _ in range(height) for x in range(width)
    )


def _mixed(width: int, height: int) -> bytes:
    return bytes((x * 29 + y * 11) % 256 for y in range(height) for x in range(width))


#: ``name -> (width, height, source ppi, raster builder)``.
#:
#: The three geometry cases the profile has to get right are first: an even
#: dimension at the target resolution (no resize at all), an odd dimension at
#: 1000 (a .5 that must round *up*, where Python's round() would round down),
#: and a dimension at 2000 whose quarter leaves a remainder.
FIXTURES: dict[str, tuple[int, int, int, object]] = {
    "gray8_even_500ppi": (64, 48, 500, _mixed),
    "gray8_odd_1000ppi": (41, 27, 1000, _mixed),
    "gray8_quarter_remainder_2000ppi": (1006, 1002, 2000, _mixed),
    "checkerboard_2000ppi": (64, 64, 2000, _checkerboard),
    "horizontal_ridges_1000ppi": (64, 64, 1000, _horizontal_ridges),
    "vertical_ridges_1000ppi": (64, 64, 1000, _vertical_ridges),
    "impulse_2000ppi": (65, 65, 2000, _impulse),
    "constant_black_1000ppi": (32, 32, 1000, lambda w, h: _constant(w, h, 0)),
    "constant_white_1000ppi": (32, 32, 1000, lambda w, h: _constant(w, h, 255)),
    "gradient_1000ppi": (64, 32, 1000, _gradient),
}


def build(*, fixture_directory: Path = FIXTURE_DIRECTORY) -> dict[str, object]:
    profile = load_transform_profile()
    pillow_version, distribution_fingerprint, _ = pillow_distribution_fingerprint()

    records: dict[str, object] = {}
    for name, (width, height, source_ppi, builder) in FIXTURES.items():
        raster = builder(width, height)
        # The source is written through the canonical encoder too, so that a
        # fixture is a valid single-frame gray8 PNG by construction rather than
        # by hope. Its declared pHYs is the profile's 500 regardless of the
        # resolution it is read at, which is exactly the situation docs/adr/0032
        # exists for: the header is not consulted.
        source_bytes = encode_canonical_png(
            width=width, height=height, raster=raster, profile=profile
        )
        path = fixture_directory / f"{name}.png"
        path.write_bytes(source_bytes)

        source = read_source_raster(path, profile=profile, image_label=name)
        artifact = canonicalise(
            source, profile=profile, source_ppi=source_ppi, image_label=name
        )
        inventory = parse_png_chunks(artifact.encoded_bytes)

        records[name] = {
            "source": {
                "width": width,
                "height": height,
                "effective_ppi": source_ppi,
                "pixel_sha256": canonical_pixel_hash(
                    width=width, height=height, raster=raster
                ),
                "encoded_sha256": source.encoded_sha256,
                "size_bytes": source.size_bytes,
            },
            "output": {
                "width": artifact.width,
                "height": artifact.height,
                "effective_ppi": profile.target_ppi,
                "transform_action": artifact.transform_action,
                "scale": f"{artifact.scale_numerator}/{artifact.scale_denominator}",
                "pixel_sha256": artifact.pixel_sha256,
                "encoded_sha256": artifact.encoded_sha256,
                "size_bytes": artifact.size_bytes,
                "chunk_types": list(inventory.chunk_types),
                "phys": {
                    "x": inventory.phys.pixels_per_unit_x,
                    "y": inventory.phys.pixels_per_unit_y,
                    "unit": inventory.phys.unit_specifier,
                },
                "extent_error_ppm": {
                    "x": artifact.extent_error_ppm_x,
                    "y": artifact.extent_error_ppm_y,
                },
            },
        }

    return {
        "schema": "imaging_golden_fixtures_v1",
        "generated_under": {
            "transform_profile_id": profile.profile_id,
            "transform_profile_fingerprint": profile.profile_fingerprint,
            "pillow_version": pillow_version,
            "pillow_distribution_fingerprint": distribution_fingerprint,
            "zlib_runtime_version": pillow_zlib_version(),
        },
        "fixtures": records,
    }


def _normalise_for_check(
    payload: dict[str, object], *, compare_encoded_bytes: bool
) -> dict[str, object]:
    """Remove only provenance terms that necessarily differ across platforms."""

    normalised = copy.deepcopy(payload)
    generated_under = normalised["generated_under"]
    assert isinstance(generated_under, dict)
    generated_under.pop("pillow_distribution_fingerprint")
    if not compare_encoded_bytes:
        generated_under.pop("zlib_runtime_version")
        fixtures = normalised["fixtures"]
        assert isinstance(fixtures, dict)
        for fixture in fixtures.values():
            assert isinstance(fixture, dict)
            for side_name in ("source", "output"):
                side = fixture[side_name]
                assert isinstance(side, dict)
                side.pop("encoded_sha256")
                side.pop("size_bytes")
    return normalised


def check() -> int:
    committed = json.loads(EXPECTED.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="fpbench-imaging-fixtures-") as directory:
        generated = build(fixture_directory=Path(directory))

    committed_runtime = committed["generated_under"]
    generated_runtime = generated["generated_under"]
    compare_encoded_bytes = (
        committed_runtime["zlib_runtime_version"]
        == generated_runtime["zlib_runtime_version"]
    )
    expected = _normalise_for_check(
        committed, compare_encoded_bytes=compare_encoded_bytes
    )
    actual = _normalise_for_check(
        generated, compare_encoded_bytes=compare_encoded_bytes
    )
    if actual != expected:
        expected_lines = json.dumps(expected, indent=2, ensure_ascii=False).splitlines(
            keepends=True
        )
        actual_lines = json.dumps(actual, indent=2, ensure_ascii=False).splitlines(
            keepends=True
        )
        sys.stdout.writelines(
            difflib.unified_diff(
                expected_lines,
                actual_lines,
                fromfile="committed expected.json",
                tofile="generated expected.json",
            )
        )
        return 1

    encoded_note = "including encoded bytes" if compare_encoded_bytes else "pixels only"
    print(f"verified {len(actual['fixtures'])} fixtures ({encoded_note})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against committed golden values without rewriting fixtures",
    )
    arguments = parser.parse_args(argv)
    if arguments.check:
        return check()

    payload = build()
    EXPECTED.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(payload['fixtures'])} fixtures and {EXPECTED.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
