# 0080 — Calibration selects native score boundaries, without score normalization

*Status: Accepted — 2026-08-07, stage 8D*

## Context

Three algorithms have executed the canonical 6,000 comparisons and they produce
numbers that live in unrelated spaces: a SourceAFIS score of 50, an NBIS
BOZORTH3 score of 50 and an flx similarity of 1.4 have no common unit.
docs/adr/0058 and docs/adr/0060 already forbid equating or subtracting them.

Calibration is where that principle is most tempting to break, because it is
where a single number would be most convenient. It would be easy to write a
normalizer — min-max, z-score, Platt scaling — and then talk about "the
threshold" as one quantity across the benchmark.

There is a second, quieter problem. A selector that has to place a boundary
"just above 0.4" needs a number that is not 0.4, and the obvious way to get one
is to add an epsilon. Every epsilon is a scale assumption: `0.4 + 1e-9` is a
different boundary for a matcher whose scores span `[0, 1]` than for one whose
scores span `[0, 10000]`, and on some scales it is not a different boundary at
all.

A third: a target rate of `0.001` written as a binary float is not one
thousandth. Comparing an observed count ratio against it decides borderline
candidates by the rounding of IEEE 754.

## Decision

**Each algorithm gets its own threshold, on its own scale.** The shared thing is
the *policy*, never the number:

```
same development cohort
same pair-generation rules
same target operating-point definition
same threshold-selection algorithm
```

applied independently to each algorithm's own scores. `fpbench.calibration`
contains no normalization of any kind — no min-max, no z-score, no Platt
scaling, no fusion, no cross-algorithm mapping — and there is a structural test
that says so.

**Boundaries come from the observed impostor scores, never from an epsilon and
never from the genuine population.** For each distinct score `s` that a *scored
`CROSS_SUBJECT_IMPOSTOR` comparison* produced in the development population, and
for a higher-is-better matcher, the candidate boundaries are

```
score >= s
score >  s
```

and for a lower-is-better matcher

```
score <= s
score <  s
```

Mated scores do not generate candidate boundaries, do not determine
permissiveness, and do not participate in tie-breaking. They are evaluated only
after the boundary has been selected.

That set is closed over the quantity being constrained: `>= min` admits every
impostor and `> max` admits none, so both extremes of the impostor rate are
representable without inventing a number that is not a score. A boundary *below*
the lowest impostor score is deliberately unreachable — the only motivation for
moving there is to admit more mated comparisons, which is the objective this ADR
refuses.

**A threshold is a boundary, not a number.** An operating point carries a
`threshold` *and* a `comparator`, because `>= 40` and `> 40` are different rules
that disagree about every comparison that scored exactly 40. This is the same
distinction docs/adr/0055 already forced into `DecisionProfile` schema 2, reused
rather than reinvented.

**Equal scores are decided together.** A boundary is a predicate over a score,
so two comparisons with the same score always receive the same decision. There
is no random tie-breaking and no ordering by `pair_id`: a selector that could
accept one of three identical `0.4`s would be choosing between comparisons on
the basis of nothing.

Because ties are atomic, a target rate is often unreachable exactly, and the
rule undershoots rather than overshooting. Where two boundaries produce
*literally the same set of decisions*, the canonical one is chosen — inclusive
comparator first, then Decimal ordering of the threshold — so that identity is
stable without any decision changing.

**Rates are exact integers.** A target is stored as a numerator and a
denominator, never as a float, and every comparison is a cross-multiplication:

```
a/b <= c/d      is evaluated as      a*d <= c*b
```

**The objective is fixed in advance.** The selection rule is
"the most permissive boundary whose observed impostor match rate does not exceed
the target", where *permissive* counts admitted impostor evidence and nothing
else. Genuine performance at that boundary is measured and recorded; it is never
a second objective, and there is no search over rules to find the one with the
best FNMR. A selector that optimised two things would be fitting the development
set rather than applying a policy to it.

Restricting the candidates and the ordering to the impostor population is what
makes that statement true rather than merely intended. It was not true in the
first implementation: candidates were drawn from every observed score, so over
impostors `1, 2, 3, 4` under a ceiling of one in four, mated scores of `5, 6, 7`
selected `>= 4` while mated scores of `2.5, 3.5, 100` selected `>= 3.5`. Same
impostor evidence, two thresholds, and the second one a number no impostor
comparison ever produced. The genuine population had chosen the boundary through
the permissiveness ordering, which is precisely the optimisation this decision
forbids.

## Alternatives considered

**Normalize scores to a common scale and calibrate once.** Produces one number
that appears to mean something for every algorithm. Every normalizer requires
distributional assumptions about matchers this project has deliberately treated
as black boxes, and the resulting "shared threshold" would be an artefact of the
normalizer.

**Add an epsilon to reach a strict boundary.** Scale-dependent, and it puts a
number in an operating point that no comparison ever produced.

**Break ties by `pair_id`, or at random with a fixed seed.** Reaches the target
rate exactly. It decides identical evidence differently, which is not a
threshold.

**Search rules and keep the best FNMR.** The standard way to overfit a
development set. The rule is fixed first and the genuine performance is a
consequence.

**Store the target as a `Decimal` string rather than a rational.** Better than a
float, and still wrong for a target like one in three thousand. A rational is
exact for every target anyone would write.

## Consequences

Operating points are algorithm-scoped by construction. There is no artifact in
which two algorithms' thresholds are commensurable, so the comparison
docs/adr/0058 forbids has nowhere to be expressed.

An observed rate will usually sit strictly below the target, and the operating
point records both the target and the observed counts so the gap is visible
rather than implied.

A target rate is bounded by `[0, 1]`. `0/1` and `1/1` are both meaningful — admit
no impostor, admit every impostor — and anything above 1 is refused, because it
constrains nothing: every boundary satisfies it, so a protocol carrying it would
report a selection nobody constrained.

Achieving a specific FMR *exactly* is not possible in general and is not
attempted. A future protocol that needs a different objective — a nearest-rate
rule, an equal-error rule — is a new `CalibrationProtocol` with its own
`threshold_selection_rule`, not a change to this one.
