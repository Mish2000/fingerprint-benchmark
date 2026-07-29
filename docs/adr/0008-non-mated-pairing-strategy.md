# 0008 — Impostor pairs shift the finger within a subject

## Status

Accepted. Implemented in `fpbench.protocols.pair_generation` and configured in
`configs/protocols/sd300_50_subjects.yaml`.

## Context

The protocol specifies the impostor stage as *"finger 1 in plain against finger
2 in roll, constructed so that only wrong pairs are produced"*, with an optimal
expectation of 0% false matches.

That description fixes the intent — guaranteed non-mated pairs — but leaves one
question open: are the two sides taken from the **same subject** or from
**different subjects**? Both readings produce guaranteed impostors, and they
measure different things.

The stated pair count (500 per release, matching the 500 plain images) also
implies one impostor pair per plain image, which rules out an all-against-all
construction.

## Decision

Plain finger *i* is compared against rolled finger *i + 1* of the **same
subject**, wrapping from 10 back to 1. One pair per plain image: 500 per
release.

This stage is reported as a **deterministic same-subject, different-finger
negative sanity test**. It is not presented as a general FMR estimate.

The shift is configurable (`pairs.plain_roll_non_mated.finger_shift`) and a
shift that is a multiple of ten is rejected outright, since it would silently
regenerate mated pairs.

## Alternatives

**Different subjects.** A conventional construction for estimating FMR.
Rejected for this stage because it answers a different question and is not the
selected deterministic reading of "finger 1 against finger 2".

**All non-mated combinations.** 500 x 499 comparisons per release. Statistically
much stronger and the right basis for a real FMR estimate, but it contradicts
the stated 500-pair result format and costs three orders of magnitude more
compute.

## Consequences

* The result must be described as "same-subject, different-finger negative
  sanity test", not as a general FMR.
* 500 impostor pairs is far too few to estimate a low FMR with any precision.
  If a genuine FMR figure is needed later, an additional cross-subject stage
  should be added; it costs nothing to generate and reuses the same manifest
  machinery.
* A future cross-subject stage remains possible without changing this decision;
  it would be a distinct protocol stage with distinct interpretation.
