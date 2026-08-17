# 0136 — A modified matcher gets its own identity, and an inertness proof

**Status:** Accepted
**Stage:** 19B
**Date:** 2026-08-17

## Context

Stage 19A ran `MINDTCT → OpenAFIS` over the canonical 6,000 and scored 1,583 of
them. Every one of the 4,417 failures had the same cause: OpenAFIS declares
`MaximumMinutiae = 128` in `lib/Template.h`, `Template::load` refuses anything
above it, and MINDTCT finds a median of 205 minutiae in a rolled SD300 impression.
95.1% of rolled images did not fit.

Stage 19A refused the obvious repair — keeping the best 128 by quality — because
that is a minutiae-selection rule fpbench would have invented, and the resulting
score would have been ours rather than what MINDTCT and OpenAFIS produce
(docs/adr/0135). That refusal still stands.

Stage 19B asks a different question: what if we remove the *refusal* itself,
change nothing else, and see whether the composition becomes usable?

## Decision

**The change is two lines in one file**, guarded so the diff states its own intent:

```c
+#ifndef FPBENCH_STAGE19B_ALLOW_ABOVE_MAXIMUM_MINUTIAE
     if (minutiae.size() > MaximumMinutiae) {
         Log::error("minutiea count > MaximumMinutiae");
         return false;
     }
+#endif
```

**The constant is not changed.** `MaximumMinutiae` is not raised to 256 or 512,
because it also sizes the ISO parser's `reserve` and its `MaximumLength`, and this
stage has no business altering the ISO route. Auditing every use of the constant
found exactly four: the refusal above, a `std::vector` capacity hint that grows
dynamically, and two ISO-only sites. The CSV reader loads all its minutiae before
`Template::load` is reached, which is what makes this the clean experiment.

**`MinimumMinutiae = 2` is untouched.** Only the upper bound is removed.

**The identity changes.** A score from a build that does not behave like upstream
must not be attributed to upstream, so the route is registered separately as
`nbis_mindtct_openafis_capacity_extended`, and the descriptor itself carries
`upstream_modified`, `base_openafis_commit` and `modification` — not only a
document beside it. The variant is a *sibling module* subclassing Stage 19A's
adapter rather than an edit to it, because 19A's marker pins that file byte for
byte; `compare` is inherited unchanged, so extraction, translation, probe side,
failure vocabulary and score contract are literally the same code.

**Gate A comes before the full run.** The 1,583 comparisons the unmodified build
already scored are rerun against the patched build and must return byte-identical
scores — no tolerance, no correlation. To attribute any difference correctly, the
templates are extracted **once** and both binaries are run over the same CSV
files, so MINDTCT cannot contribute a spurious mismatch.

Result: **1583/1583 exact, 0 mismatches, 0 status regressions**, and 0
reproduction mismatches against the stored Stage 19A scores.

## Consequences

Gate A establishes something narrow and worth stating precisely: the change is
inert *in the region where upstream already worked*. It does **not** establish
that behaviour above 128 minutiae is upstream-validated, and it cannot — upstream
refuses that region, so there is no upstream behaviour to agree with. Every
document this stage publishes carries that caveat.

The disclosure the supervisor's comparison table must carry is therefore not
optional:

> NBIS MINDTCT + OpenAFIS (capacity-extended variant) — composition defined by the
> project. It shares the MINDTCT extractor with the NBIS/BOZORTH3 method and
> differs primarily in the matcher. The OpenAFIS source was minimally modified to
> permit CSV templates containing more than the upstream limit of 128 minutiae;
> the original behaviour was verified unchanged on all 1,583 previously accepted
> comparisons.

**One correction to the stage's own premise, on the record.** The requirement's
section 12 withdrew a `uint8_t` overflow check on the grounds that `matched`
cannot exceed the minutiae count on either side, so the score cannot exceed 100.
Stage 19A observed a maximum of **109**, so that reasoning does not hold: the
score formula is an unclamped integer ratio and `matched` counts compatible
minutia pairs drawn from triplets, which can exceed `sqrt(n_probe × n_candidate)`.
The gate stays withdrawn as instructed, but the risk is real above 128 minutiae
and is audited arithmetically in the diagnostics from the recorded minutiae counts
rather than assumed away.

If Stage 19B passes, Algorithm 5 is established as a project-defined variant. If
Gate A had failed, no second patch would have been attempted.

## Related

- `docs/adr/0135` — the translation is settled from source, not from scores.
- `docs/adr/0134` — a reference route is copied, not improved (Stage 18A).
