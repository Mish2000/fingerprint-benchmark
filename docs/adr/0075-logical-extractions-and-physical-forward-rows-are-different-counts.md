# 0075 — Logical extractions and physical forward rows are different counts

*Status: Accepted — 2026-08-05, stage 8C*

## Context

ADR 0070 established that the pinned texture branch cannot process a batch of
one, so one extraction feeds the identical preprocessed tensor twice as a batch
of exactly two rows and represents row 0, after asserting the two rows are
bitwise equal.

That workaround is invisible inside a single comparison and impossible to ignore
across 6,000 of them. A full Stage 8C run plans:

```
6,000  comparisons
12,000 preprocess calls          two per comparison, one per side
12,000 extraction calls          two per comparison, one per side
6,000  comparison calls
```

and executes 24,000 physical forward rows to produce those 12,000 extractions.

Both numbers are true and they measure different things. 12,000 is how many
representations the run produced and is the number that must equal
`2 x stored results`. 24,000 is how much arithmetic the checkpoint did and is
the number that explains the wall clock. A summary that reported "24,000
extractions" would claim the run produced twice as many representations as it
did; a summary that reported only 12,000 would make the measured throughput look
half as fast as the hardware actually worked.

Stage 8B's policy already reasons in the first unit — `max_projected_12000_extractions_seconds`
is a budget over logical extractions — so a summary that silently used the other
unit would also be comparing against a budget it does not match.

## Decision

The operational summary reports both, under names that cannot be confused:

```
preprocess_call_count            12,000
logical_extraction_call_count    12,000
physical_forward_row_count       24,000
comparison_call_count             6,000
```

`physical_forward_row_count` is always reported together with the rule that
produced it, so a reader never has to know ADR 0070 to interpret it:

```
inference_batch_rows  2
inference_batch_rule  duplicate_pair_take_first_row
represented_row       0
```

The identity of a representation is unchanged and stays as ADR 0070 defined it:

```
one logical extraction
  -> two identical physical rows
  -> verify both output rows are bitwise equal
  -> return row 0
```

The word "extraction", unqualified, means a logical extraction everywhere in
Stage 8C: in the counts, in the audit, in the receipt and in the evidence. A
physical row is never called an extraction.

## Alternatives considered

**Report only logical extractions.** Hides the doubling, so the measured
throughput of the run cannot be reconciled with the measured cost of one forward
pass, and the ADR 0070 workaround becomes invisible in exactly the artefact a
reviewer reads.

**Report only physical rows.** Overstates the number of representations by a
factor of two and would make the run appear not to satisfy "12,000 logical
extraction operations".

**Report one number and a multiplier.** The multiplier is a property of the
pinned checkpoint's texture branch, not of the run, and a reader would have to
perform the arithmetic to get either number. Two named counts cost one line
each.

**Patch upstream so one image is one row.** Rejected in ADR 0070 and not
reopened here: the source is pinned by digest and a local patch would make the
executed algorithm a reimplementation (docs/adr/0066).

## Consequences

The receipt, the audit and the operational summary all carry both counts, and a
contract test asserts the fixed relationship
`physical_forward_row_count == logical_extraction_call_count * inference_batch_rows`
rather than asserting either literal.

The projection Stage 8B recorded — 2.54 h for 12,000 logical extractions —
already includes the doubling, because it was measured on the route that does
it. Nothing in the budget needs restating.

If a future runtime profile gains a single-row path, `inference_batch_rows`
becomes 1, the two counts coincide, and the summary keeps both fields rather
than changing shape. A run under that profile would be a different route with a
different representation identity, so the two are not comparable anyway.
