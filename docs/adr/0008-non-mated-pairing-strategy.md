# 0008 — Impostor pairs shift the finger within a subject

## Status

**Proposed — needs review before results are reported.**

Implemented as the configured default in
`configs/protocols/sd300_50_subjects.yaml`, because the pipeline cannot
generate the fourth stage without *some* rule. The rule is easy to change: it
is one config value.

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

The shift is configurable (`pairs.plain_roll_non_mated.finger_shift`) and a
shift that is a multiple of ten is rejected outright, since it would silently
regenerate mated pairs.

## Alternatives

**Different subjects.** The conventional impostor construction, and the one a
published FMR figure usually refers to. Rejected as the default because two
fingers of the same person are the *harder* impostor case — shared skin
characteristics, the same card, the same scan session, the same ink — so a
cross-subject FMR would look better than reality for the same matcher. It is
also a less natural reading of "finger 1 against finger 2".

**All non-mated combinations.** 500 x 499 comparisons per release. Statistically
much stronger and the right basis for a real FMR estimate, but it contradicts
the stated 500-pair result format and costs three orders of magnitude more
compute.

## Consequences

* The reported false match count is a **conservative** figure. It should be
  described as "same-subject, different-finger impostor pairs", not as a
  general FMR, and a report that omits that qualifier is misleading.
* 500 impostor pairs is far too few to estimate a low FMR with any precision.
  If a genuine FMR figure is needed later, an additional cross-subject stage
  should be added; it costs nothing to generate and reuses the same manifest
  machinery.
* If review concludes the cross-subject reading was intended, only
  `pair_generation.py` gains a second strategy and the config selects it; no
  other module is affected.

## Open question for the supervisor

Should the impostor stage pair different fingers of the same subject (current
default), different subjects, or both as separate stages?
