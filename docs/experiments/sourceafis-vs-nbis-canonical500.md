# SourceAFIS and NBIS on the canonical 500 ppi inputs

The last gate of stage 7D: two algorithms, the same 6,000 comparisons, the same
3,000 prepared images, two independently documented operating points, and a long
list of things the result does not establish.

```bash
python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 prepare
python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 derive
python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 status
python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 finalize
python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 show
```

## The one sentence that governs everything else

> This comparison uses independently documented, uncalibrated operating points on
> identical inputs. It records paired observed outcomes. It does not establish
> equal FMR, general algorithm superiority, causality, or statistical
> significance.

It is printed verbatim in the receipt and twice in the report, and it is inside
the comparison policy fingerprint — so a document that dropped it does not
fingerprint to the policy it claims to follow.

## Why SourceAFIS uses `>= 40`

SourceAFIS's own documentation states a match at a score of at least 40, with an
approximate false-match rate of upstream's own measuring on upstream's own data.
Stage 5A applied it to the native run; stage 6B transferred it unchanged to the
canonical inputs so that the only variable between those two runs was image
preparation. It has not moved since, and stage 7D may not move it: the profile
`sourceafis_java_3_18_1_documented_40_canonical500_v1` is frozen and
`decisionset_df0d584bdede` remains the official SourceAFIS side.

## Why NBIS uses `> 40`

NIST's NBIS guide describes a BOZORTH3 score greater than 40 as a rule of thumb
that usually indicates a true match. The comparator is strict because the source
sentence is strict. See
[the NBIS decisions note](nbis-canonical500-decisions.md) and
[ADR 0057](../adr/0057-nbis-uses-nist-documented-score-greater-than-40.md).

## Why 40 and 40 are not an equivalent operating point

The digits agree; nothing else does. Two matchers, two minutiae
representations, two scoring functions, two score scales, two documents, and no
measurement anywhere establishing that the two thresholds sit at the same error
rate.

Worse, the two sentences are not even the same *kind* of statement. SourceAFIS
publishes an operating point with an approximate error rate beside it. NIST
publishes a rule of thumb. The NBIS profile records
`source_statement_kind: rule_of_thumb` inside its own fingerprint for exactly
this reason.

So the comparison is named for what it is:

```text
comparison_at_independently_documented_operating_points
```

and never `comparison_at_equal_fmr`, `comparison_at_equivalent_threshold` or
`comparison_at_matched_security_level`. `operating_points_equated` is a field of
the fairness audit and must be false for the gate to open
([ADR 0058](../adr/0058-cross-algorithm-operating-points-are-not-equated.md)).

## Why nothing was calibrated

SD300 is the test cohort these results are reported over. Choosing either
threshold from it would be the one form of leakage that invalidates the whole
study. Choosing one from a development cohort is correct and needs a development
cohort, a calibration manifest and a procedure — none of which exists.

A future stage that calibrated both algorithms to a common FMR on an independent
development cohort would answer a different question under a new protocol id. It
would not supersede this comparison.

## What makes the two sides comparable at all

Before a single paired row is built, `FairComparabilityAudit` checks six
equalities and five negatives:

| must be true | must be false |
|---|---|
| `pair_ids_equal` | `left_calibrated` |
| `pair_semantics_equal` | `right_calibrated` |
| `prepared_entries_equal` | `test_cohort_used` |
| `eligibility_policy_equal` | `operating_points_equated` |
| `metric_policy_equal` | `raw_scores_compared` |
| `execution_profile_equal` | |

The first three come from stage 7C's alignment report, **re-derived from the
manifests** rather than read back, and required to fingerprint to
`d25b5215…` — the value the frozen protocol names. No second alignment is built
in parallel: the interesting failure is precisely the one where two answers to
"were these the same inputs?" differ, and it would be invisible if the comparison
computed its own ([ADR 0054](../adr/0054-stage-7c-alignment-is-completion-authority.md)).

Any failure and nothing is published.

## Why the full population is the primary analysis

Four mated populations exist once both chains are finished, and only one of them
is identical for the two algorithms by construction:

* **all 1,500 mated attempts** — same denominator, both sides, nothing filtered;
* the attempts each side could decide — differs whenever one side fails and the
  other does not;
* each side's own SELF-eligible subset — each algorithm's own selection;
* the intersection of the two eligible subsets — removes the fingers that were
  hard for *either* algorithm.

The primary operational metric is therefore

```text
plain_roll_mated_unconditional_non_success_rate_attempt
```

