# An asymmetric matcher is bound by protocol, not normalised

## Status

Accepted, implemented.

## Context

Innovatrics documents its fingerprint matching as not symmetrical and the
comparison as not commutative: `score(A, B)` and `score(B, A)` can differ,
because the algorithm treats the probe side and the gallery side differently.

Stage 11A asked the same question of VeriFinger and treated the answer as a
*finding* — run both orderings, publish whether the digests agree. That was the
right shape for a route where symmetry was plausible. Here it is documented not
to hold, which changes what the question is for. There is nothing to discover;
there is something to decide.

Three ways of deciding it are available, and two of them are wrong in ways that
would not show up until the results were being compared:

* **Reduce.** Take the maximum, the minimum or the mean of the two orderings.
  The maximum is the worst: it is a per-pair choice made on the strength of the
  scores themselves, which is a decision rule smuggled into a raw score.
* **Normalise.** Score both ways for all 6,000 pairs and combine. This doubles
  the workload, doubles the licence cost, and still has to choose a combining
  rule — the same problem with more steps.
* **Bind.** Map the pair order the protocol already holds onto the roles the API
  defines, once, in advance, and apply it to every pair.

The benchmark's pair manifest already distinguishes a left side from a right
side, and has since the protocol was frozen. Every other algorithm in the
benchmark receives the pair in that order.

## Decision

```text
pair.left  → probe
pair.right → gallery
```

Frozen in `PAIR_ROLE_BINDING`, applied to every pair, and enforced by the marker:
`pair_orientation` must be exactly `left_probe_right_gallery` or the marker
refuses to validate.

**This is a protocol binding, not a parameter.** It is recorded with the
provenance `FPBENCH_PROTOCOL_BINDING`, which is the one member of the provenance
vocabulary that is not upstream's own statement. It covers the deterministic
mapping of something the benchmark already froze onto an API — this, and 500 DPI
for a 500 PPI image — and it may never be used to pick a quality threshold, a
speed profile or a template size. It was not chosen by trying both and keeping
the better one, and nothing in the code path can consult a score to decide it.

**Both orderings are still run once, in qualification.** Not to choose between
them, but so that the evidence *publishes* that they differ. A reader who later
sees an asymmetry in the results should find it already recorded rather than
discover it.

**The reductions are refused by name.** `REFUSED_ORIENTATION_REDUCTIONS` holds
max, min, average, sorting the two paths, and choosing whichever scores higher.
The contract suite asserts each one is there.

## Alternatives

**Score both directions for all 6,000 and publish both.** Defensible, and a
different benchmark: it would give this candidate two measurements per pair where
the other four have one, and every comparison would then have to say which of the
two it used. It also doubles a licence's transaction count for a candidate whose
entitlement is not yet known.

**Choose the orientation that scores higher on a pilot.** This is tuning on the
data, with an extra step.

**Treat asymmetry as a blocker.** Over-strict. An asymmetric matcher is a normal
matcher with a documented convention; what would be a blocker is an asymmetry
nobody recorded.

## Consequences

The 6,000 comparisons under this candidate would be exactly 6,000, in the same
pair order as every other algorithm, with the orientation recorded once in the
marker rather than per pair.

The cost is that this candidate's scores are, strictly, scores of a directed
comparison — and so are every other algorithm's, which is why they are
comparable. If a later stage wants the reverse direction, it is a separate run
with its own identity, not a re-reading of this one.
