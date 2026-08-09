# 0089 — Algorithm 4 is preflighted before it is committed to

*Status: Accepted — 2026-08-09, stage 10A*

## Context

Stage 9 selected FLARE as the fourth algorithm and then spent a full stage
establishing that it could not be executed faithfully. The reading was correct
and the outcome — `FLARE_FULL_ROUTE_BLOCKED` — was a complete result. The
problem was the order of the work.

Stage 9A opened by pinning two repositories, enumerating ten artifacts, building
a seventeen-operation transform graph and modelling the score arithmetic. Only
after all of that did it become clear that the paper and the public code place
enhancement at different points of the route, and that the six checkpoints have
Google Drive links instead of identities. Neither fact needed a transform graph
to discover. Both were readable on the first day.

The cost was not wasted keystrokes. The cost was that a candidate had already
been *selected* before it had been *checked*, and a selected candidate creates
pressure. Every gap becomes something to work around rather than something to
report, because the alternative is that the stage produced nothing.

The two candidates now in front of us look likely to fail for entirely different
reasons, and both reasons are readable before anything is downloaded:

```text
AFR-Net    no author-supplied implementation or checkpoint was located
JIPNet     official and well documented, and released for a different input
```

## Decision

Selection of Algorithm 4 is preceded by a **preflight**: a cheap, hard,
fail-fast qualification of every candidate, run before any candidate is chosen.

**One question.** Which, if either, candidate can enter fpbench as Algorithm 4
without an fpbench reconstruction, without invented preprocessing, and without
SD300 being consulted to make it fit.

**Seven hard gates, conjunctive and unweighted:**

```text
1  IDENTITY             is the executable thing the authors' own?
2  INPUT_DOMAIN         can canonical_500 reach its declared input?
3  ARTIFACTS            are the required bytes named and obtainable?
4  INFERENCE_ROUTE      does the checkpoint fill the model it claims?
5  SCORE_CONTRACT       one finite scalar per attempt, no threshold
6  TRAINING_PROVENANCE  what was it fitted on, and does that touch SD300?
7  RUNTIME_SMOKE        does it construct, load and run on a synthetic pair?
```

A candidate must pass all seven. There is no total, no weighting and no
threshold at which enough gates make a candidate acceptable. This is the direct
lesson of Stage 9A: a scoring scheme would have ranked FLARE first while its
artifact identity was unresolved.

**Fail-fast, in that order.** A candidate stops at the first gate it fails, and
every later gate is published `NOT_REACHED` — a state that is neither a pass nor
a soft failure, and that carries no conclusion. Gates 1 and 2 come first because
both can be settled by reading. Settling either negatively means several hundred
megabytes are never fetched and a runtime is never built.

**Both outcomes are complete results:**

```text
ALGORITHM4_CANDIDATE_SELECTED       exactly one survivor, named
ALGORITHM4_PREFLIGHT_NO_SURVIVOR    none, and a search for a third candidate opens
```

No gate is weakened to obtain an Algorithm 4.

## Alternatives

**Score the candidates and pick the best.** Rejected: this is exactly what
produced the Stage 9A ordering, where a candidate with an unresolvable blocker
would still have won.

**Qualify one candidate fully, then the other if it fails.** Rejected: it
re-creates the commitment problem one candidate at a time, and it wastes the
cheapest information — that the two fail at different gates — which is only
visible when both are run against the same ladder.

**Fold the preflight into the artifact qualification.** Rejected: an artifact
qualification downloads artifacts. The whole value here is deciding *not* to.

## Consequences

A stage that can end in a few days with no candidate, having downloaded nothing.
That is the intended shape, and it is much cheaper than discovering the same
fact after an artifact qualification.

`NOT_REACHED` has to be honoured everywhere, including in the published
documents. A reader can see which questions were asked and which were not, and
cannot mistake silence for a pass.

If a future candidate survives, its artifact qualification starts from a
position where identity, input domain and score semantics are already settled —
which is the position Stage 9A should have started from.
