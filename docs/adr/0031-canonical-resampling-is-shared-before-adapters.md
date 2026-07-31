# 0031 — Canonical resampling is a shared step, not an adapter's business

*Status: Accepted — 2026-07-31, stage 6A*

## Context

SD300 is delivered at three resolutions: 500 ppi (A), 1000 ppi (B) and 2000 ppi
(C). The stage 4B run compared each release at its native resolution, and
SourceAFIS did its own internal scaling on the way in.

The next question the supervisor wants answered is what happens when every
algorithm sees the *same* resolution. That means resampling, and resampling is
not one thing. Lanczos and bicubic differ. One reduction differs from two
chained reductions. Rounding half up differs from rounding half to even. Two
matchers handed images produced by two different downsamplers are not being
compared with each other; they are being compared with each other's
preprocessing.

There is an obvious place to put the resampling — inside each adapter, next to
the code that already knows what its matcher wants — and it is the wrong one.

## Decision

Canonical image transformation is an **experiment-wide imaging operation**. It
lives in `fpbench.imaging`, runs once, before any run, and produces an immutable
set of artefacts. Every algorithm evaluated under a resolution profile receives
exactly that set, identified by `preparation_set_fingerprint`.

An adapter, a bridge, a runner or a planner may not, under the same resolution
profile:

- resample an image;
- choose a different interpolation filter;
- change output dimensions;
- sharpen, denoise, normalise contrast or change polarity after the reduction;
- read the higher-resolution original and bypass the prepared set.

An adapter may perform further **technical encoding** — a matcher that cannot
read PNG needs something it can read — but only if the encoding preserves the
canonical pixel hash exactly, and only if it is documented separately as an
adapter step rather than as part of the profile.

## Consequences

The fairness claim becomes checkable rather than aspirational.
`preparation_set_fingerprint` is one value that either matches between two runs
or does not, and every stored result of a canonical run carries it along with
the entry hash of each side.

It also makes the claim falsifiable in the other direction: because the profile
insists on a single direct resampling from source to target, and because the
golden fixtures show that two chained halvings produce different pixels from one
quartering, "we resampled the same way" is a statement with content.

The cost is that a canonical run cannot start until a canonical set exists, and
the set's identity cannot be known until the last image is produced. That is why
the preparation experiment has its own four-command lifecycle, and why the
canonical run's configs are filled in after the materialisation finishes.

## Alternatives considered

**Resample inside each adapter.** Cheaper to build, and every future adapter
would quietly reintroduce the problem the moment its author picked a filter they
preferred.

**Resample in the runner.** Would put an image-processing decision in the one
component docs/adr/0007 requires to stay algorithm-agnostic, and would mean the
resampling happened once per comparison — 12,000 times for 6,000 pairs — inside
whichever algorithm's timing budget happened to be running.

**Pre-resample into a second dataset directory.** Effectively this decision
without the identity: no fingerprint, no verification, no way to prove two runs
used the same pixels.
