# SourceAFIS and NBIS on the canonical 500 ppi inputs

Two algorithms, the same 6,000 comparisons, the same 3,000 prepared images, two
independently documented operating points.

## The sentence that governs everything else

> This comparison uses independently documented, uncalibrated operating points on
> identical inputs. It records paired observed outcomes. It does not establish
> equal FMR, general algorithm superiority, causality, or statistical
> significance.

It is printed verbatim in the receipt and in the report, and it is inside the
comparison policy fingerprint — so a document that dropped it would not
fingerprint to the policy it claims to follow.

## What the two operating points are

| side | rule | source | kind of statement |
|---|---|---|---|
| SourceAFIS | `score >= 40` | the project's own documentation | operating point with an approximate FMR |
| NBIS | `score > 40` | NIST's own guide | rule of thumb |

Both are written "40". They come from two documents about two matchers on two
score scales, and **nothing establishes that they sit at the same error rate**.
Neither was calibrated; SD300 is the test cohort these results are reported over,
and choosing either threshold from it would have been leakage.

The relation is recorded, everywhere it appears, as
`independently_documented_not_equated` (docs/adr/0058).

## What makes the two sides comparable

Before a single paired row exists, a fair-comparability audit checks six
equalities and five negatives: the same pair ids in the same order, the same pair
meanings, the same prepared images, the same eligibility policy, the same metric
policy, the same execution profile — and nothing calibrated, no test cohort used
to choose anything, no operating points equated, no raw scores compared.

The first three come from stage 7C's alignment report, re-derived from the
manifests rather than read back, and required to fingerprint to the value the
frozen measurement protocol names (docs/adr/0054).

Any failure and nothing is published.

## The population hierarchy

**A. the full mated population** — all 1,500 attempts, same denominator both
sides, `NON_MATCH` and `UNDECIDABLE` both counted as non-successes. This is the
primary analysis, because it is the only mated population that is identical for
the two algorithms by construction (docs/adr/0059).

**B. eligibility and exclusions** — 1,500 units, with the full 3x3 transition
matrix.

**C. common eligible** — the intersection of the two eligible sets. A controlled
*secondary* analysis: it filters out exactly the units that were hard for either
algorithm.

**D. each side's own conditional set** — descriptive only. Where the two eligible
sets differ, the two rates are two measurements over two populations and their
difference is undefined; the table says so rather than subtracting them
(docs/adr/0038).

## What is not here

No raw score, on either side, in any form. A BOZORTH3 score and a SourceAFIS
score are numbers on two scales; their difference has no unit and their
correlation has no referent. There is no `score_delta`, no normalisation and no
rank correlation, and the package that produced this evidence has no field one
could be stored in (docs/adr/0060).

No raw result rows, no finger identifiers, no subject identifiers, no XYT, no
templates and no PNGs.

No ROC, no DET, no EER, no AUC, no bootstrap, no confidence interval and no
significance test.

The same-subject different-finger set is reported and is **not** a false-match
rate.

## Files

```text
fair-comparability-audit.json   the six equalities and five negatives, fingerprinted
<algcompare_id>.json            the receipt, definition, manifest, observations and counts
<algcompare_id>.md              the rendered report
cross-algorithm-finalization.json  the last-written marker
```

The full method note is in `docs/experiments/sourceafis-vs-nbis-canonical500.md`.
