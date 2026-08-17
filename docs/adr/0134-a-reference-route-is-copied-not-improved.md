# 0134 — A reference route is copied, not improved

**Status:** Accepted
**Stage:** 18A
**Date:** 2026-08-17

## Context

Stage 18A runs the 6,000-comparison manifest through `SecuGen → OpenAFIS` to
learn how OpenAFIS behaves when its minutiae come from an extractor its own
author demonstrated it against, before Stage 19A replaces that extractor with
MINDTCT.

The route is fixed by `data/extract.py` in the pinned OpenAFIS tree, and two of
its steps are visibly wrong for our data:

1. It resizes every input to **300×400 without preserving the aspect ratio**,
   because `SG_DEV_FDU05` (the SecuGen HU20) is a 300×400 sensor. fpbench's
   canonical images are 500 ppi at their native dimensions — 381×891 for a plain
   impression, larger and differently shaped for a rolled one.
2. It declares **every** impression `LIVE_SCAN_PLAIN`, including rolled ones.

Both are straightforward to "fix", and fixing either would plausibly have
produced better-looking numbers.

## Decision

Neither is fixed. The route is transcribed as upstream wrote it, and the
distortion is carried into the run.

Deviations are permitted only where the machine leaves no alternative — a DLL
search path, a batch wrapper, an API that the current SDK has withdrawn — and
each one is recorded in `route-contract.json` with the return code that forced
it. Nothing that could move a score is changed: not the resize, not the
resampling filter, not the template format, not the minutiae, and not OpenAFIS's
matching parameters.

## Consequences

The run completed with 3,000/3,000 templates and 6,000/6,000 scored comparisons,
and it produced a result that is degenerate exactly where it matters: the SELF
populations sit at a median of 100 while `plain_roll_mated` sits at a median of 0
with a maximum of 7, barely above `plain_roll_non_mated`'s maximum of 3.

That is the decision working, not failing. Had the resize been "corrected", the
stage would have reported on a SecuGen pipeline fpbench invented, and the
comparison to Stage 19A would have been against a route with no author. Instead
the stage reports a fact about the published route: **it does not survive
non-square canonical fingerprint images**, because plain and rolled impressions
have different native aspect ratios and the fixed 300×400 squeeze therefore
distorts them differently. Two impressions of one finger stop resembling each
other; an image still resembles itself, which is why SELF is unaffected.

OpenAFIS is exonerated by the same evidence: on upstream's own FVC templates the
identical build scores 72 between two impressions of one finger, and 0 between
different fingers.

This is also why the stage publishes `publication_eligible = false` and why
section 17's prohibition matters. The numbers describe a transform, not an
algorithm, and Stage 19A must be derived from the MINDTCT and OpenAFIS
specifications rather than tuned until it resembles them.

## Related

- `docs/adr/0132` — the route is settled by authority, not by experiment.
- `evidence/stage18a-secugen-openafis-reference/route-contract.json` — the four
  recorded deviations and the 179-of-180-byte corroboration against upstream's
  own shipped template.
