"""What the transform does to pixels, checked against committed golden hashes.

Every assertion here is either "these exact bytes came out" or "this thing
demonstrably did not happen". Both matter, and the second is the one a
plausible-looking bug survives: a downsampler that also sharpened slightly would
produce a perfectly reasonable image, and only a golden hash notices.

The golden values are tied to the pinned resampler. When the recorded Pillow
version does not match the installed one the hash comparisons are skipped and
the *structural* properties — dimensions, polarity, no inversion, black stays
black — are still asserted, because those hold for any correct Lanczos
implementation and a silent full skip would hide a real regression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import ImagingError, SourceImageContractError
from fpbench.core.imaging_models import (
    TRANSFORM_ACTION_IDENTITY,
    canonical_pixel_hash,
)
from fpbench.imaging.canonical import (
    canonicalise,
    encode_canonical_png,
    read_source_raster,
)
from fpbench.imaging.runtime import pillow_distribution_fingerprint
from fpbench.imaging.transform_profile import load_transform_profile

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "imaging"


@pytest.fixture(scope="module")
def golden():
    payload = json.loads((FIXTURE_DIRECTORY / "expected.json").read_text("utf-8"))
    return payload


@pytest.fixture(scope="module")
def profile():
    return load_transform_profile()


@pytest.fixture(scope="module")
def pinned_resampler(golden) -> bool:
    """Whether the installed Pillow is the one the golden hashes were taken under."""
    installed, _, _ = pillow_distribution_fingerprint()
    return installed == golden["generated_under"]["pillow_version"]


@pytest.fixture(scope="module")
def pinned_encoder(golden, pinned_resampler) -> bool:
    """Also the same zlib build, which decides the compressed bytes but not the pixels."""
    from fpbench.imaging.runtime import pillow_zlib_version

    return pinned_resampler and (
        pillow_zlib_version() == golden["generated_under"]["zlib_runtime_version"]
    )


def _fixture_names(golden):
    return sorted(golden["fixtures"])


def test_the_golden_file_was_taken_under_this_transform_profile(golden, profile):
    """The profile is part of the golden values' meaning.

    If the profile changes, the fixtures must be regenerated deliberately — the
    point of committing them is that nobody can change the transformation and
    still see a green suite.
    """
    assert (
        golden["generated_under"]["transform_profile_fingerprint"]
        == profile.profile_fingerprint
    )


@pytest.mark.parametrize(
    "name",
    [
        "gray8_even_500ppi",
        "gray8_odd_1000ppi",
        "gray8_quarter_remainder_2000ppi",
        "checkerboard_2000ppi",
        "horizontal_ridges_1000ppi",
        "vertical_ridges_1000ppi",
        "impulse_2000ppi",
        "constant_black_1000ppi",
        "constant_white_1000ppi",
        "gradient_1000ppi",
    ],
)
def test_every_fixture_transforms_to_its_golden_values(
    name, golden, profile, pinned_resampler, pinned_encoder
):
    expected = golden["fixtures"][name]
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    assert source.width == expected["source"]["width"]
    assert source.height == expected["source"]["height"]
    assert source.pixel_sha256 == expected["source"]["pixel_sha256"]

    artifact = canonicalise(
        source,
        profile=profile,
        source_ppi=expected["source"]["effective_ppi"],
        image_label=name,
    )
    # Structural, and true of any correct implementation.
    assert artifact.width == expected["output"]["width"]
    assert artifact.height == expected["output"]["height"]
    assert artifact.transform_action == expected["output"]["transform_action"]
    assert len(artifact.raster) == artifact.width * artifact.height

    if pinned_resampler:
        assert artifact.pixel_sha256 == expected["output"]["pixel_sha256"]
    if pinned_encoder:
        assert artifact.encoded_sha256 == expected["output"]["encoded_sha256"]
        assert artifact.size_bytes == expected["output"]["size_bytes"]


def test_a_500_ppi_source_keeps_its_raster_byte_for_byte(golden, profile):
    """SD300A's control invariant, in miniature.

    Not one pixel value moves (spec sections 19 and 84).
    """
    name = "gray8_even_500ppi"
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    artifact = canonicalise(source, profile=profile, source_ppi=500, image_label=name)

    assert artifact.transform_action == TRANSFORM_ACTION_IDENTITY
    assert (artifact.width, artifact.height) == (source.width, source.height)
    assert artifact.raster == source.raster
    assert artifact.pixel_sha256 == source.pixel_sha256


def test_the_identity_path_still_re_encodes_rather_than_copying(tmp_path, profile):
    """Same pixels, our encoder, our metadata.

    Copying an SD300A file straight through would be faster and would leave one
    release carrying NIST's PNG encoding while the other two carried ours — so a
    difference between releases could be a difference in the container rather
    than in the resolution. The two identities diverge here and that is the
    point of keeping both (docs/adr/0034).
    """
    from PIL import Image

    raster = bytes((x * 13 + 7) % 256 for x in range(32 * 24))
    path = tmp_path / "loosely-encoded.png"
    with Image.frombytes("L", (32, 24), raster) as image:
        # A different compression level: same pixels, different file.
        image.save(path, format="PNG", compress_level=1, dpi=(500, 500))

    source = read_source_raster(path, profile=profile, image_label="loose")
    artifact = canonicalise(source, profile=profile, source_ppi=500, image_label="loose")

    assert artifact.pixel_sha256 == source.pixel_sha256
    assert artifact.encoded_sha256 != source.encoded_sha256
    assert artifact.size_bytes != source.size_bytes


def test_a_direct_quarter_differs_from_two_chained_halvings(profile, pinned_resampler):
    """2000 -> 500 is one resampling, and it is not 2000 -> 1000 -> 500.

    Two Lanczos passes are a different filter from one. If they agreed there
    would be no reason for the profile to insist on ``direct_source_to_target``;
    this test is what makes the insistence checkable (spec section 21).
    """
    if not pinned_resampler:
        pytest.skip("golden pixel comparison needs the pinned Pillow")

    from PIL import Image

    name = "checkerboard_2000ppi"
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    direct = canonicalise(source, profile=profile, source_ppi=2000, image_label=name)

    with Image.frombytes("L", (source.width, source.height), source.raster) as start:
        half = start.resize(
            (source.width // 2, source.height // 2),
            resample=Image.Resampling.LANCZOS,
            reducing_gap=None,
        )
        quarter = half.resize(
            (direct.width, direct.height),
            resample=Image.Resampling.LANCZOS,
            reducing_gap=None,
        )
        chained = quarter.tobytes()
        half.close()
        quarter.close()

    assert len(chained) == len(direct.raster)
    assert chained != direct.raster, (
        "chaining two halvings produced the same pixels as one quartering; the "
        "profile's direct_source_to_target rule would then be unfalsifiable"
    )


def test_a_constant_image_stays_constant(profile):
    """No contrast normalisation, no histogram equalisation, no gamma.

    A flat image is the sharpest test of all three: any of them would map a
    uniform grey onto a different uniform grey, or onto something that is no
    longer uniform at the edges.
    """
    for name, value in (
        ("constant_black_1000ppi", 0),
        ("constant_white_1000ppi", 255),
    ):
        source = read_source_raster(
            FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
        )
        artifact = canonicalise(
            source, profile=profile, source_ppi=1000, image_label=name
        )
        assert set(artifact.raster) == {value}


def test_polarity_is_never_flipped(profile):
    """A gradient that ran dark-to-light still runs dark-to-light.

    Inversion is the one transformation that would leave every statistic intact
    and every score wrong.
    """
    name = "gradient_1000ppi"
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    artifact = canonicalise(source, profile=profile, source_ppi=1000, image_label=name)
    row = artifact.raster[: artifact.width]
    assert row[0] < row[-1]
    assert row == bytes(sorted(row))


def test_nothing_is_cropped_or_padded(profile, golden):
    """Output area follows the formula for every fixture, with no slack.

    A cropped image would be smaller than the formula says and a padded one
    larger; both would still decode, and both would change what a matcher saw.
    """
    for name, expected in golden["fixtures"].items():
        source = read_source_raster(
            FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
        )
        artifact = canonicalise(
            source,
            profile=profile,
            source_ppi=expected["source"]["effective_ppi"],
            image_label=name,
        )
        scale = expected["source"]["effective_ppi"] // 500
        assert artifact.width == (2 * source.width + scale) // (2 * scale)
        assert artifact.height == (2 * source.height + scale) // (2 * scale)


def test_an_impulse_stays_where_it_was(profile):
    """No rotation and no mirroring.

    A single bright pixel at the centre of a 65x65 image lands at the centre of
    a 16x16 one. A rotated or mirrored image would put its energy somewhere else
    — and for a symmetric input, only an asymmetric one can tell.
    """
    name = "impulse_2000ppi"
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    artifact = canonicalise(source, profile=profile, source_ppi=2000, image_label=name)

    brightest = max(range(len(artifact.raster)), key=lambda i: artifact.raster[i])
    row, column = divmod(brightest, artifact.width)
    assert abs(row - artifact.height // 2) <= 1
    assert abs(column - artifact.width // 2) <= 1


def test_ridge_orientation_survives(profile):
    """Horizontal stripes stay horizontal; vertical stripes stay vertical."""
    horizontal = _artifact(profile, "horizontal_ridges_1000ppi", 1000)
    vertical = _artifact(profile, "vertical_ridges_1000ppi", 1000)

    def row_variance(artifact) -> int:
        rows = [
            artifact.raster[index * artifact.width : (index + 1) * artifact.width]
            for index in range(artifact.height)
        ]
        return len({bytes(row) for row in rows})

    # Horizontal stripes: every row is uniform, rows differ from each other.
    assert row_variance(horizontal) > 1
    assert all(
        len(
            set(
                horizontal.raster[
                    index * horizontal.width : (index + 1) * horizontal.width
                ]
            )
        )
        == 1
        for index in range(horizontal.height)
    )
    # Vertical stripes: every row is identical, and each row is not uniform.
    assert row_variance(vertical) == 1
    assert len(set(vertical.raster[: vertical.width])) > 1


def test_upsampling_is_refused(profile):
    name = "gray8_even_500ppi"
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    with pytest.raises(ImagingError, match="upsampling is forbidden"):
        canonicalise(source, profile=profile, source_ppi=250, image_label=name)


def test_the_canonical_pixel_hash_binds_the_shape_as_well_as_the_bytes():
    raster = bytes(range(24))
    wide = canonical_pixel_hash(width=6, height=4, raster=raster)
    tall = canonical_pixel_hash(width=4, height=6, raster=raster)
    assert wide != tall

    with pytest.raises(ValueError, match="bytes"):
        canonical_pixel_hash(width=6, height=4, raster=raster[:-1])


def test_a_colour_source_is_refused_rather_than_flattened(tmp_path, profile):
    """RGB in, error out.

    Converting quietly would change what the experiment measured — which channel
    weights? whose luma coefficients? — without changing anything the experiment
    records (spec section 14).
    """
    from PIL import Image

    path = tmp_path / "colour.png"
    with Image.new("RGB", (8, 8), (10, 20, 30)) as image:
        image.save(path, format="PNG")

    with pytest.raises(SourceImageContractError, match="colour type"):
        read_source_raster(path, profile=profile, image_label="colour")


def test_a_sixteen_bit_source_is_refused_rather_than_narrowed(tmp_path, profile):
    from PIL import Image

    path = tmp_path / "deep.png"
    with Image.new("I;16", (8, 8), 1000) as image:
        image.save(path, format="PNG")

    with pytest.raises(SourceImageContractError, match="bit depth"):
        read_source_raster(path, profile=profile, image_label="deep")


def test_a_paletted_source_is_refused(tmp_path, profile):
    from PIL import Image

    path = tmp_path / "paletted.png"
    with Image.new("P", (8, 8)) as image:
        image.putpalette([index % 256 for index in range(768)])
        image.save(path, format="PNG")

    with pytest.raises(SourceImageContractError):
        read_source_raster(path, profile=profile, image_label="paletted")


def test_a_source_carrying_colour_management_is_refused(tmp_path, profile):
    """``gAMA`` says the samples are not what they appear to be.

    The source may keep a wrong ``pHYs`` — the manifest's effective ppi is
    authoritative and nothing reads the header — but a chunk that changes how a
    *sample* should be interpreted has no such override, so the image is refused
    (spec section 15).
    """
    raster = bytes((x * 7) % 256 for x in range(64))
    clean = encode_canonical_png(width=8, height=8, raster=raster, profile=profile)

    path = tmp_path / "gamma.png"
    path.write_bytes(_with_chunk(clean, b"gAMA", (45455).to_bytes(4, "big")))

    assert b"gAMA" in path.read_bytes()
    with pytest.raises(SourceImageContractError, match="gAMA"):
        read_source_raster(path, profile=profile, image_label="gamma")


def test_a_source_carrying_an_icc_profile_is_refused(tmp_path, profile):
    raster = bytes((x * 5) % 256 for x in range(64))
    clean = encode_canonical_png(width=8, height=8, raster=raster, profile=profile)
    path = tmp_path / "iccp.png"
    path.write_bytes(_with_chunk(clean, b"iCCP", b"name\x00\x00" + b"\x00" * 4))

    with pytest.raises(SourceImageContractError, match="iCCP"):
        read_source_raster(path, profile=profile, image_label="iccp")


def _with_chunk(png: bytes, chunk_type: bytes, body: bytes) -> bytes:
    """Splice one chunk in just before the first IDAT.

    Pillow will not write ``gAMA`` or ``iCCP`` for a plain grayscale save, and
    an ambiguity the parser cannot be shown refusing is an ambiguity nobody has
    tested. So the container is edited directly — which is also a fair
    reproduction of what an upstream delivery might hand over.
    """
    import struct
    import zlib

    index = png.index(b"IDAT") - 4
    chunk = (
        struct.pack(">I", len(body))
        + chunk_type
        + body
        + struct.pack(">I", zlib.crc32(chunk_type + body) & 0xFFFFFFFF)
    )
    return png[:index] + chunk + png[index:]


def test_a_wrong_phys_in_the_source_is_recorded_and_ignored(tmp_path, profile):
    """SD300C in one test.

    The file says 5080; the manifest says 2000; the scale uses 2000 and the
    declared value is kept in provenance (docs/adr/0004, docs/adr/0032).
    """
    from PIL import Image

    raster = bytes((x * 3) % 256 for x in range(64 * 64))
    path = tmp_path / "wrong-phys.png"
    with Image.frombytes("L", (64, 64), raster) as image:
        image.save(path, format="PNG", dpi=(5080, 5080), compress_level=9)

    source = read_source_raster(path, profile=profile, image_label="wrong")
    assert "200000" in str(source.declared_ppi)  # 5080 ppi in pixels per metre

    artifact = canonicalise(source, profile=profile, source_ppi=2000, image_label="w")
    assert (artifact.width, artifact.height) == (16, 16)


def _artifact(profile, name: str, source_ppi: int):
    source = read_source_raster(
        FIXTURE_DIRECTORY / f"{name}.png", profile=profile, image_label=name
    )
    return canonicalise(
        source, profile=profile, source_ppi=source_ppi, image_label=name
    )


def test_the_encoder_round_trips_any_raster(profile):
    """Encode, decode, and get the same pixels. The most basic obligation."""
    from PIL import Image
    import io

    for width, height in ((1, 1), (7, 3), (64, 64)):
        raster = bytes((x * 31) % 256 for x in range(width * height))
        encoded = encode_canonical_png(
            width=width, height=height, raster=raster, profile=profile
        )
        with Image.open(io.BytesIO(encoded)) as decoded:
            decoded.load()
            assert decoded.tobytes() == raster
