"""A stand-in for a command-line template matcher. Not a biometric tool.

    matcher.py <left-template> <right-template>

Reads two templates, prints ``score=<number>``, exits zero. The number is a
deterministic function of the two digests — arithmetic, not biometrics. **No
score this fixture produces means anything about two fingerprints**, and nothing
derived from one may appear in a research claim.

Its purpose is to be *shaped* like Bozorth3: a separate process, taking two
template files and printing a number, able to fail the handful of ways a real
matcher fails. Behaviour is chosen by markers the extractor copied into the
templates, so a test picks an outcome by writing an input file.

Markers, matched in either template:

    FPBENCH-FIXTURE:MATCH-FAIL      exit 4, the "these two would not match" code
    FPBENCH-FIXTURE:MATCH-NOSCORE   exit 0 having printed nothing usable
    FPBENCH-FIXTURE:MATCH-CRASH     die without an orderly exit
    FPBENCH-FIXTURE:MATCH-HANG      sleep until something kills it
    FPBENCH-FIXTURE:MATCH-NOISY     write a great deal to stderr, then succeed
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

TEMPLATE_MAGIC = "FPTEMPLATE1"

FAIL = "FPBENCH-FIXTURE:MATCH-FAIL"
NO_SCORE = "FPBENCH-FIXTURE:MATCH-NOSCORE"
CRASH = "FPBENCH-FIXTURE:MATCH-CRASH"
HANG = "FPBENCH-FIXTURE:MATCH-HANG"
NOISY = "FPBENCH-FIXTURE:MATCH-NOISY"

#: "I compared them and produced no comparable structure." A distinct number,
#: for the same reason the extractor has one.
EXIT_NO_MATCH = 4

#: Scores run 0..100, higher meaning more similar. Fixed so that a threshold
#: written against this fixture keeps meaning the same thing.
SCORE_SCALE = 100.0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: matcher.py <left-template> <right-template>\n")
        return 2

    try:
        left = _read_template(argv[1])
        right = _read_template(argv[2])
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"unusable template: {type(exc).__name__}\n")
        return 2

    text = left + right
    if HANG in text:
        time.sleep(600)
        return 0
    if CRASH in text:
        sys.stderr.write("matcher died\n")
        os._exit(139)
    if FAIL in text:
        sys.stderr.write("the two templates share no comparable structure\n")
        return EXIT_NO_MATCH
    if NOISY in text:
        sys.stderr.write("e" * 4_000_000)
    if NO_SCORE in text:
        sys.stdout.write("score=unavailable\n")
        return 0

    sys.stdout.write(f"score={_score(left, right):.4f}\n")
    return 0


def _read_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.strip():
        raise ValueError("empty template")
    if not text.startswith(TEMPLATE_MAGIC):
        raise ValueError("not a template")
    return text


def _score(left: str, right: str) -> float:
    """Deterministic, ordered, and reproducible across machines.

    Left then right, never sorted: an accidentally symmetric matcher would be a
    bug worth detecting, and the adapter's contract fixes left as the probe
    (spec section 67).
    """
    payload = (left + "\0" + right).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:6], "big") / float((1 << 48) - 1) * SCORE_SCALE


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
