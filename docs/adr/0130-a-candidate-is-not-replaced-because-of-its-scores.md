# A candidate is not replaced because of its scores

## Status

Accepted, implemented.

## Context

Stage 15A closed `FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE` and set
`algorithm_5_established: true`. The result set is complete: 6,000 outcomes, none
missing, none duplicated, no infrastructure failure, fully deterministic.

It is also, on inspection, not usable. Of the 389 scores, 367 are SELF
comparisons that return exactly 1.0 by construction. Twenty-two comparisons of
two different prints produced a number. The other 5,610 outcomes are one refusal
code, `CONVEXITY_DEFECTS_REFUSED_CONTOUR`, raised where an Otsu-binarised
fingerprint yields a contour whose convex-hull indices are not monotonous.

There are two completely different ways to say why that candidate is being
passed over, and they lead to different projects.

The first is available immediately and is the wrong one: *twenty-two genuine
scores out of six thousand is too few to calibrate against roughly 5,900 from
each of the other four algorithms.* It is true. It is also a comparison of two
algorithms' outputs, made before any common operating point exists between any of
the five — the exact thing every stage since 7D has refused to do — and it makes
the benchmark's roster a function of the benchmark's own results.

The second is what the evidence actually supports. The route is deterministic and
reruns identically. The matcher stage succeeds whenever both sides extract. The
failures originate in feature extraction, not in matching. A single invalid
contour aborts an image that is otherwise entirely processable. And remediation —
a `try/except`, a different `contour mode` — would change the algorithm rather
than fix the harness.

That second account never mentions a score. It survives somebody disagreeing
about whether twenty-two is few.

The distinction generalises past this one candidate. A score distribution cannot
tell an algorithm that is *strict* from one that is *broken*: both produce few
numbers. Only the mechanism separates them, and Stage 15A is the case where
everything read green and the candidate was still unusable.

## Decision

**A candidate is passed over for a stated structural reason, never for its score
behaviour.**

Stage 16A records Stage 15A's non-selection as
`STRUCTURAL_EXTRACTION_ROUTE_FAILURE`, with five statements of mechanism and not
one number:

```text
route deterministic
matcher stage succeeds whenever both sides extract
widespread failures originate in feature extraction
single invalid contour aborts an otherwise processable image
remediation would require modifying upstream algorithm
```

and publishes, beside it, what the reason **is not**: low genuine scores, poor
discrimination, worse than another matcher. `verify_stage16a_evidence` fails if
any of those three denials goes missing, so the account cannot quietly drift into
a comparison later.

Three consequences are enforced rather than promised:

- **Stage 15A's evidence is not modified and its run is not repeated.** It stands
  as published: a valid result set from a candidate that was examined.
- **Stage 15A's scores were not read to choose a successor.** They could not have
  been: FingerFlow was already named as the reserve in Stage 15A's own selection
  record, under a policy fixed before either candidate produced anything.
- **The Algorithm 5 acceptance criterion is rewritten, and its fourth condition
  carries no number.** "The result set carries at least one score" is retired.
  What replaces it is: the route is upstream-authoritative and closed; no systemic
  implementation exception on valid input; extraction and matching do not
  collapse from an internal defect across the dataset; and a materially large
  number of score-bearing comparisons between two different impressions. If a
  candidate approaches Stage 15A's extreme, the stage stops before the marker and
  a person decides on the mechanism.

## Alternatives

**Set a numeric floor — say, 1,000 genuine scores.** Rejected. Any number chosen
now would be chosen with Stage 15A's twenty-two in view, which is a threshold
picked from the evaluation data. It would also be arbitrary across algorithms
whose refusal semantics differ.

**Rewrite Stage 15A's outcome as a failure.** Rejected for the reason
docs/adr/0104 and docs/adr/0121 give: the stage ran to the end and produced a
real result. A stage that found the candidate unusable has succeeded at being a
stage, and reclassifying finished evidence after the fact manufactures a history
that did not happen.

**Say nothing about why, and simply open the next candidate.** Rejected. The
next reader would find two consecutive Algorithm 5 stages and no account of the
transition, and would reasonably assume the scores decided it.

## Consequences

The roster is chosen on properties of algorithms rather than on their outputs,
which is what lets the eventual calibration stage compare five algorithms without
the selection having already peeked.

The cost is that "materially large" is not machine-checkable, and Stage 16A
therefore cannot mechanically refuse a thin-but-nonzero result set the way it
refuses an empty one. That is deliberate: the alternative is a number invented in
advance of the only data that could justify it. The stage stops and asks.

Stage 15A's own marker keeps `algorithm_5_established: true`, because that was
the criterion it was given and rewriting it retroactively is the thing this ADR
forbids. Stage 16A's marker is where the slot reopens.
