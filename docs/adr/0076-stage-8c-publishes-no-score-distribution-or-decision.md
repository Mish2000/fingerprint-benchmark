# 0076 — Stage 8C publishes no score distribution or decision

*Status: Accepted — 2026-08-05, stage 8C*

## Context

Stage 8C produces 6,000 raw flx similarity scores over the same pairs SourceAFIS
and NBIS already scored. Every interesting question about them — is the mated
distribution separated from the non-mated one, where would a threshold sit, how
does it compare with the other two algorithms — is one arithmetic step away and
none of it is licensed by anything this stage has established.

The reasons are not the same as Stage 7C's, and it is worth writing down which
ones are new.

**There is no threshold on this scale.** BOZORTH3 at least had NIST's own
documented 40. The flx score is `dot(texture) + dot(minutia)` in `[-2, 2]`, from
an author-supplied implementation of one variant, with no operating point
published by anyone (docs/adr/0065, docs/adr/0069).

**A threshold may not be chosen from these scores.** SD300 is the evaluation
set. Reading the distribution and picking the point that separates it is fitting
a parameter to the test data, and the resulting rate would be an upper bound on
nothing. Stage 8D must freeze its threshold source, comparator, boundary
semantics and calibration status in a separate, prior act.

**A distribution is a threshold in disguise.** A histogram, a percentile table,
a mean-by-pair-kind summary or a handful of example scores is enough for a
reader to choose an operating point by eye, and it would be chosen from the
evaluation set just the same. The prohibition has to cover the summary
statistics, not only the decision.

**Reading another algorithm's scores is the same act at one remove.** Correlating
flx against SourceAFIS or NBIS on these pairs is a cross-algorithm claim, and it
needs the comparability apparatus Stage 7D built and a decision profile that
does not exist for flx.

## Decision

Stage 8C reads a score for exactly five purposes and publishes none of them as a
number:

```
finite validation
range validation against [-2, 2] plus the fingerprinted float32 allowance
canonical 17-significant-digit serialization
fingerprint construction
ResultSet audit
```

It does not compute, store or publish:

```
minimum, maximum, mean, median, any percentile
histogram, distribution, score bins
per-pair score table, example scores
mated / non-mated / SELF score summaries
correlation with SourceAFIS or NBIS
threshold, decision, eligibility, any metric
```

The prohibition is enforced in three independent places, because a rule that
only exists as a sentence is a rule nobody breaks by accident and everybody
breaks eventually:

1. **The configuration loader** refuses `threshold`, `decision_profile`,
   `match_threshold`, `acceptance_threshold`, `calibration`, `eer`, `far`,
   `fmr`, `fnmr`, `roc`, `det`, `score_bins` and `score_statistics` at any depth
   of the document, with the single exception of the fixed field
   `score_statistics: false`, and requires `biometric_metrics: false` and
   `score_export: false`.

2. **An AST and runtime boundary check** proves the Stage 8C modules do not
   import `fpbench.decisions`, `fpbench.eligibility`, `fpbench.evaluation`,
   `fpbench.metrics`, `fpbench.cross_algorithm` or `fpbench.paired`, and do not
   open the SourceAFIS or NBIS result rows.

3. **Finalization refuses to complete** while any `DecisionSet`,
   `EligibilitySet`, `MetricSet`, paired evaluation or cross-algorithm
   comparison derives from the new run. The check uses the real models and
   stores, not a filename search.

The published evidence carries `permits_decisions: false` and
`opens_stage_8d: true`, and the raw ResultSet stays in the workspace.

## Alternatives considered

**Publish the distribution but no threshold.** The distribution *is* the
information a threshold is chosen from. Withholding only the last arithmetic
step is a formality.

**Publish summary statistics as "operational".** Wall-clock duration and a
failure-code histogram describe the harness. A score percentile describes the
biometric outcome. The line is where the number stops being about the run and
starts being about fingerprints.

**Publish a few example scores for sanity.** Six thousand rows summarised by the
six a human picked is the least representative possible summary, and any
selection rule is itself a claim.

**Let Stage 8C choose a threshold since nobody else will.** That is the failure
this ADR exists to prevent. Stage 8D chooses one in a separate pre-registered
act, and it may not choose it from these scores.

## Consequences

Stage 8C's headline is a count, not a rate: 6,000 stored outcomes, of which some
number are raw scores and the rest are declared algorithmic failures. A reader
who wants to know whether flx is any good has to wait for Stage 8D, and that is
the intended answer.

The evidence directory publishes seven documents and no score row. Anyone with
the workspace can compute anything they like from the raw ResultSet; what they
cannot do is cite this stage as having published it.

`operational_summary: true` is the one reporting switch that is on. It is
allowed to say how long the run took, how many workers started, how many calls
of each kind were made and which failure codes occurred, because none of those
is a fact about fingerprints.
