# A native transformed score is a raw score

## Status

Accepted, implemented.

## Context

This project's score contract has been simple so far because its algorithms were
simple about it. SourceAFIS returns a similarity, NBIS returns a match count, and
"raw" plainly meant "the number the algorithm returned, before any threshold".

VeriFinger's number is not that shape. Its manual defines the matching score by
its correspondence with a claimed false acceptance rate, publishes the table —
0 at 100%, 12 at 10%, 24 at 1%, 48 at 0.01%, 96 at 0.000001% — and gives the
formula `score = -12 * log10(FAR)`. The number is a similarity, higher meaning
more similar, and it is also a calibrated quantity on a scale the vendor chose.

That raises a question worth answering explicitly rather than by reflex: is a
score that already encodes a claimed error rate a *raw* score, or has something
been applied to it that this project's contract forbids?

## Decision

It is a raw score, and the test is authorship rather than shape.

A score is raw when it is the number upstream's own API returns for one 1:1
attempt. What it is a function of — a distance, a count, a claimed FAR, a
log-FAR, a normalised similarity — is upstream's business and part of the
algorithm's identity. What is forbidden is fpbench computing a different number
from it: no conversion to FAR, no inversion of the vendor's formula, no
rescaling, in either direction.

Two things stay exactly as strict as before.

**No threshold inside the number.** Where an API offers both a score and a
decision, the raw route takes the score and stops. VeriFinger passes this
cleanly: the threshold is a separate settable engine property, and upstream's own
tutorial reads the integer score under `MATCH_NOT_FOUND` as well as under `OK` —
the score survives a negative decision rather than being replaced by one. An API
whose only output is a boolean fails outright.

**No vendor threshold constant enters this stage.** The tutorial's `48` is a
recommended operating point. It is a fact about the vendor's advice and belongs
to a calibration stage or to nothing; it is not part of the raw route and no
document here treats it as one.

The route status records which of these two cases holds — `NATIVE_SCALAR` or
`NATIVE_TRANSFORMED_SCALAR` — so a reader can tell a plain similarity from a
calibrated one without reading prose.

## Alternatives

**Refuse transformed scores.** Would exclude a large class of commercial matchers
for a reason that has nothing to do with reproducibility: a deterministic
function of a similarity is exactly as reproducible as the similarity.

**Convert the score back to a comparable quantity.** This is the failure mode.
Inverting the vendor's formula would produce a number no upstream API ever
returned, published under the vendor's name, and every later result would rest on
this project's arithmetic rather than on the algorithm.

**Treat the published FAR table as a calibration and use it.** Same failure,
dressed as rigour. The table is recorded as upstream's own correspondence and is
used for nothing.

## Consequences

VeriFinger's raw-score gate — the one the specification calls decisive — passes
on artifact evidence, and the answer does not depend on running anything.

Cross-algorithm comparison gets harder in a way that was already true and is now
visible: a VeriFinger score of 48 and a SourceAFIS score of 48 are not the same
event. ADR 0058 already refuses to equate operating points across algorithms, and
this is another reason it was right to.
