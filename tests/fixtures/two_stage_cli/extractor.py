"""A stand-in for a command-line template extractor. Not a biometric tool.

    extractor.py <input-path> <template-path>

Reads one file, writes one template, exits zero. What it produces is a digest of
the input with a header on it — there is no image decoding here, no minutiae and
no biometrics of any kind, and no number this fixture influences may appear in a
research claim.

Its purpose is to be *shaped* like MINDTCT: a separate process, taking a file and
producing a file, able to fail in the handful of ways a real extractor fails. The
failure it takes is chosen by a marker in the input bytes, so a test picks a
behaviour by writing a file rather than by setting an environment variable — the
adapter under test passes no environment through, which is exactly the property
being relied on.

Markers, matched anywhere in the input:

    FPBENCH-FIXTURE:EXTRACT-FAIL     exit 3, the "no template from this print" code
    FPBENCH-FIXTURE:EXTRACT-EMPTY    write a zero-byte template, exit 0
    FPBENCH-FIXTURE:EXTRACT-MISSING  write nothing at all, exit 0
    FPBENCH-FIXTURE:EXTRACT-CRASH    die without an orderly exit
    FPBENCH-FIXTURE:EXTRACT-HANG     sleep until something kills it
    FPBENCH-FIXTURE:EXTRACT-NOISY    write a great deal to stdout, then succeed

A marker found here is copied into the template, so the matcher downstream can be
told what to do by the same mechanism.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

TEMPLATE_MAGIC = "FPTEMPLATE1"

MARKER_PREFIX = b"FPBENCH-FIXTURE:"

FAIL = b"FPBENCH-FIXTURE:EXTRACT-FAIL"
EMPTY = b"FPBENCH-FIXTURE:EXTRACT-EMPTY"
MISSING = b"FPBENCH-FIXTURE:EXTRACT-MISSING"
CRASH = b"FPBENCH-FIXTURE:EXTRACT-CRASH"
HANG = b"FPBENCH-FIXTURE:EXTRACT-HANG"
NOISY = b"FPBENCH-FIXTURE:EXTRACT-NOISY"

#: The exit code this tool uses for "I looked at it and produced no template".
#: A distinct number, so the adapter maps a biometric outcome without reading
#: any English (spec section 76).
EXIT_NO_TEMPLATE = 3


def markers(payload: bytes) -> list[bytes]:
    """Every fixture marker in the payload, in order of appearance."""
    found: list[bytes] = []
    start = 0
    while True:
        index = payload.find(MARKER_PREFIX, start)
        if index < 0:
            return found
        end = index
        while end < len(payload) and payload[end : end + 1].isupper() or payload[
            end : end + 1
        ] in (b":", b"-"):
            end += 1
        found.append(payload[index:end])
        start = max(end, index + 1)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: extractor.py <input-path> <template-path>\n")
        return 2

    input_path, template_path = argv[1], argv[2]
    try:
        with open(input_path, "rb") as handle:
            payload = handle.read()
    except OSError as exc:
        sys.stderr.write(f"cannot read input: {type(exc).__name__}\n")
        return 2

    found = markers(payload)

    if HANG in found:
        time.sleep(600)
        return 0
    if CRASH in found:
        sys.stderr.write("extractor died\n")
        os._exit(134)
    if FAIL in found:
        sys.stderr.write("no usable ridge structure in this input\n")
        return EXIT_NO_TEMPLATE
    if MISSING in found:
        return 0
    if NOISY in found:
        sys.stdout.write("x" * 4_000_000)

    body = "" if EMPTY in found else _template(payload, found)
    try:
        with open(template_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    except OSError as exc:
        sys.stderr.write(f"cannot write template: {type(exc).__name__}\n")
        return 2
    return 0


def _template(payload: bytes, found: list[bytes]) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    lines = [f"{TEMPLATE_MAGIC} {digest}"]
    lines.extend(marker.decode("ascii") for marker in found)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
