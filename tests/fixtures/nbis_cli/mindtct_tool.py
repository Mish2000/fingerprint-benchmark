"""A stand-in for MINDTCT: its command line, its file layout, and nothing else.

This is **not** a minutiae extractor and produces nothing biometric. It exists so
that the NBIS adapter's own contract — the exact argument order, the eight output
files beside one root, the empty-XYT case, the non-zero exit, the crash, the
timeout — can be exercised on a machine that has never built NBIS and without a
network (spec section 53).

It reads the PNG's IHDR so the minutiae it invents land inside the raster, which
is what makes the adapter's bounds check meaningful. Everything else about the
numbers is arithmetic on a digest.

**Which case to act out is carried by the image, not by its name.** The adapter
stages every input as ``left-input.png`` or ``right-input.png``, so a fixture that
keyed on the file name could not be steered at all. A test instead embeds a PNG
``tEXt`` chunk with the keyword ``fpbench-case``:

    mindtct-fail      exit 1, write nothing        (mindtct declines the print)
    mindtct-empty     exit 0, write an empty XYT   (a template with no minutiae)
    mindtct-garbage   exit 0, write an unusable XYT
    mindtct-noxyt     exit 0, write every file except the XYT
    mindtct-crash     die: a signal on POSIX, a status outside 0..255 on Windows
    mindtct-hang      sleep far past any budget
    mindtct-few       exit 0, write nine minutiae
    anything else     exit 0, write a full template

A ``bozorth3-*`` case is passed through: it is written into the ``.brw`` file
beside the XYT, which is where the matcher stand-in looks for it. Both files are
removed by the adapter's own cleanup, so this smuggles nothing into a test's
assertions about the working directory.
"""

from __future__ import annotations

import hashlib
import os
import signal
import struct
import sys
import time
from pathlib import Path

#: Everything the real tool writes beside its output root. All eight, so the
#: adapter's cleanup is exercised against the real file set.
SUFFIXES = ("xyt", "min", "brw", "dm", "hcm", "lcm", "lfm", "qm")

CASE_KEYWORD = b"fpbench-case\x00"


def case_of(payload: bytes) -> str:
    """The ``fpbench-case`` tEXt value, or the empty string.

    A PNG chunk is ``[length][type][data][crc]``, and the keyword sits at the
    start of the data — so the length is the eight bytes before it.
    """
    index = payload.find(CASE_KEYWORD)
    if index < 8:
        return ""
    length = int.from_bytes(payload[index - 8 : index - 4], "big")
    data = payload[index : index + length]
    _keyword, _, text = data.partition(b"\x00")
    return text.decode("ascii", "replace").strip()


def raster_size(payload: bytes) -> tuple[int, int]:
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    width, height = struct.unpack(">II", payload[16:24])
    return (width, height)


def minutiae(payload: bytes, width: int, height: int, count: int) -> list[str]:
    digest = hashlib.sha256(payload).digest()
    lines = []
    for index in range(count):
        seed = hashlib.sha256(digest + index.to_bytes(2, "big")).digest()
        x = seed[0] % max(width - 1, 1)
        y = seed[1] % max(height - 1, 1)
        theta = (seed[2] * 360) // 256
        quality = seed[3] % 101
        lines.append(f"{x} {y} {theta} {quality}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: mindtct <image> <output-root>\n")
        return 2
    image = Path(argv[0])
    root = Path(argv[1])
    if not image.is_file():
        sys.stderr.write("cannot read the input image\n")
        return 1
    payload = image.read_bytes()
    case = case_of(payload)

    if case == "mindtct-hang":
        time.sleep(600)
        return 0
    if case == "mindtct-crash":
        # A real crash on POSIX. On Windows a signal is not available and an
        # unhandled fault surfaces as a status far outside the 0..255 an ordinary
        # program returns, so the fixture returns one of those instead — which is
        # exactly what ``is_process_crash`` keys on.
        if os.name == "nt":
            os._exit(300)
        os.kill(os.getpid(), signal.SIGSEGV)
        return 0
    if case == "mindtct-fail":
        sys.stderr.write("no minutiae could be detected\n")
        return 1

    width, height = raster_size(payload)
    if case == "mindtct-empty":
        lines: list[str] = []
    elif case == "mindtct-garbage":
        lines = ["1 2 3", "not an xyt line at all"]
    elif case == "mindtct-few":
        lines = minutiae(payload, width, height, 9)
    else:
        # Payload-dependent, and always above BOZORTH3's minimum of ten. Two
        # different rasters have to produce two different counts, or the
        # conformance suite's directional golden — the sides' counts must swap
        # when the sides swap — would hold vacuously (spec section 44).
        lines = minutiae(
            payload, width, height, 12 + hashlib.sha256(payload).digest()[4] % 40
        )

    root.parent.mkdir(parents=True, exist_ok=True)
    written = [item for item in SUFFIXES if not (case == "mindtct-noxyt" and item == "xyt")]
    for suffix in written:
        target = root.with_name(f"{root.name}.{suffix}")
        if suffix == "xyt":
            target.write_text(
                ("\n".join(lines) + "\n") if lines else "", encoding="ascii"
            )
        elif suffix == "brw":
            # The channel the matcher stand-in reads its own case from.
            target.write_text(case if case.startswith("bozorth3-") else "", encoding="ascii")
        else:
            target.write_bytes(hashlib.sha256(payload + suffix.encode()).digest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
