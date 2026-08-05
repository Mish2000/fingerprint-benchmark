# 0073 — A raw score is a Decimal, and is never clamped

*Status: Accepted — 2026-08-05, stage 8B*

## Context

The comparator produces an IEEE double. Everything downstream — a result row, a
threshold comparison two stages from now, a diff between two runs — wants a
number that means exactly one thing.

Handing that double to `Decimal` directly is faithful and useless:

```
Decimal(0.1) == Decimal('0.1000000000000000055511151231257827021181583404541015625')
```

Fifty-five digits of binary expansion, in every result row, for a value whose
last forty are an artefact of the representation rather than of the comparison.
Rounding it, on the other hand, throws away bits a later stage may need, and
"round to six places" is a decision about precision made by whoever wrote the
formatting code.

Two separate float32 facts also surfaced once the route ran. Both are
properties of the arithmetic, not of any input, and both were measured rather
than anticipated.

The branches are L2-normalized in float32, so a norm is 1 within an ulp. A SELF
comparison — the same representation against itself — therefore does not land
on 2. It lands on **2.0000001192092896**, which is exactly `2 + 2**-23`.

And the antialiased bilinear resize computes its filter weights in float32;
they do not sum to exactly one. A uniformly white image does not resize to a
constant. It resizes to **[0.9999997615814209, 1.0000003576278687]**.

Under a literal reading of "nominal range [-2, 2]" and "value range [0, 1]",
the route fails on its own arithmetic, for every input, forever.

## Decision

**Serialization.** The public `compare` API returns `Decimal`, produced by one
frozen rule, `ieee_scalar_to_decimal17_v1`:

1. preserve the scalar the pinned `numpy.dot` comparator returned;
2. convert it through a canonical 17-significant-digit decimal string;
3. construct the `Decimal` from that string.

Seventeen digits is not the shortest form that round-trips — `repr` gives that,
and `repr(0.1)` is `"0.1"`. It is the digit count that always suffices to
recover an IEEE double exactly, which is the property the rule needs. Nothing
is rounded for a decision or for display while a raw result is being made.

**Range.** The declared ranges stay [-2, 2] and [0, 1], because those are the
mathematical ranges and they are what the profile means. Enforcement allows a
bounded excursion, and the bound is derived from the format rather than fitted
to the measurement:

| | allowance | derivation | observed |
| --- | --- | --- | --- |
| score | `2**-21` | four float32 ulps at 1.0: two branches, each off by up to one ulp, doubled | `2**-23` |
| tensor | `2**-20` | eight float32 ulps at 1.0 | `~3e-7` |

Neither value is clamped. Clamping the score would discard bits a later stage
may need; clamping the tensor would change pixels in a step neither the spec
nor upstream performs.

**These allowances are not the determinism tolerance.** `numeric_tolerance`
remains exactly `0`: two runs of the same comparison must still agree bit for
bit, and nothing here relaxes that. One says how far arithmetic may sit from an
ideal; the other says how far two runs may sit from each other, and the answer
to the second is nowhere.

## Alternatives considered

**Clamp to the declared range.** Makes the contract true by making the number
false. A score of exactly 2.0 that was measured as 2.0000001 is a rounded
score presented as a raw one.

**Widen the declared range to what was observed.** Turns a bound into a
transcription of a measurement, on this machine, this week. The next torch
release moves it and the range means nothing.

**Return the float and let the caller decide.** The caller is a result store,
and then a threshold, and then a report; each would make its own formatting
decision and none would be recorded. `Decimal` at the boundary is what makes
the rule inspectable.

**Round to a fixed number of decimal places.** Chooses a precision without
saying why, and the choice would sit outside every fingerprint.

## Consequences

A raw score is exactly reproducible from its stored text, and two runs that
agree bitwise produce byte-identical rows.

The two allowances are part of the frozen identity and appear in the evidence,
so a reader can see that the route runs slightly outside its ideal range and
why. A future runtime whose arithmetic drifts further will fail the range gate
rather than quietly widening it.

Stage 8C stores these scores unchanged. Thresholds, decisions, eligibility and
metrics remain outside it (docs/adr/0065).
