# Self-service acquisition is a hard requirement for Algorithm 5

## Status

Accepted, implemented.

## Context

Three consecutive Algorithm 5 stages ended at a vendor, and not one of them ended
at a finding about a matcher:

- **Stage 12A — Innovatrics IDKit.** Ten gates built. A request made in the
  maintainer's own name received an explicit policy refusal. One gate reached.
- **Stage 13A — Neurotechnology FingerCell.** Ten gates, a bridge and a
  qualification harness built. The archive was obtained, hashed and compiled
  against. The trial entitlement never arrived. Three gates reached.
- **Stage 14A — Griaule.** The order was deliberately inverted so acquisition was
  tested first. Every official route was walked and none of them serves the
  package. One gate reached, and the request was never sent.

The pattern is not that these are bad algorithms. Nothing in three stages
established anything about their matching at all. The pattern is that the
*acquisition channel* was the binding constraint every time, and that no amount
of harness engineering moved it. Stage 14A's ADR 0123 already responded once, by
testing acquisition before building the harness. That helped — it made the third
failure cheap — but it still produced a stage that ended without a matcher.

Meanwhile the slot has been open across three stages, four algorithms have raw
result sets waiting, and the common calibration phase cannot begin until a fifth
exists.

## Decision

Two properties become **hard requirements** for an Algorithm 5 candidate, checked
before anything is built:

```text
selection_policy:
    self_service_acquisition        = HARD_REQUIREMENT
    runnable_without_vendor_action  = HARD_REQUIREMENT
```

*Self-service acquisition* means this project can obtain the artifact by itself,
from a published locator, without asking anyone for permission and without
anyone's decision in the loop.

*Runnable without vendor action* means that once the bytes are local, they
execute: no licence to be issued, no entitlement to be granted, no activation, no
machine binding, no clock.

A candidate failing either is not weighed against its technical merits. It is not
in the queue.

## What this does not do

**It does not retroactively fail Griaule.** Stage 14A remains exactly what HEAD
published: a non-final investigation in which `request_sent=false`. It is given no
marker, its evidence is not edited, and `stage14a_final_outcome` is recorded as
`NONE`. Nobody contacted Griaule, so there is no refusal, no silence and no
finding to report, and manufacturing one would be inventing evidence
(docs/adr/0104, docs/adr/0121).

What changed is fpbench's criterion. That is a statement about this project, and
the record says so in those words.

**It does not claim the excluded candidates are worse.** VeriFinger — this
benchmark's Algorithm 4 — would fail `runnable_without_vendor_action` outright: it
needs an activated trial and a 30-day clock. The rule is about what this project
can qualify on its own schedule, not about quality, and the record does not
pretend otherwise.

**It is not retroactive.** Algorithms 1–4 keep their slots. The rule governs the
Algorithm 5 search from Stage 15A forward.

## Alternatives

**Send the Griaule request and wait.** The honest cost is another stage of
unknown length with a prior set by two refusals, for a candidate whose route
questions the documentation leaves open. The slot has been open long enough that
the waiting itself is now the problem.

**Weight self-service heavily but keep commercial candidates eligible.** This is
what has effectively been happening, and it produced three stages and no matcher.
A soft preference did not stop the work being spent.

**Drop the fifth algorithm and calibrate on four.** Possible, but it settles a
methodological question by attrition. Four is the number that happens to have
worked, not a number anyone chose.

## Consequences

`fingerprints-matching` 0.1.0 becomes the active candidate: MIT, on PyPI, 4,492
bytes, local-only, nothing to activate. `FingerFlow 3.0.1` is the reserve.

`fingerprintMatcher`, MCC, OpenAFIS, JIPNet, AFR-Net, IDKit, FingerCell, Griaule
and id3 stay out of the queue and are not reopened.

Stage 15A has no acquisition preflight and no readiness stage in front of it,
because there is nothing to be ready for. Qualification and production execution
happen in one pass.

If the commercial route ever needs reopening — an institutional licence, a
research agreement — this ADR is what would be superseded, and the three stages
above are what the argument would have to answer.
