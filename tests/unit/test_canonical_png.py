"""What a canonical PNG is allowed to contain, and what it must declare.

Two separate obligations, and the second is the one that leaks.

The image has to be an 8-bit grayscale, non-interlaced PNG declaring 500 ppi,
because that is what every algorithm evaluated under this profile is entitled to
assume.

And it has to contain *nothing else*. No creation time, no software name, no
source filename, no image id, no ICC profile. A text chunk is exactly where a
list of subject ids leaks out of a workspace and into an artefact somebody
shares, and "we did not add one" is a weaker guarantee than "the file is
rejected if one is there".
"""

from __future__ import annotations

import pytest

from fpbench.core.errors import ImagingError
from fpbench.imaging.canonical import (
    canonicalise,
    encode_canonical_png,
    read_source_raster,
    verify_canonical_png,
)
from fpbench.imaging.png_chunks import (
    CANONICAL_ALLOWED_CHUNKS,
    parse_png_chunks,
)
from fpbench.imaging.transform_profile import (
    PIXELS_PER_METRE_AT_500_PPI,
    load_transform_profile,
)

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


@pytest.fixture(scope="module")
def profile():
    return load_transform_profile()


@pytest.fixture()
def encoded(profile):
    raster = bytes((x * 17 + 3) % 256 for x in range(40 * 24))
    return encode_canonical_png(width=40, height=24, raster=raster, profile=profile)


def test_the_output_is_eight_bit_grayscale_and_not_interlaced(encoded):
    header = parse_png_chunks(encoded).header
    assert header.colour_type == 0
    assert header.bit_depth == 8
    assert not header.is_interlaced
    assert (header.width, header.height) == (40, 24)


def test_the_output_declares_500_ppi_in_pixels_per_metre(encoded):
    phys = parse_png_chunks(encoded).phys
    assert phys is not None
    assert phys.pixels_per_unit_x == PIXELS_PER_METRE_AT_500_PPI == 19685
    assert phys.pixels_per_unit_y == PIXELS_PER_METRE_AT_500_PPI
    assert phys.unit_specifier == 1  # metre, not "aspect ratio only"


def test_the_output_carries_nothing_but_the_four_permitted_chunks(encoded):
    inventory = parse_png_chunks(encoded)
    assert set(inventory.chunk_types) <= CANONICAL_ALLOWED_CHUNKS
    assert inventory.canonical_violations() == ()

    counts = inventory.counts()
    assert counts["IHDR"] == 1
    assert counts["pHYs"] == 1
    assert counts["IEND"] == 1
    assert counts.get("IDAT", 0) >= 1


@pytest.mark.parametrize(
    "forbidden", ["tEXt", "zTXt", "iTXt", "tIME", "gAMA", "sRGB", "iCCP", "eXIf"]
)
def test_no_metadata_chunk_of_any_kind_is_written(encoded, forbidden):
    assert forbidden.encode("ascii") not in encoded


def test_the_same_input_encodes_to_byte_identical_output(profile):
    """Determinism, which is what makes ``encoded_sha256`` worth storing.

    ``optimize`` is off precisely for this: Pillow's optimiser searches filter
    strategies and its choice is not pinned by anything in the profile.
    """
    raster = bytes((x * 7) % 256 for x in range(64 * 64))
    first = encode_canonical_png(width=64, height=64, raster=raster, profile=profile)
    second = encode_canonical_png(width=64, height=64, raster=raster, profile=profile)
    assert first == second


def test_one_changed_pixel_changes_both_identities(profile):
    raster = bytearray((x * 7) % 256 for x in range(32 * 32))
    before = encode_canonical_png(
        width=32, height=32, raster=bytes(raster), profile=profile
    )
    raster[17] = (raster[17] + 1) % 256
    after = encode_canonical_png(
        width=32, height=32, raster=bytes(raster), profile=profile
    )
    assert before != after


def test_changing_only_the_compression_moves_the_file_but_not_the_raster(profile):
    """The whole reason two digests are kept (docs/adr/0034).

    Re-encoding the same pixels at a different compression level must look like
    a different *file* and the same *image*, and a store that kept one digest
    would have to answer only one of those questions.
    """
    import io

    from PIL import Image

    from fpbench.core.imaging_models import canonical_pixel_hash

    raster = bytes((x * 11) % 256 for x in range(48 * 32))
    tight = encode_canonical_png(
        width=48, height=32, raster=raster, profile=profile
    )

    buffer = io.BytesIO()
    with Image.frombytes("L", (48, 32), raster) as image:
        image.save(buffer, format="PNG", optimize=False, compress_level=1,
                   dpi=(500, 500))
    loose = buffer.getvalue()

    assert tight != loose
    with Image.open(io.BytesIO(loose)) as decoded:
        decoded.load()
        assert canonical_pixel_hash(
            width=48, height=32, raster=decoded.tobytes()
        ) == canonical_pixel_hash(width=48, height=32, raster=raster)


