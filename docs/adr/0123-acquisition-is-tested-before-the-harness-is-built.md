# Acquisition is tested before the harness is built

## Status

Accepted, implemented.

## Context

Two Algorithm 5 candidates have now consumed a full preflight stage each, and
neither produced a single comparison.

Stage 12A defined ten gates, a qualification harness, a fake-SDK double and
thirteen evidence documents for Innovatrics IDKit. It reached gate one:
Innovatrics does not license SDKs for academic, research-only evaluation.

Stage 13A defined ten gates, thirteen documents, a compiled C++ bridge and a
qualification harness for Neurotechnology FingerCell. It went further — the
archive was fetched, hashed, unpacked and compiled against — and reached gate
three: the trial entitlement could not be established in the qualified
environment. No extraction, no match, no score.

In both cases the work that settled the stage was small and came first, and the
work that was thrown away was large and came before it. Roughly nine gates of
machinery were built each time for questions that were never asked.

The pattern is not bad luck. Vendor SDK acquisition and route viability are
*independent* of harness quality, they are settled early, and they fail often.
Building the harness first optimises for the case that has not happened yet.

## Decision

Stage 14A inverts the order. It asks the smallest set of questions that could
disqualify the candidate, in the order that disqualifies fastest, and builds
nothing else until they are answered:

```text
G1  OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS    can we get it, with its trial?
G2  DIRECT_CANONICAL500_INPUT_ROUTE       can our image enter it unmodified?
G3  SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE    can we get a raw scalar score out?
G4  SCORE_AFFECTING_ROUTE_CLOSURE         is anything left for us to invent?
```

Four gates, eight documents. Explicitly out of scope: trial activation, any
score-bearing execution, determinism experiments, performance measurement, SD300
access, the production adapter, registry integration, the 6,000-pair run,
threshold profiles, calibration and metrics. The stage publishes that list as
`STAGE_14A_DOES_NOT` so the boundary is checkable rather than promised.

Every gate after G1 is a question about delivered bytes, so unlike Stage 13A —
where a training-provenance search needed no runtime and could be answered out of
order — **every non-passing state stops the run**. There is nothing to ask around
a package nobody holds, and a gate answered from the vendor's website instead
would be answering a different question.

If all four pass, Stage 14B is a single stage that carries the candidate all the
way: bounded non-SD300 runtime qualification, then the production adapter over
the same frozen route, then the 6,000 canonical raw outcomes. No separate
readiness stage.

## Alternatives

**Repeat the ten-gate template.** Consistent with Stages 12A and 13A, and it
would have produced a third large harness for a candidate whose package this
project cannot currently obtain.

**Ask only about acquisition, and defer the route questions.** Cheaper still, and
it would defer the two questions most likely to disqualify Griaule specifically:
a documented 500 × 500 extraction limit, and a matcher documented in terms of a
threshold rather than a score. Both are cheap to answer from a delivered header
and expensive to discover after an adapter exists.

**Build the bridge while acquisition is pending.** Stage 13A's own ADR 0115
established that the harness should compile before the trial clock starts — but
that presumes a package. Here there is no package to compile against, and a
bridge written from a documentation page would be a bridge to an API nobody has
seen.

## Consequences

Stage 14A is the smallest stage since 8A: five source modules, no bridge, no
adapter, no integration directory, no fake engine. If Griaule fails at G1 as the
last two candidates did, the total cost of the attempt is an acquisition walk and
a route table.

The cost is that a Stage 14A `PASS` proves less than a Stage 13A `PASS` would
have: it establishes that the route exists and is authoritative, not that it runs
deterministically or fast enough. Those move to Stage 14B, where they are
answered against a package that is known to exist.
