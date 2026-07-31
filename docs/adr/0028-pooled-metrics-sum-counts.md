# 0028 — Pooled metrics sum counts across releases and divide once

## Status

Accepted. Implemented in `fpbench.metrics.aggregate.pooled` and enforced by
`_require_pooled_is_the_sum`.

## Context

The protocol reports three releases — SD300A, SD300B, SD300C — and a reader will want one
number as well as three. There are two ways to produce it:

```
sum(numerators)                    rate_A + rate_B + rate_C
----------------                   ------------------------
sum(denominators)                             3
```

The left is a rate over the union of the populations. The right is the mean of three
rates, which weights a release with 200 usable comparisons the same as one with 500.

In *this* protocol the two agree, because every release contributes exactly 500
comparisons. That is a fact about the current pair manifest and not a property of
anything. The moment a release loses comparisons — a subject withdrawn, a set of images
failing validation, a fourth release added at a different size — the two formulas
separate, and nothing about a stored percentage says which one produced it.

There is a second, quieter version of the same mistake. Averaging *per subject* rather
than per comparison is a defensible weighting: it treats each person equally rather than
each print. It is also a different measurement, and one that answers a different
question, and choosing it silently because it was convenient would be a methodological
decision made by an implementation detail.

## Decision

**A pooled value is the sum of the release numerators over the sum of the release
denominators, computed once.**

The count models define `__add__`, and `pooled()` is a fold over the release counts. A
pooled count record is therefore *arithmetically* the sum of its parts — not checked to
be, but constructed as. There is no code path by which a caller can supply a pooled
count.

Observations are then derived from those pooled counts by the same `resolve` that derives
the release observations, and `_require_pooled_is_the_sum` re-checks that each pooled
pair equals the release sums. That check cannot fail by arithmetic; it can fail if a
metric's denominator resolves differently at pooled scope than at release scope, which
would be a real bug producing a pooled rate over a population that is not the union of
the release populations.

**The unit of analysis is one comparison.** `unit_of_analysis.kind: comparison` and
`subject_weighting: none` are in the policy file, are checked by the loader, and reach
the policy fingerprint. A policy asking for per-subject weighting is refused with a
message saying it is a different metric needing its own ADR — not silently accommodated.

The test suite uses releases of *unequal* size (10, 20, 30) precisely because the equal
case cannot distinguish the two formulas.

## Alternatives

**Average the release percentages.** Weights small releases equally with large ones, for
no stated reason, and is the default that a spreadsheet produces.

**Weight by subject.** A real and defensible choice — it stops a subject with ten usable
fingers dominating one with two — and a different measurement. It needs its own policy id,
its own metric ids and its own argument. The loader says so when refused.

**Publish only per-release values.** Honest, and unhelpful: somebody will pool them
anyway, in a spreadsheet, using the mean.

**Publish the pooled value only.** Hides that the releases differ at all, which is one of
the few things this data can actually show.

## Consequences

* Every metric has `len(releases) + 1` observations, and the pooled one is last in
  canonical order.
* Pooled counts equal the release sums by construction, so the check that says so is
  cheap and the property is not merely documented.
* A release that shrinks changes the pooled value in the way a reader would expect,
  without anyone revisiting this decision.
* A per-subject or per-finger analysis is out of scope, explicitly, rather than absent.
