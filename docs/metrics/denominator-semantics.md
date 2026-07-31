# Denominator semantics

Five denominators, what each one covers, and why a metric may not choose freely
between them.

## The problem this solves

A rate whose denominator is implied is a rate nobody can check. Consider a population of
500 mated comparisons of which 13 produced no score, and 3 of the remainder returned a
non-match. Two honest numbers exist:

```
3 / 487 = 0.6161%      3 / 500 = 0.6000%
```

They are different quantities with different meanings, and neither percentage says which
denominator produced it. If an aggregation function picks one and a report prints the
other's label, nothing that checks arithmetic will notice — the arithmetic is fine, the
*population* is wrong.

So denominators are named rather than computed. `MetricDefinition` carries a
`MetricDenominator` member, and one function —
[`fpbench.metrics.denominators.resolve`](../../src/fpbench/metrics/denominators.py) —
turns that member and a stored count record into an integer. Both the aggregation that
produces observations and the verifier that re-checks them call it, so the two cannot
disagree about what a denominator was.

## The five denominators

### `ALL_ATTEMPTS`

Every comparison in the population, decided or not.

Over a decision family this is the total number of comparisons attempted. Over the
conditional family it is **every mated row, included or excluded** — the denominator of
the selection rate, and the only one in the stage that spans excluded rows.

### `DECIDED_ATTEMPTS`

Only the comparisons a threshold could actually be applied to: `MATCH + NON_MATCH`.
Comparisons that produced no score are not here.

The difference between this and `ALL_ATTEMPTS` is exactly the undecidable count, which
the report prints beside every population so the reader can see the gap rather than infer
it.

### `ALL_ELIGIBILITY_UNITS`

Every release/subject/finger unit, whatever its SELF status. Available only over the
eligibility family — asking for it over the mated view is a category error, not an
unusual choice, and `resolve` raises.

### `INCLUDED_CONDITIONAL_ATTEMPTS`

Conditional rows the SELF condition kept, decided or not. Excluded rows are never in
here; they are accounted for by the selection rate.

### `DECIDED_CONDITIONAL_ATTEMPTS`

Conditional rows the SELF condition kept **and** that produced a score:
`included_match + included_non_match`.

## What each family can supply

| Count family | Denominators |
| --- | --- |
| `plain_self_outcomes` | `ALL_ATTEMPTS`, `DECIDED_ATTEMPTS` |
| `roll_self_outcomes` | `ALL_ATTEMPTS`, `DECIDED_ATTEMPTS` |
| `self_eligibility_outcomes` | `ALL_ELIGIBILITY_UNITS` |
| `mated_unconditional_outcomes` | `ALL_ATTEMPTS`, `DECIDED_ATTEMPTS` |
| `mated_conditional_outcomes` | `ALL_ATTEMPTS`, `INCLUDED_CONDITIONAL_ATTEMPTS`, `DECIDED_CONDITIONAL_ATTEMPTS` |
| `negative_sanity_outcomes` | `ALL_ATTEMPTS`, `DECIDED_ATTEMPTS` |

Anything outside this table fails at derivation with a message saying so. The point is
that a denominator a population cannot supply produces an error rather than a plausible
number.

## Numerators, and the one that is a sum

Most numerators name an outcome that already exists one layer down: a decision value, an
eligibility status, a conditional inclusion state. One does not.

`NON_SUCCESS` is `NON_MATCH + UNDECIDABLE`, and it exists because that sum is the honest
attempt-level answer for a genuine comparison — both mean "this finger was not
recognised" — and because computing it inline would let two call sites disagree about
whether failures are in it.

**It is refused over impostor populations.** For an impostor comparison a failure is not a
near miss, and the sum of non-matches and failures is not a quantity anyone can
interpret. `resolve` raises rather than computing it.

Over the conditional family, outcome numerators always mean the *included* outcome:
`NON_MATCH` resolves to `included_non_match`. Counting an excluded row's outcome would
put rows in a numerator that its denominator excludes.

## Zero denominators

A metric over an empty population is `UNDEFINED_ZERO_DENOMINATOR`, with numerator zero,
no fraction and no percentage. It renders as:

```
undefined (0 included decided attempts)
```

Not `0.0000%`, not `NaN`, not an exception. An evaluation in which no finger passed both
SELF tests is a real, reportable outcome; "no comparison failed" and "no comparison was
covered" are different facts, and rendering the second as zero per cent would publish a
measurement nobody made.

## How a stored rate is checked

The verifier does not confirm that `3 ≤ 487`. It looks up the count record the metric's
family names, at the metric's scope, resolves the metric's denominator enum against it,
and compares the result with the stored integer. The same for the numerator, the same for
the fraction text, and the same for every pooled value against the sum of its releases.

A metric set is not evidence of itself. See
[ADR 0026](../adr/0026-metrics-name-their-denominators.md).