def test_a_written_file_is_read_back_and_re_hashed(tmp_path, profile):
    """``Image.save()`` returning is not evidence that the file decodes right."""
    raster = bytes((x * 3) % 256 for x in range(20 * 12))
    encoded = encode_canonical_png(
        width=20, height=12, raster=raster, profile=profile
    )
    path = tmp_path / "out.png"
    path.write_bytes(encoded)

    from fpbench.core.imaging_models import canonical_pixel_hash

    report = verify_canonical_png(
        path,
        profile=profile,
        expected_width=20,
        expected_height=12,
        expected_pixel_sha256=canonical_pixel_hash(
            width=20, height=12, raster=raster
        ),
        expected_encoded_sha256=__import__("hashlib").sha256(encoded).hexdigest(),
        expected_size_bytes=len(encoded),
        image_label="out",
    )
    assert report["width"] == 20
    assert report["chunk_counts"]["pHYs"] == 1


def test_verification_notices_a_single_flipped_byte(tmp_path, profile):
    raster = bytes((x * 3) % 256 for x in range(20 * 12))
    encoded = encode_canonical_png(
        width=20, height=12, raster=raster, profile=profile
    )
    from fpbench.core.imaging_models import canonical_pixel_hash

    expected_pixels = canonical_pixel_hash(width=20, height=12, raster=raster)

    path = tmp_path / "corrupt.png"
    corrupted = bytearray(encoded)
    corrupted[-6] ^= 0xFF  # inside IEND's CRC region
    path.write_bytes(bytes(corrupted))

    with pytest.raises(ImagingError):
        verify_canonical_png(
            path,
            profile=profile,
            expected_width=20,
            expected_height=12,
            expected_pixel_sha256=expected_pixels,
            image_label="corrupt",
        )


def test_verification_rejects_a_file_carrying_a_text_chunk(tmp_path, profile):
    import struct
    import zlib

    raster = bytes((x * 3) % 256 for x in range(16 * 16))
    encoded = encode_canonical_png(
        width=16, height=16, raster=raster, profile=profile
    )
    body = b"Software\x00fpbench"
    chunk = (
        struct.pack(">I", len(body))
        + b"tEXt"
        + body
        + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF)
    )
    index = encoded.index(b"IDAT") - 4
    path = tmp_path / "texty.png"
    path.write_bytes(encoded[:index] + chunk + encoded[index:])

    from fpbench.core.imaging_models import canonical_pixel_hash

    with pytest.raises(ImagingError, match="tEXt"):
        verify_canonical_png(
            path,
            profile=profile,
            expected_width=16,
            expected_height=16,
            expected_pixel_sha256=canonical_pixel_hash(
                width=16, height=16, raster=raster
            ),
            image_label="texty",
        )


def test_the_parser_refuses_a_file_with_a_broken_crc(profile):
    raster = bytes(range(64))
    encoded = bytearray(
        encode_canonical_png(width=8, height=8, raster=raster, profile=profile)
    )
    encoded[20] ^= 0x01  # inside IHDR's payload, CRC now wrong
    with pytest.raises(ImagingError, match="CRC"):
        parse_png_chunks(bytes(encoded))


def test_the_parser_refuses_trailing_bytes_after_iend(profile):
    raster = bytes(range(64))
    encoded = encode_canonical_png(
        width=8, height=8, raster=raster, profile=profile
    )
    with pytest.raises(ImagingError, match="trailing"):
        parse_png_chunks(encoded + b"\x00\x00")


def test_the_parser_refuses_something_that_is_not_a_png():
    with pytest.raises(ImagingError, match="signature"):
        parse_png_chunks(b"not a png at all")


def test_every_transform_action_produces_a_conforming_file(tmp_path, profile):
    """The three SD300 paths, each written and re-verified from disk."""
    from fpbench.core.imaging_models import canonical_pixel_hash

    for source_ppi, (width, height) in (
        (500, (32, 24)),
        (1000, (64, 48)),
        (2000, (128, 96)),
    ):
        raster = bytes((x * 5 + source_ppi) % 256 for x in range(width * height))
        source_path = tmp_path / f"src-{source_ppi}.png"
        source_path.write_bytes(
            encode_canonical_png(
                width=width, height=height, raster=raster, profile=profile
            )
        )
        source = read_source_raster(source_path, profile=profile)
        artifact = canonicalise(source, profile=profile, source_ppi=source_ppi)

        out = tmp_path / f"out-{source_ppi}.png"
        out.write_bytes(artifact.encoded_bytes)
        verify_canonical_png(
            out,
            profile=profile,
            expected_width=artifact.width,
            expected_height=artifact.height,
            expected_pixel_sha256=artifact.pixel_sha256,
            expected_encoded_sha256=artifact.encoded_sha256,
            expected_size_bytes=artifact.size_bytes,
        )
        assert artifact.pixel_sha256 == canonical_pixel_hash(
            width=artifact.width, height=artifact.height, raster=artifact.raster
        )