over all 1,500, with `NON_MATCH` and `UNDECIDABLE` both counted as
non-successes. It is deliberately not called an FNMR: an FNMR has a decided
denominator and this one does not
([ADR 0059](../adr/0059-unconditional-attempt-population-is-primary.md)).

`plain_roll_mated_unconditional_fnmr_decided` is shown for both algorithms too,
and its difference is stored only when both sides decided the same attempts.
Otherwise the observation carries `different_decided_populations` and no
difference at all — the report says so in the cell rather than leaving it blank.

## Why common eligible is secondary

`common eligible` is the intersection of the two eligible sets, derived by
`eligibility_unit_id` rather than by position. It answers a real and narrower
question:

> When both algorithms have shown that a finger's plain and rolled impressions
> match themselves, how did the plain-to-rolled decisions differ?

It is a *controlled* analysis, and controlling for that filters out exactly the
units that were hard for either algorithm — which flatters both, and flatters the
worse one more. Its denominator is identical on both sides, so its rates do
subtract; it is reported after the full population, labelled as secondary.

## Why differing conditional sets are not subtracted

Each algorithm's conditional rates are computed over its own SELF-eligible set.
When the two sets differ, the difference of the two rates is the sum of the
effect and the change in who was counted, and there is no way to separate them
afterwards.

So the model has nowhere to put such a number. An observation whose population is
`different_eligible_populations` carries no difference at all, and the model
raises rather than storing one ([ADR 0038](../adr/0038-conditional-rates-over-different-populations-are-not-subtracted.md)).
The two rates are shown side by side, with full numerators and denominators, and
the cell that would hold a difference says why it does not.

## Why the negative sanity set is not an FMR

Same 1,500 same-subject, different-finger pairs on both sides, from one fixed
cyclic pairing. It is structurally shaped like a false-match-rate calculation,
which is exactly why the refusal to call it one is a machine-checked flag in the
metric policy and in the comparison policy rather than a sentence in a document.

An observed match-rate difference over it is computed — the denominator is
identical on both sides — and is labelled, in the table itself, as not an FMR,
not a false-match-rate estimate and not a statement about impostor population
performance.

## Why raw scores are not compared

A BOZORTH3 score of 41 and a SourceAFIS score of 41 are two numbers on two
scales. Their difference has no unit, their ratio has no meaning, and their rank
correlation would measure the agreement of two orderings whose ties and ranges
are incomparable.

`fpbench.cross_algorithm` therefore has no score field, imports no result store
and no score parser, and `require_no_score_comparison` refuses `score`,
`raw_score`, `score_delta`, `score_ratio`, `normalised_score`,
`rank_correlation` and the rest by name in any rendered document. A structural
test walks the package's syntax trees and asserts the same
([ADR 0060](../adr/0060-cross-algorithm-comparison-never-subtracts-raw-scores.md)).

The comparison is a table of paired **decisions**, not of paired numbers.

## What the report contains

In this order, and the order is the population hierarchy:

**A. Full mated population** — all 1,500 attempts. The primary analysis.
**B. Eligibility and exclusions** — 1,500 units, the full 3×3 transition matrix.
**C. Common eligible** — the intersection, explicitly secondary.
**D. Each side's own conditional set** — descriptive only where they differ.

Then the SELF comparisons (PLAIN and ROLL separately, attempt and decided rates),
the negative sanity set, and the five 3×3 decision transition matrices — every
one of which carries all nine cells, including the zeros, so that an unobserved
cell is visibly zero rather than absent.

Every rate is printed as `numerator / denominator` beside its percentage. Every
difference is stored as an exact reduced fraction; the decimal is display only.

## What may and may not be said about the result

Permitted:

> At their documented, uncalibrated operating points, SourceAFIS and NBIS
> produced the following observed outcomes on the same pairs and the same
> inputs.

> NBIS's unconditional non-success rate was higher (or lower) by the observed
> amount —

but only with the numerator, the denominator, the exact difference and the two
operating points shown.

Not permitted, in any form: that one algorithm is *more accurate*, *safer*, or
*better*; that either has a lower FMR; that any difference is statistically
significant; or that the two thresholds represent the same security level.

## Evidence

```text
evidence/sourceafis-vs-nbis-canonical500/
├── README.md
├── fair-comparability-audit.json
├── <algcompare_id>.json
├── <algcompare_id>.md
└── cross-algorithm-finalization.json
```

No raw score, no raw result row, no finger identifier, no subject identifier, no
XYT, no template and no PNG.
