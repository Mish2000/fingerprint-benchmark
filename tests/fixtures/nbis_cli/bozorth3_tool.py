"""A stand-in for BOZORTH3: its command line and its one line of output.

**Not a matcher.** It reads two XYT files, applies BOZORTH3's documented minimum
of ten minutiae per side, and otherwise prints a number derived from a digest. No
score it produces means anything about two fingerprints; what it is for is the
adapter's contract — argument order, the single integer on stdout, the zero
score, the non-zero exit, the crash, the timeout (spec section 53).

The one behaviour that is faithful on purpose is **asymmetry**: the number depends
on which file came first, so a test can prove the adapter runs
``bozorth3 <probe> <gallery>`` and not the other order. BOZORTH3's own
documentation says its scores are not necessarily symmetric (spec section 44).

Which case to act out arrives through the ``.brw`` file the extractor stand-in
writes beside the probe's XYT, because the adapter chooses both file names itself
and there is nothing else to key on:

    bozorth3-fail     exit 1                        (matching failed)
    bozorth3-crash    die: a signal on POSIX, a status outside 0..255 on Windows
    bozorth3-hang     sleep far past any budget
    bozorth3-noise    exit 0 and print two lines    (no usable score)
    bozorth3-silent   exit 0 and print nothing
    anything else     exit 0 and print one non-negative integer
"""

from __future__ import annotations

import hashlib
import os
import signal
import sys
import time
from pathlib import Path

#: BOZORTH3's documented minimum. Fewer minutiae on either side and the real tool
#: returns 0 rather than failing, which is the case this fixture has to reproduce
#: faithfully (spec sections 26 and 43).
MINIMUM_MINUTIAE = 10


def count_minutiae(path: Path) -> int:
    return len([line for line in path.read_text("ascii").splitlines() if line.strip()])


def case_beside(template: Path) -> str:
    sidecar = template.with_name(template.name[: -len(".xyt")] + ".brw")
    if not sidecar.is_file():
        return ""
    try:
        return sidecar.read_text("ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: bozorth3 <probefile> <galleryfile>\n")
        return 2
    probe, gallery = Path(argv[0]), Path(argv[1])
    case = case_beside(probe)

    if case == "bozorth3-hang":
        time.sleep(600)
        return 0
    if case == "bozorth3-crash":
        if os.name == "nt":
            os._exit(300)
        os.kill(os.getpid(), signal.SIGSEGV)
        return 0
    for path in (probe, gallery):
        if not path.is_file():
            sys.stderr.write("cannot read an input template\n")
            return 1
    if case == "bozorth3-fail":
        sys.stderr.write("comparison failed\n")
        return 1
    if case == "bozorth3-noise":
        sys.stdout.write("42\n7\n")
        return 0
    if case == "bozorth3-silent":
        return 0

    left, right = count_minutiae(probe), count_minutiae(gallery)
    if left < MINIMUM_MINUTIAE or right < MINIMUM_MINUTIAE:
        sys.stdout.write("0\n")
        return 0

    # Deliberately order-dependent: the probe's bytes are weighted differently
    # from the gallery's, so score(A, B) != score(B, A) for distinct templates.
    digest = hashlib.sha256(
        b"probe:" + probe.read_bytes() + b"|gallery:" + gallery.read_bytes()
    ).digest()
    sys.stdout.write(f"{int.from_bytes(digest[:2], 'big') % 400}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
