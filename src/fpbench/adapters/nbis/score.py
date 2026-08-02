"""Reading BOZORTH3's one line of output, and refusing every other shape.

A 1:1 BOZORTH3 invocation prints one non-negative integer and stops. That is the
whole contract, and it is worth enforcing exactly because the failure modes are
so quiet: a second line means the tool ran in a mode this route did not ask for,
``score=42`` means somebody added a flag, ``42.0`` means it is not BOZORTH3, and
an empty stdout means the comparison did not happen.

**0 is a score.** BOZORTH3 returns 0 when a side has fewer minutiae than its
minimum, and a genuine 0 for two templates that share no compatible structure.
Neither is a failure and neither may become ``NO_SCORE``: what the number *means*
biometrically is a question for the decision stage, over stored scores, and this
module has no opinion about it (docs/adr/0006, spec sections 25 and 26).

The upper bound is where a float stops being able to hold an integer exactly.
``raw_score`` is a float in the stored result, so a value above 2**53 would be
recorded as a different number than the one BOZORTH3 printed — which is not a
scale a matcher could plausibly produce, and therefore evidence that something
other than BOZORTH3 wrote the line.
"""

from __future__ import annotations

__all__ = ["ScoreFormatError", "MAX_EXACT_INTEGER_SCORE", "parse_bozorth3_score"]

#: The largest integer a Python float represents exactly.
MAX_EXACT_INTEGER_SCORE = 2**53

#: Enough of a rogue stdout to identify it, and not enough to put a tool's debug
#: output into every row of a run.
_MAX_EXCERPT_CHARS = 200


class ScoreFormatError(ValueError):
    """BOZORTH3 exited successfully without printing exactly one score."""

    def __init__(self, detail: str, *, excerpt: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.excerpt = " ".join(excerpt.split())[:_MAX_EXCERPT_CHARS]


def parse_bozorth3_score(stdout: str) -> int:
    """The single non-negative integer BOZORTH3 printed.

    A trailing newline is ordinary and accepted; anything else on stdout is not.

    Raises:
        ScoreFormatError: no line, more than one line, a non-integer, a negative
            number, extra text beside the number, or a value too large to survive
            being stored as a float.
    """
    if not isinstance(stdout, str):  # pragma: no cover - the caller passes str
        raise ScoreFormatError("stdout was not text")
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ScoreFormatError("printed nothing", excerpt=stdout)
    if len(lines) > 1:
        raise ScoreFormatError(
            f"printed {len(lines)} lines, expected one", excerpt=stdout
        )

    line = lines[0]
    if not line.isdigit() or not line.isascii():
        raise ScoreFormatError(
            "printed something that is not a non-negative integer", excerpt=stdout
        )
    value = int(line)
    if value > MAX_EXACT_INTEGER_SCORE:
        raise ScoreFormatError(
            "printed a value too large to store exactly", excerpt=stdout
        )
    return value
