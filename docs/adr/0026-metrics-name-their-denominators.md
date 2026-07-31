# 0026 — Every rate stores and names its exact numerator and denominator

## Status

Accepted. Implemented in `fpbench.core.metric_models` and enforced by
`fpbench.metrics.denominators.resolve`.

## Context

Stage 5A produced 6,000 decisions and deliberately computed no rate, because a rate is
three claims wearing one number: which comparisons counted, what counted as success, and
what happened to the ones that produced no score. Stage 5B has to publish rates, and the
question is what a published rate *is*.

The tempting answer is a float. `0.006` is small, sorts, plots, and goes into a table
without argument. It is also unfalsifiable. A reader who wants to know whether `0.6%`
means three failures out of five hundred or thirty out of five thousand cannot find out,
and neither can a reviewer, and neither — six months later — can the person who computed
it.

Worse is the failure that is invisible from the number. Consider a population of 500
mated comparisons of which 13 produced no score. A non-match count of 3 can honestly be
reported as `3/487` or as `3/500`; they are different quantities with different names,
and they round to `0.6161%` and `0.6000%`. Nothing about either percentage says which
denominator produced it. If the aggregation function picks one and the report prints the
other's label, no test that checks arithmetic will notice, because the arithmetic is
correct — it is the *population* that is wrong.

## Decision

**A metric's authoritative value is a pair of integers, and its denominator is named by a
closed vocabulary rather than supplied as a number.**

Three things follow.

`MetricObservation` stores `numerator_count` and `denominator_count`. The percentage is
never stored. It is rendered on demand from the two integers using exact decimal
arithmetic, and it is always printed *beside* the fraction:

```
3/500 (0.6000%)
```

`MetricDefinition` names its denominator with a `MetricDenominator` member —
`ALL_ATTEMPTS`, `DECIDED_ATTEMPTS`, `ALL_ELIGIBILITY_UNITS`,
`INCLUDED_CONDITIONAL_ATTEMPTS`, `DECIDED_CONDITIONAL_ATTEMPTS` — and that member reaches
the metric policy fingerprint. Changing a denominator changes the policy fingerprint,
therefore the metric-set fingerprint, therefore the metric-set id. A silent substitution
is not available.

**No function may pass a denominator to another function.** Both the aggregation that
produces observations and the verifier that re-checks them call `resolve(definition,
record)`, which derives *both* integers from a stored count record and the definition's
enums. A verifier handed `3/487` does not check that 3 ≤ 487; it looks up the count
record the metric reads, resolves `DECIDED_ATTEMPTS` against it, and sees whether 487 is
what comes out.

Alongside the observations, the complete aggregate tables are stored as
`EvaluationCountRecord`s. A reader with those can recompute every rate in the report and
does not have to trust — or reverse-engineer — the code that produced it.

## Alternatives

**Store the percentage and the counts.** Redundant, and redundancy in stored data is a
question about which copy is authoritative that somebody eventually answers wrongly. The
percentage is derived; it lives where derived things live, in the rendering.

**Store a `Fraction`.** `Fraction(3, 500)` normalises to `3/500` but `Fraction(6, 1000)`
also normalises to `3/500`, and 6 out of 1,000 is not 3 out of 500. Normalisation
destroys exactly the information this ADR exists to keep.

**Name the denominator in a docstring and pass an integer.** This is the status quo
everywhere and it is what produced the problem. A docstring is not checked.

**Let each metric have its own aggregation function.** Fourteen functions, each free to
divide by whatever it finds convenient, and no single place to test. The cost of one
`resolve` is that adding a metric means adding a catalogue entry rather than a function;
that cost is the feature.

## Consequences

* Every report table is wider: a rate column carries a fraction and a percentage.
* Adding a metric means adding an entry to `METRIC_CATALOGUE` in code. A config file can
  switch a metric on; it cannot define one.
* A denominator that a population cannot supply — eligibility units over the mated view —
  fails loudly at derivation rather than producing a plausible number.
* Percentages are strings, quantized once for display. There is no float anywhere in the
  metric path, so there is no rounding to argue about.
