"""The input contract, enforced before any process exists (spec section 20).

The adapter hands MINDTCT the prepared file byte for byte, which is only
defensible if the file really is an 8-bit greyscale PNG at 500 ppi. Everything
else is refused here, in Python, rather than discovered by a C program halfway
through a run.

One rejection is not like the others. A file of the right *shape* whose bytes no
longer hash to what the preparer recorded is not a fact about this pair: it means
the artefact changed after preflight approved it, so it is raised as drift and is
fatal to the invocation rather than recorded as a comparison failure
(docs/adr/0033).

The ``pHYs`` chunk is deliberately not consulted, and there is a test for that
absence: re-introducing a resolution check here would quietly undo what the PPI
probe measured (docs/adr/0047).
"""

from __future__ import annotations

import struct
import zlib

import pytest

from fpbench.adapters.nbis.png_input import (
    MIN_SIDE_PIXELS,
    NbisInputRejected,
    require_gray8_500ppi_png,
)
from fpbench.core.errors import PreparedImageDriftError
from nbisworld import gray8_png, png_with_phys, prepared_image

pytestmark = pytest.mark.nbis_contract


def chunk(kind: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def png(width: int, height: int, depth: int, colour: int, *, plte: bool = False) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)
    parts = [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", header)]
    if plte:
        parts.append(chunk(b"PLTE", b"\x00\x00\x00" * 256))
    parts.append(chunk(b"IDAT", zlib.compress(b"\x00" * 16)))
    parts.append(chunk(b"IEND", b""))
    return b"".join(parts)


# --------------------------------------------------------------- accepted


def test_a_gray8_500ppi_png_is_accepted(tmp_path):
    payload = gray8_png(1)
    raster = require_gray8_500ppi_png(prepared_image(tmp_path / "left.png", payload))
    assert raster.width == raster.height == 250
    assert raster.size_bytes == len(payload)


def test_a_png_without_phys_is_accepted(tmp_path):
    """Section 41: the default 500 ppi route does not need the chunk."""
    payload = gray8_png(2)
    assert b"pHYs" not in payload
    require_gray8_500ppi_png(prepared_image(tmp_path / "left.png", payload))


@pytest.mark.parametrize("declared", [500, 1000, 2000])
def test_the_phys_chunk_is_never_consulted(tmp_path, declared):
    """Whatever it says, the file is accepted; MINDTCT ignores it too."""
    payload = png_with_phys(gray8_png(3), declared)
    require_gray8_500ppi_png(prepared_image(tmp_path / f"p{declared}.png", payload))


# --------------------------------------------------------------- rejected


def test_a_16_bit_png_is_refused(tmp_path):
    payload = png(64, 64, 16, 0)
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(prepared_image(tmp_path / "deep.png", payload))
    assert raised.value.reason == "unsupported_bit_depth"


def test_an_rgb_png_is_refused(tmp_path):
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(
            prepared_image(tmp_path / "rgb.png", png(64, 64, 8, 2))
        )
    assert raised.value.reason == "unsupported_colour_type"


def test_an_rgba_png_is_refused(tmp_path):
    with pytest.raises(NbisInputRejected, match="colour"):
        require_gray8_500ppi_png(
            prepared_image(tmp_path / "rgba.png", png(64, 64, 8, 6))
        )


def test_a_greyscale_with_alpha_png_is_refused(tmp_path):
    with pytest.raises(NbisInputRejected, match="colour"):
        require_gray8_500ppi_png(
            prepared_image(tmp_path / "ga.png", png(64, 64, 8, 4))
        )


def test_an_indexed_png_is_refused(tmp_path):
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(
            prepared_image(tmp_path / "idx.png", png(64, 64, 8, 3, plte=True))
        )
    assert raised.value.reason == "unsupported_colour_type"


def test_a_corrupt_png_is_refused(tmp_path):
    payload = b"\x89PNG\r\n\x1a\ndeliberately not a valid PNG body"
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(prepared_image(tmp_path / "bad.png", payload))
    assert raised.value.reason in ("malformed_png", "not_a_png")


def test_a_file_that_is_not_a_png_is_refused(tmp_path):
    with pytest.raises(NbisInputRejected, match="signature"):
        require_gray8_500ppi_png(prepared_image(tmp_path / "text.png", b"hello there"))


def test_a_truncated_png_is_refused(tmp_path):
    payload = gray8_png(1)[: len(gray8_png(1)) // 2]
    with pytest.raises(NbisInputRejected):
        require_gray8_500ppi_png(prepared_image(tmp_path / "cut.png", payload))


def test_a_png_with_no_image_data_is_refused(tmp_path):
    header = struct.pack(">IIBBBBB", 64, 64, 8, 0, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")
    with pytest.raises(NbisInputRejected, match="image data"):
        require_gray8_500ppi_png(prepared_image(tmp_path / "empty.png", payload))


def test_an_interlaced_png_is_refused(tmp_path):
    header = struct.pack(">IIBBBBB", 64, 64, 8, 0, 0, 0, 1)
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", zlib.compress(b"\x00" * 16)),
            chunk(b"IEND", b""),
        ]
    )
    with pytest.raises(NbisInputRejected, match="interlaced"):
        require_gray8_500ppi_png(prepared_image(tmp_path / "il.png", payload))


def test_a_tiny_raster_is_refused(tmp_path):
    payload = png(MIN_SIDE_PIXELS - 1, MIN_SIDE_PIXELS - 1, 8, 0)
    with pytest.raises(NbisInputRejected, match="dimensions"):
        require_gray8_500ppi_png(prepared_image(tmp_path / "tiny.png", payload))


@pytest.mark.parametrize("ppi", [1000, 2000, 499, 5080])
def test_any_resolution_other_than_500_is_refused(tmp_path, ppi):
    """Section 22: this route is defined at 500 and nowhere else."""
    image = prepared_image(tmp_path / "x.png", gray8_png(1), effective_ppi=ppi)
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(image)
    assert raised.value.reason == "unsupported_resolution"


def test_a_non_png_media_type_is_refused(tmp_path):
    image = prepared_image(tmp_path / "x.png", gray8_png(1), media_type="image/x-wsq")
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(image)
    assert raised.value.reason == "unsupported_media_type"


def test_a_missing_file_is_refused(tmp_path):
    image = prepared_image(tmp_path / "gone.png", gray8_png(1))
    (tmp_path / "gone.png").unlink()
    with pytest.raises(NbisInputRejected) as raised:
        require_gray8_500ppi_png(image)
    assert raised.value.reason == "input_missing"


def test_a_symlinked_input_is_refused(tmp_path):
    image = prepared_image(tmp_path / "real.png", gray8_png(1))
    link = tmp_path / "link.png"
    try:
        link.symlink_to(tmp_path / "real.png")
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    from dataclasses import replace

    with pytest.raises(NbisInputRejected, match="symlink"):
        require_gray8_500ppi_png(replace(image, local_path=link.resolve()))


# ------------------------------------------------------------------- drift


def test_bytes_that_no_longer_hash_to_the_prepared_digest_are_fatal(tmp_path):
    """Not a comparison failure: the artefact changed after preflight."""
    image = prepared_image(tmp_path / "left.png", gray8_png(1))
    (tmp_path / "left.png").write_bytes(gray8_png(4))
    with pytest.raises(PreparedImageDriftError, match="no longer hashes"):
        require_gray8_500ppi_png(image)


def test_a_size_that_disagrees_with_the_prepared_entry_is_fatal(tmp_path):
    from dataclasses import replace

    image = prepared_image(tmp_path / "left.png", gray8_png(1))
    with pytest.raises(PreparedImageDriftError):
        require_gray8_500ppi_png(replace(image, prepared_size_bytes=7))
