# Stage 19B — OpenAFIS capacity extension

**Outcome: `MINDTCT_OPENAFIS_CAPACITY_EXTENDED_CANONICAL_RAW_COMPLETE`.**
6,000 expected, 6,000 stored, 0 missing, **0 failures of any kind**.

**Algorithm 5 established: true**, against the six structural conditions of the
requirement — not against any accuracy threshold, because none was asked for.

## The hypothesis, and the answer

> Can `MINDTCT → OpenAFIS` become usable if we remove *only* OpenAFIS's refusal of
> templates above 128 minutiae, changing neither the matching algorithm, nor
> MINDTCT, nor the translation?

Yes, for coverage. Stage 19A scored 1,583 of 6,000; this stage scores all 6,000.

| population | 19A scored | 19B scored | median | max | zeros |
|---|---|---|---|---|---|
| plain_self | 1369 | **1500** | 100 | 110 | 0 |
| roll_self | 73 | **1500** | 98 | 108 | 0 |
| plain_roll_mated | 73 | **1500** | 0 | 10 | 1293 |
| plain_roll_non_mated | 68 | **1500** | 0 | 1 | 1459 |
| **all** | **1583** | **6000** | 44 | 110 | 2752 |

4,417 comparisons newly admitted, 0 lost, and `minutiae_above_upstream_maximum`
is now **0**.

## The change

Two lines, one file, and the constant itself untouched:

```c
+#ifndef FPBENCH_STAGE19B_ALLOW_ABOVE_MAXIMUM_MINUTIAE
     if (minutiae.size() > MaximumMinutiae) {
         Log::error("minutiea count > MaximumMinutiae");
         return false;
     }
+#endif
```

`MaximumMinutiae` is **not** raised to 256 or 512. Auditing every use of it found
four: the refusal above, a `std::vector` capacity hint that grows dynamically, and
two ISO-only sites (`reserve` and `MaximumLength`). The CSV reader loads all its
minutiae before `Template::load` is reached, which is what makes this the clean
experiment and leaves the ISO route untouched. `MinimumMinutiae = 2` still refuses.

`Match::compute` never sees the constant; it receives a `Fingerprint` that is
already built. No matching parameter, triplet rule, Delaunay step or score formula
was altered.

## Gate A — the inertness proof, and its limit

The 1,583 comparisons the **unmodified** build already scored were rerun against
the patched build:

```text
baseline scored pairs   1583
exact score matches     1583
score mismatches           0
status regressions         0
reproduction mismatches    0
```

To attribute any difference correctly the templates were extracted **once** and
both binaries were run over the *same* CSV files, so MINDTCT could not contribute
a spurious mismatch. The zero reproduction mismatches additionally show MINDTCT is
deterministic over these images.

**What this does not prove:** that behaviour *above* 128 minutiae is
upstream-validated. It cannot — upstream refuses that region, so there is no
upstream behaviour to agree with. Gate A shows only that the change is inert where
upstream already worked.

### The second half of the same claim

Disabling the C++ refusal was only half the change. fpbench's own translator
enforced the same 128 ceiling, so the patched build would never have been asked
the question — the first attempt at this run produced 239 capacity failures that
were *ours*, not OpenAFIS's. Because `translation.py` is pinned byte-for-byte by
Stage 19A's marker, the fix is an uncapped sibling in the variant module, and it
is proved **byte-identical to the original for all 127 minutiae counts the
original accepts** (`gate-a-inertness.json`). Together the two proofs carry Gate
A's conclusion through the adapter as well as the bridge.

## Determinism

30 pairs frozen by rule before running — 10 SELF, 10 mated, 10 non-mated — and
**all 30 chosen with at least one side above 128 minutiae**, because those are the
comparisons the extension admits and therefore the ones whose repeatability is
actually in question. Two full passes each, extraction included: **30/30 identical
status and score.**

## What the numbers say, and what they do not

Coverage is solved. Discrimination is weak and must be reported as such:
`plain_roll_mated` has a median of 0 and a maximum of 10, against
`plain_roll_non_mated`'s maximum of 1. There is separation — 207 mated
cross-impression pairs carry a non-zero score against 41 non-mated — but it is
small. Per section 17 that is a result of the method and not a reason to withhold
the identity; there is no minimum-score, minimum-median or TAR condition.

The SELF populations behave: `plain_self` median 100, `roll_self` median 98.

### The controlled matcher comparison

Algorithms 2 and 5 run the same MINDTCT binary from the same certified build
(`658f9f54a8f2`) over the same images. They differ only in the matcher.

| | score-bearing | Spearman vs Algorithm 2 |
|---|---|---|
| MINDTCT → BOZORTH3 | 6000 / 6000 | — |
| MINDTCT → OpenAFIS (19A) | 1583 / 6000 | 0.264, over a self-selected subset |
| MINDTCT → OpenAFIS capacity-extended | **6000 / 6000** | **0.787, over all 6,000** |

The correlation is now measured over the whole manifest rather than over the
pairs that happened to fit, which is the more meaningful comparison and part of
why the extension was worth testing.

**Neither matcher is called better.** The scales are unrelated, no common
operating point exists, and no threshold is applied anywhere. That waits for
calibration.

## The `uint8_t` audit the requirement withdrew

Section 12 withdrew an overflow check, reasoning that `matched` cannot exceed the
minutiae count and so the score cannot exceed 100. **Stage 19A observed 109 and
this stage observes 110**, so the premise does not hold: the formula is an
unclamped integer ratio and `matched` counts triplet-derived pairs.

The gate stays withdrawn as instructed, and the headroom is measured instead of
assumed. Over all 6,000 scored pairs: maximum 110, headroom to a wrap 146, 390
scores above 100, largest implied `matched` at 1.049× the smaller template, and
**0 pairs where a single wrap is even arithmetically reachable**.

## Disclosure that must travel with the number

> NBIS MINDTCT + OpenAFIS (capacity-extended variant) — composition defined by the
> project. It shares the MINDTCT extractor with the NBIS/BOZORTH3 method and
> differs primarily in the matcher. The OpenAFIS source was minimally modified to
> permit CSV templates containing more than the upstream limit of 128 minutiae;
> the original behavior was verified unchanged on all 1,583 previously accepted
> comparisons.

This is more important than the label "Algorithm 5". The marker carries it as a
field so it cannot be dropped when the table is assembled.

## Timings

Median 200.3 ms per comparison, against 148.9 ms in Stage 19A — the cost of
triangulating and matching templates that now carry up to 373 minutiae rather than
at most 128. MINDTCT 68.8 ms (left) and 118.5 ms (right); OpenAFIS matching
0.283 ms.

## Files

| File | What it holds |
|------|---------------|
| `variant-identity.json` | the new identity, the modification, and the field-by-field proof that nothing score-affecting differs from the base route |
| `patch-provenance.json` | base commit, the exact diff, patched source and compiled bridge digests, compiler and build command |
| `gate-a-inertness.json` | the 1,583-pair result and the translator inertness proof |
| `canonical-run-binding.json` | counts, coverage, distributions, both comparisons, timings, the overflow audit |
| `stage-19b-finalization.json` | the marker |

## Reproducing

```bash
make stage19b-build
make stage19b-gate-a
make stage19b-run
make stage19b-determinism
make stage19b-diagnostics
```

Gate A must pass before the run. If it had failed, no second patch would have been
attempted.
