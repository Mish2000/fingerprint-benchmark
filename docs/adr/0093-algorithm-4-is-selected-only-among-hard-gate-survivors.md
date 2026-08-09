# 0093 — Algorithm 4 is selected only among hard-gate survivors, and never on reported performance

*Status: Accepted — 2026-08-09, stage 10A*

## Context

Selection between candidates invites a scorecard. It is the natural shape:
several criteria, a weight each, a total, a winner. It reads as rigorous, it
produces an answer every time, and it is exactly wrong for this problem.

A scorecard makes gates commensurable. It allows:

```text
candidate A = 82
candidate B = 76
→ A wins
```

while A's artifact provenance is unresolved. The 82 absorbs the blocker into a
number, and the blocker then travels as six points of deduction rather than as
the reason nothing should have been selected. Stage 9A's FLARE reading is the
concrete instance: FLARE would have scored well on method quality, diversity and
recency while its checkpoints had Drive links instead of digests.

The second temptation is reported accuracy. Both candidates' papers report
strong numbers. They are not comparable: different datasets, different
protocols, different partial-fingerprint regimes, different impostor
constructions. Comparing them compares two experiments, not two candidates — and
fpbench has no evaluation of its own to settle the difference, by design, because
reading SD300 to choose a candidate would make the benchmark part of the
selection.

## Decision

**Selection happens only among candidates that passed every hard gate.** A
candidate that failed one is not ranked, not scored and not compared. There is
no path by which a failing candidate becomes a selection.

```text
one survivor      →  that candidate is selected
no survivors      →  ALGORITHM4_PREFLIGHT_NO_SURVIVOR, and a candidate search opens
two survivors     →  the tie-break, in order
```

**The tie-break is ordered, not weighted.** Criteria are applied in sequence and
the first that discriminates decides:

```text
1  closer fit to the canonical_500 full-fingerprint benchmark
2  cleaner executable provenance
3  fewer inference-time external components
4  methodological diversity against SourceAFIS, NBIS and flx
5  runtime practicality
6  learning value
```

**Reported performance is not among them and is not read.** Author-reported
accuracy may be kept as background in a candidate's paper record. It never
enters the comparison, and the marker asserts as much:

```text
selection_based_on_reported_performance: false
reported_performance_read: false
```

**No gate is weakened to produce a selection.** `NO_SURVIVOR` is a complete
result. The response to it is a third candidate, not a lower bar.

**The tie-break has no comparator.** Stage 10A froze the criteria and wrote no
code to apply them, because no candidate survived and implementing a comparator
against a case that did not arise would mean implementing it against a guess.
Two survivors raises rather than silently picking: it is a decision a person
makes, on evidence, not a computation.

## Alternatives

**Weighted scorecard.** Rejected above.

**Rank the failures anyway, "for information".** Rejected: a published ranking
is read as a recommendation, and the two candidates here failed at different
gates for unrelated reasons, so a ranking between them would carry no meaning at
all.

**Let reported EER break ties.** Rejected: it is the single most persuasive
number available and the least comparable one.

**Implement the tie-break comparator now, for completeness.** Rejected: it would
be written against imagined candidates, and the first real pair of survivors
would fit it badly. Freezing the criteria costs nothing and commits the ordering;
writing the comparator early commits the interpretation.

## Consequences

Stage 10A ends with an empty Algorithm 4 slot and an open candidate search. The
project has three executed algorithms and keeps them.

The next candidate search starts with a written specification of what a
candidate must satisfy, which is a better starting point than the one Stage 8A
had.

If two candidates ever survive, the stage stops and asks. That is a deliberate
gap in the automation, and it is the right place for one.
