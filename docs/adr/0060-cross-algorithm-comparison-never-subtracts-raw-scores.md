# 0060 — A cross-algorithm comparison never touches raw scores

*Status: Accepted — 2026-08-04, stage 7D*

## Context

Stage 6B built `fpbench.paired` to compare two runs of the *same* algorithm under
two image preparations. There, a score delta is a meaningful quantity, the SD300A
control set of exactly-equal scores is the central argument, and `ScoreRelation`
answers a question worth asking.

None of that survives the move to two algorithms. A BOZORTH3 score of 41 and a
SourceAFIS score of 41 are two numbers on two scales produced by two matchers.
Their difference has no unit, their ratio has no meaning, their rank correlation
would measure the agreement of two orderings whose ties and ranges are
incomparable, and any normalisation would require a mapping between the scales
that nobody has estimated.

Reusing `PairedComparisonRecord` would have inherited four assumptions that are
all false here: one algorithm, one threshold, a single image-preparation
variable, and a control set of identical scores.

## Decision

`fpbench.cross_algorithm` is a separate package with separate models, and
`PairedComparisonRecord`, `NativeCanonicalControlAudit` and the
`sourceafis_native_vs_canonical500` schema are not used by it.

`CrossAlgorithmComparisonRecord` carries five hashes and two outcomes: which
stored decision and which stored raw result each side's outcome came from, and
the outcomes themselves. It has no score field, and `require_no_score_comparison`
walks any rendered cross-algorithm document and refuses `score`, `raw_score`,
`left_score`, `right_score`, `score_delta`, `score_ratio`, `normalised_score`,
`rank_correlation` and the rest by name.

`FairComparabilityAudit.raw_scores_compared` must be false for the gate to be
clean, and the comparison policy's `scores` section refuses `compare_raw`,
`normalise`, `subtract` and `correlate`.

The package imports `core` and nothing else from the project. A structural test
walks its syntax trees and asserts that it imports no adapter, no result store
and no score parser.

## Consequences

The comparison is a table of paired *decisions*, not of paired numbers. Two
algorithms that disagreed about one pair are recorded as having disagreed; how
far apart their scores were is not recorded, because the distance is not defined.

A future stage that wanted a score-level analysis would need a documented mapping
between the two scales, and would need to justify it before computing anything —
which is exactly the discussion this ADR forces into the open rather than into a
column.
