"""The fixtures are deterministic, content-addressed, and not fingerprints."""

from __future__ import annotations

import hashlib
import struct
import zlib

import pytest

from fpbench.flx import fixtures

pytestmark = pytest.mark.stage8b_contract


def _ihdr(payload: bytes) -> tuple[int, int, int, int, int]:
    width, height, depth, colour, _, _, interlace = struct.unpack(
        ">IIBBBBB", payload[16:29]
    )
    return width, height, depth, colour, interlace


def test_the_four_required_fixtures_exist() -> None:
    # Spec section 16 names these four as the minimum.
    assert {
        "fixture_white",
        "fixture_gradient",
        "fixture_synthetic_ridges",
        "fixture_seeded_noise",
    } <= set(fixtures.FIXTURE_BUILDERS)


def test_every_fixture_is_a_valid_gray8_png() -> None:
    for name, payload in fixtures.build_all_fixtures().items():
        width, height, depth, colour, interlace = _ihdr(payload)
        assert payload.startswith(b"\x89PNG\r\n\x1a\n"), name
        assert (depth, colour, interlace) == (8, 0, 0), name
        assert width > 0 and height > 0, name
        assert payload.endswith(b"IEND\xae\x42\x60\x82"), name


def test_every_fixture_is_byte_identical_on_regeneration() -> None:
    first = fixtures.build_all_fixtures()
    second = fixtures.build_all_fixtures()

    assert {name: hashlib.sha256(value).hexdigest() for name, value in first.items()} == {
        name: hashlib.sha256(value).hexdigest() for name, value in second.items()
    }
    assert first == second


def test_the_fixture_set_is_content_addressed() -> None:
    digests = fixtures.fixture_digests()

    assert set(digests) == set(fixtures.FIXTURE_BUILDERS)
    assert len(set(digests.values())) == len(digests)
    for digest in digests.values():
        assert len(digest) == 64


def test_the_canonical_fixtures_have_the_shape_the_real_pipeline_produces() -> None:
    for name in ("fixture_white", "fixture_gradient", "fixture_synthetic_ridges", "fixture_seeded_noise"):
        width, height, _, _, _ = _ihdr(fixtures.build_fixture(name))
        assert (width, height) == (fixtures.CANONICAL_WIDTH, fixtures.CANONICAL_HEIGHT), name


def test_one_fixture_has_an_odd_padding_difference_and_one_is_landscape() -> None:
    # 891 - 381 is even, so the canonical shape never exercises the parity rule.
    odd_width, odd_height, _, _, _ = _ihdr(fixtures.build_fixture("fixture_odd_padding"))
    assert (odd_height - odd_width) % 2 == 1

    wide_width, wide_height, _, _, _ = _ihdr(fixtures.build_fixture("fixture_landscape"))
    assert wide_width > wide_height


def test_the_white_fixture_is_uniformly_white() -> None:
    payload = fixtures.build_fixture("fixture_white")
    start = payload.index(b"IDAT") + 4
    length = struct.unpack(">I", payload[start - 8 : start - 4])[0]
    raster = zlib.decompress(payload[start : start + length])

    width = fixtures.CANONICAL_WIDTH
    for row in range(fixtures.CANONICAL_HEIGHT):
        offset = row * (width + 1)
        assert raster[offset] == 0
        assert set(raster[offset + 1 : offset + 1 + width]) == {255}


def test_an_unknown_fixture_is_named_rather_than_silently_empty() -> None:
    with pytest.raises(KeyError, match="unknown Stage 8B fixture"):
        fixtures.build_fixture("fixture_sd300")


def test_the_generator_names_no_biometric_corpus() -> None:
    import inspect

    source = inspect.getsource(fixtures).lower()
    for corpus in ("sd300", "sd4", "fvc", "mcyt", "sfinge", "nist"):
        assert f"{corpus} sample" not in source
    assert "none of these is a fingerprint" in source


def test_the_deliberately_invalid_inputs_are_invalid_in_the_way_they_claim() -> None:
    assert fixtures.corrupt_png().startswith(b"\x89PNG")
    assert len(fixtures.truncated_png()) < len(fixtures.build_fixture("fixture_white"))
    assert _ihdr(fixtures.wrong_bit_depth_png())[2] == 16
    assert _ihdr(fixtures.paletted_png())[3] == 3
    assert _ihdr(fixtures.interlaced_png())[4] == 1
    assert b"acTL" in fixtures.animated_png()
