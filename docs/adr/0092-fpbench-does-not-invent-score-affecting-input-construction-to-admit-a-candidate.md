# 0092 — fpbench does not invent score-affecting input construction to admit a candidate

*Status: Accepted — 2026-08-09, stage 10A*

## Context

ADR 0087 established that a score-affecting gap in the upstream sources is a
blocker rather than a decision for fpbench to take. It was written about a
resampling kernel and a border fill in the middle of a route.

Stage 10A meets the same principle one step earlier, at the entrance to the
route, where it is far more tempting. A candidate needs a 160×160 patch. The
benchmark has a full fingerprint. The gap is one line of code, and there are
half a dozen obvious ways to write it — each of which is defensible, and each of
which produces different numbers.

The temptation has a particular shape here, because upstream *does* describe a
construction. JIPNet's paper explains how it builds partial pairs: align two
impressions of a finger with VeriFinger, compute their common mask, sample a
patch centre inside it, sample a second centre on a ring around the first, and
cut both patches after a random rotation drawn from [-180°, 180°]. It is a
careful procedure and it is fully documented.

It is also a *simulation for constructing a dataset*, not an inference
algorithm. It needs the mated image, a commercial SDK the authors state they
cannot release, and a random number generator. Adopting it would produce:

```text
VeriFinger  +  an fpbench crop policy  +  JIPNet
```

which is not JIPNet, and which fpbench would then have benchmarked under
JIPNet's name.

## Decision

fpbench does not invent, adapt or promote a score-affecting input construction
in order to admit a candidate.

**Named and refused**, so that none of them can arrive as a small practical
decision later:

```text
centre-crop N×N because it seems reasonable
resize the whole fingerprint to the model's input size
crop around an estimated core or singular point
choose the highest-quality N×N region
generate several patches and take the maximum of their scores
crop plain and rolled impressions under different rules
use SD300 to discover which crop works best
adopt a training-data or evaluation-set construction as an inference step
```

The last two are the ones that would have been easiest to justify, and they are
the worst. Choosing a crop by its performance on the evaluation set makes the
benchmark a fitting procedure. Promoting a data-construction step to an
inference step silently redefines the algorithm.

**The consequence when the gap is real:**

```text
BENCHMARK_INPUT_ROUTE_UNRESOLVED  →  the candidate FAILS
```

Not "fails with a documented preprocessing note". The note would be true, and it
would not travel with the numbers.

**A proprietary dependency is separated by role.** A commercial SDK used to
*build training data* is a training-reproducibility limitation and does not
disqualify a candidate. The same SDK required *at inference time* is
`INFERENCE_DEPENDENCY_UNAVAILABLE` and does. Only the second is a blocker for a
benchmark that has to run the route itself.

## Alternatives

**Define an fpbench crop policy, document it, and mark the algorithm id with
it.** Rejected for the reason ADR 0090 rejects a qualified reimplementation
name: the qualifier stays in the evidence, the number goes everywhere.

**Ask upstream.** Not rejected — it is a reasonable next step for anyone who
wants this candidate — but it is not something a stage can depend on, and it
cannot be the reason a stage stays open.

**Run several crops and report the spread.** Rejected: it multiplies one
unresolved choice into a distribution over unresolved choices, and then someone
has to pick a summary statistic, which is the same decision wearing a hat.

## Consequences

The Algorithm 4 slot can stay empty at the end of a stage. That is the intended
cost, and it is smaller than the cost of a number nobody can attribute.

The refused list is reusable and will be checked against future candidates
verbatim. It is short, specific and phrased as things somebody might actually
propose, which is what makes it useful.

Where a candidate *does* have an authoritative transformation, this ADR costs
nothing: the transformation is recorded with its locator and the gate passes.
