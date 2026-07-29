# 0003 — Thresholds are applied outside the adapter

## Status

Accepted. Partly implemented: adapters return a raw score and a score
direction, and results are stored with neither threshold nor decision.
`fpbench.decisions` and the `DecisionPolicy` that reads those scores do not
exist yet.

## Context

A matcher produces a score. Whether that score counts as a match depends on a
threshold, and the study needs at least two: the algorithm's own documented
threshold (the primary result) and a calibrated threshold (a secondary result).

If the adapter returned a boolean, changing the threshold would mean re-running
every comparison — 6,000 comparisons per algorithm, some of them slow — and the
two threshold profiles could never be compared on identical scores.

## Decision

The adapter returns a raw score and the direction that score runs in:

```
raw_score: 37.4
score_direction: higher_is_better
```

A separate `DecisionPolicy` turns that into a decision:

```
decision: non_match
threshold: 40.0
threshold_profile: native
threshold_source: official_documentation
```

Raw results and decisions are stored as two separate records. Applying a new
threshold reads the stored scores; it never re-runs the matcher.

## Alternatives

**Adapter returns a boolean.** Rejected: throws away the score, forces a
re-run per threshold, and makes ROC/DET analysis impossible.

**Adapter applies the threshold but also returns the score.** Rejected: it puts
the same value in two places with no guarantee they agree, and it invites
adapters to embed research decisions.

## Consequences

* Score normalisation is *not* required. Each algorithm keeps its own score
  space and its own threshold; normalisation is only needed if scores from
  different algorithms are ever combined.
* Threshold provenance must be recorded — a native threshold taken from
  documentation and a calibrated one derived from data are different kinds of
  claim and must not look alike in a report.
* Calibration must run on a development cohort, never on the 50 test subjects.
  `CohortRole` exists so that this can be enforced in code rather than in
  review.
