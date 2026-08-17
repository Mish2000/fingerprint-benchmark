# 0135 — The MINDTCT→OpenAFIS translation is settled from source, not from scores

**Status:** Accepted
**Stage:** 19A
**Date:** 2026-08-17

## Context

Algorithm 5 is `MINDTCT → OpenAFIS`. Both halves already existed: MINDTCT is
Algorithm 2's certified extractor, and the OpenAFIS raw 1:1 bridge was built and
proved in Stage 18A. What did not exist was the join, and a minutia has to cross
it:

```text
MINDTCT XYT       x, y, theta (degrees), quality
OpenAFIS CSV      type, x, y, angle (radians), against a width,height header
```

Four fields had to be decided, and every one of them could have been decided by
trying a few options and keeping whichever produced better-looking scores. Stage
18A had just produced a private SecuGen reference, which made that temptation
concrete: a correlation to aim at.

## Decision

Each rule is derived from an upstream source and recorded with it. None is chosen
by experiment, and the marker publishes
`secugen_reference_used_for_parameter_selection: false`.

**Angle.** NBIS `mindtct/src/lib/mindtct/xytreps.c` documents what MINDTCT writes
without `-m1`, and `results.c` confirms that is the default: *pixel coordinates
with origin bottom-left; orientation in degrees on range [0..360] with 0 pointing
east and increasing counter clockwise*. OpenAFIS `lib/TripletScalar.cpp` relates a
minutia's angle to its geometry with `rotateAngle(minutia.angle(), atan2(dy, dx))`
over the *stored* coordinates, so it requires the angle to be counter-clockwise
from +x in the same plane as the stored y. MINDTCT's representation already is.
Therefore `radians = degrees × π / 180`, with **no inversion and no rotation**.

That reading was verified before it was trusted: decoding one of OpenAFIS's own
ISO templates the way its ISO parser does — including its `360 − angle` step — and
re-emitting it through this CSV path reproduces the ISO route's score exactly on
twelve pairs. A misread convention would have disagreed.

**Coordinates.** Carried over unscaled, with the prepared image's real dimensions
in the header, because `MinutiaPoint` normalises by `256/width` and `256/height`
itself. Normalising here would apply it twice.

**Type.** XYT carries none and OpenAFIS's CSV requires one. `MinutiaPoint` is
built from x, y and angle only and the triplets are built from `MinutiaPoint`, so
the type never reaches the similarity computation. A constant `RidgeEnding` is
used, and the invariance is proved by scoring the same minutiae twice — all
`RidgeEnding`, then all `RidgeBifurcation` — and requiring the identical result.

**Quality.** Dropped. OpenAFIS has nowhere to put it, and using it to filter would
be a minutiae-selection rule fpbench invented.

**Order.** MINDTCT's own, with no sort, no ranking and no deduplication.

## The consequence, and why it is not worked around

OpenAFIS declares `MinimumMinutiae = 2` and `MaximumMinutiae = 128` in
`lib/Template.h` and `Template::load` refuses anything outside them. MINDTCT on
canonical 500 ppi SD300 finds a median of **69** minutiae in a plain impression
and a median of **205** in a rolled one.

Measured over all 3,000 prepared images: **1,558 exceed 128** — 8.7% of plain
impressions and **95.1% of rolled ones**.

The obvious repair is to keep the best 128 by quality. It is refused. Choosing
which minutiae survive is a selection rule neither upstream project publishes, and
the resulting score would be fpbench's rather than what MINDTCT and OpenAFIS
produce between them. A template outside the bounds is recorded as
`OPENAFIS_TEMPLATE_FAILED_<side>` with reason `minutiae_above_upstream_maximum`,
and the comparison keeps its row.

That failure is classified as **algorithmic, not blocking**: a real limit of a real
matcher meeting a real property of real rolled fingerprints is data about the
composition, not a defect in the harness.

## Consequences

Algorithm 5 shares its extractor with Algorithm 2 and differs only in the matcher.
That makes the pair a controlled matcher comparison — the same minutiae into
BOZORTH3 and into OpenAFIS — which is worth having and must be stated, because it
also means Algorithm 5 is not an independent fifth system.

It also means the composition's reach is bounded by the 128 ceiling, and the
bound falls hardest exactly where cross-impression matching lives. What that does
to the 6,000 is reported by the run, not predicted here.

## Related

- `docs/adr/0134` — a reference route is copied, not improved (Stage 18A).
- `docs/adr/0049` — the options this route does not pass are part of its identity.
- `configs/algorithms/nbis_mindtct_openafis_v1.yaml` — the four rules as config.
