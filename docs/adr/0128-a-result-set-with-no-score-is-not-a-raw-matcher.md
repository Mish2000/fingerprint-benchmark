# A result set with no score is not a raw matcher

## Status

Accepted, implemented.

## Context

docs/adr/0127 makes an upstream refusal an ordinary recorded outcome rather than
a reason to reject a candidate. That is right, and it has an edge that has to be
closed somewhere.

Every integrity requirement Stage 15A publishes can be satisfied by a result set
containing no scores at all:

```text
stored outcomes = 6000        missing = 0        duplicates = 0
scores + algorithmic failures = 6000             <- holds at scores = 0
infrastructure failures = 0
thresholds = calibration = metrics = false
```

Six thousand deterministic refusals are complete, internally consistent,
reproducible and correctly recorded. Every check passes. And the benchmark would
have gained nothing, because a matcher that produced no number cannot be
compared with four matchers that did.

The failure mode is specific and worth naming: the stage's own integrity
machinery is what makes such a result set look finished. Everything reads green.
Without an explicit rule, `FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE` would
be written over it, `algorithm_5_established` would say `true`, and
`opens_common_calibration` would open a calibration phase over an empty score
column.

This is also not a hypothetical shape. The qualification measured the route
refusing real fingerprint images from two independent vendors' sample sets, so
the outcome the rule guards against is one the evidence already makes plausible.

## Decision

**The marker's outcome turns on whether the result set contains at least one
score.**

```text
scores > 0
    outcome                 FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE
    algorithm_5_established true
    opens_common_calibration true

scores == 0
    outcome                 FINGERPRINTS_MATCHING_QUALIFICATION_FAIL
    algorithm_5_established false
    reopens_algorithm_5_search true
    fallback_candidate      fingerflow_3_0_1
```

`is_score_bearing` is a property of the validation report, derived from the
stored results and not from anything declared in advance. The finalization reads
it and cannot be told otherwise.

The zero-score run is still **published in full**. It is a real, expensive,
reproducible finding about a real package: the documents are written, the counts
and the failure breakdown are published, and the marker records
`why_not_complete` in plain words. What it does not get is a claim that Algorithm
5 exists.

## Why the threshold is one score and not a fraction

Any fraction would be an operating point chosen without a basis. "At least 60 %
coverage" sounds more rigorous than "at least one score" and is less defensible:
it invents a number, and the number would inevitably be argued about against the
coverage the run happened to produce.

One score is the weakest claim that is still a claim. It says the route can
produce a benchmark number on canonical inputs. Whether the coverage it achieves
is *useful* is a question for the calibration phase, over stored scores, with all
five algorithms present — which is where every other comparative question in this
project is answered.

Coverage is published as a count so that the later phase can make that judgement
with the facts in front of it.

## Alternatives

**Publish `COMPLETE` and let the calibration phase discover the column is empty.**
Moves a known problem downstream and attaches a false claim to a marker other
stages will bind to.

**Require a coverage fraction.** An invented operating point, argued about
afterwards against the very run it was meant to judge.

**Treat a zero-score run as an infrastructure failure.** It is not one. The
harness worked perfectly; the algorithm declined every print. Recording that as a
broken machine would hide a true finding about the package.

## Consequences

Stage 15A has two final outcomes and no third. There is no pending state and no
incomplete state, because nothing in this stage waits on anybody.

A `QUALIFICATION_FAIL` marker carries a full result set, a full failure breakdown
and a named fallback. The next stage starts from evidence rather than from
scratch.

The calibration roster is written into the marker only when it is real — five
named algorithms when the set is score-bearing, an empty list when it is not — so
nothing downstream can read a roster into existence.
