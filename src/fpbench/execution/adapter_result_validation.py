"""What no raw result may ever contain, whatever produced it.

A raw result records how a comparison was carried out and what came back. It
must not record what the comparison *meant*: no threshold, no decision, no
ground truth, no protocol stage, no subject. That is docs/adr/0003 and
docs/adr/0010 stated as data rather than as prose, and it is checked rather than
assumed — an adapter that helpfully copied ``protocol_stage`` into its metadata
would have had to be given it, and being given it is the thing the contract is
arranged to prevent.

The list lives here, in ``execution``, because it belongs to every algorithm.
SourceAFIS's validator started with it and added two of its own; the next
algorithm will start with it and add different ones.

**Template and minutiae keys are deliberately not on this list.** A route that
extracts before it matches may legitimately want to record that it wrote a
template file, how many minutiae it found, or which intermediate it fed the
matcher — and refusing all of that by keyword would force a real pipeline to
describe itself dishonestly. What is forbidden is *publishing the template
itself* inside metadata, which is a rule about payloads rather than about names:
a template is an artefact with a digest, and ``artifacts`` is where a result
points at one (docs/adr/0041).
"""

from __future__ import annotations

from typing import Iterable, Mapping

__all__ = [
    "FORBIDDEN_METADATA_KEYS",
    "forbidden_metadata_present",
    "MAX_METADATA_VALUE_CHARS",
]

#: Keys that would mean an adapter had made a decision, or had been told
#: something about the pair it must not know.
FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "threshold",
        "decision",
        "is_match",
        "matched",
        "ground_truth",
        "protocol_stage",
        "subject_id",
    }
)

#: A metadata value longer than this is almost certainly a payload rather than a
#: description — an encoded template, a minutiae dump, a stack trace. Advisory:
#: a validator decides what to do about it, because "too long" is a judgement
#: and the taxonomy has no code for it.
MAX_METADATA_VALUE_CHARS = 4096


def forbidden_metadata_present(
    metadata: Mapping[str, str], *, additional: Iterable[str] = ()
) -> tuple[str, ...]:
    """Which forbidden keys this result carries, sorted.

    Args:
        additional: Keys this particular algorithm also forbids. SourceAFIS
            forbids ``template`` and ``minutiae`` because it stores neither and a
            result carrying one would mean the adapter changed; another algorithm
            may legitimately record both.
    """
    forbidden = FORBIDDEN_METADATA_KEYS | {str(key) for key in additional}
    return tuple(sorted(forbidden & set(metadata)))
