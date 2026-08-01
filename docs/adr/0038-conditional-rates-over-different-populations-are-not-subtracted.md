# 0038 — Two rates over different populations are reported, never subtracted

*Status: Accepted — 2026-08-01, stage 6B*

## Context

The conditional mated FNMR is computed over the fingers whose two SELF
comparisons both matched. Each run decides that for itself, so the two runs'
eligible sets are not the same set — a finger can be eligible natively and not
canonically, or the reverse.

Subtracting the two conditional FNMRs is arithmetically trivial and
scientifically empty. The result is the effect of the preparation path *plus* the
effect of the population having changed, and nothing in the number says which
part is which. It is also the single most natural thing for a reader to do when
the two numbers appear next to each other in a table.

The same question arises one level down. Two attempt-level rates over identical
rows are directly comparable. Two decided-level rates over identical rows are
comparable only if the two sides could decide the same subset — which is true of
this pair of runs, both being 6,000/6,000 decided, and must not be assumed in
code.

## Decision

Comparability is a **stored, enumerated property of every paired observation**,
not a convention:

```
DIRECTLY_COMPARABLE                       same attempts, same denominator
SAME_ATTEMPTS_DIFFERENT_DECIDED_SUBSETS   same attempts, decided subsets may differ
DIFFERENT_SELECTION                       different rows; no difference exists
UNDEFINED                                 one side has no denominator
```

A `PairedRateObservation` marked `DIFFERENT_SELECTION` or `UNDEFINED` **may not
carry a difference at all** — the model refuses to construct one that does. The
report prints those two rates side by side, with both denominators visible and
"not comparable" where a delta would otherwise go.

To make the fair comparison possible rather than merely to forbid the unfair one,
stage 6B derives a **common-eligible mated view**: every mated comparison, marked
with whether *both* runs found its finger eligible. The conditional rates over
that shared population have identical denominators on both sides and are
directly comparable.

Excluded rows stay in the view. A view that dropped them could not state its own
selection fraction, and a conditional result published without one is a number
with an invisible denominator (docs/adr/0029).

## Consequences

The report carries both: a `common_eligible_mated_decision_fnmr` with an exact
signed difference, and a `per_run_conditional_mated_decision_fnmr` with two
denominators and no difference. The second exists so that each run's own
published conditional number is visible in the comparison rather than quietly
replaced by a different one.

A reader who wants "the" conditional difference gets the common-eligible one,
which is the only one that means anything. A reader who wants each run's own
figure gets it, labelled with why the two cannot be subtracted.

Differences are stored as exact reduced fractions — `(cb − ad)/(bd)` divided by
its GCD — and percentages appear only in the rendered report, computed from the
integers printed beside them.

## Alternatives considered

**Subtract them and add a footnote.** The number would be copied; the footnote
would not.

**Report only the common-eligible comparison.** Cleaner, and it would hide the
fact that the eligible populations differ at all — which is itself one of the
findings.

**Recompute each run's conditional rate over the other's eligible set.** Four
numbers instead of two, none of which either run published, and each of which
would need its own explanation.
