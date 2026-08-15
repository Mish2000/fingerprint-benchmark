# An upstream refusal is an outcome, not a rejection criterion

## Status

Accepted, implemented.

## Context

`fingerprints_matching.minutiae_matching.match` ends like this:

```python
return score / len(minutiae1)
```

If the first image yields no features, that is a `ZeroDivisionError`. The research
that selected this candidate drew the obvious conclusion and proposed a rule:
reject the candidate if even one image returns zero minutiae, because the code
divides by a count it never checks.

Reading the installed module rather than the summary turns up more of the same
shape. `cv2.imread` returns `None` for anything it cannot decode, and the very
next line hands that `None` to `cvtColor`, which raises. `cv2.convexityDefects`
refuses a contour whose hull indices are not monotonous, which is a property of
the binarised ridge structure of that particular print, and it raises too.

So the route has several ways to raise on an input it cannot process, and none of
them is a bug in the sense of being unintended: each one is the algorithm meeting
an image it has nothing to say about.

The benchmark already has a representation for that. Every stage since 7A stores
outcomes, not scores: VeriFinger's Stage 11B result set contains 81 `BAD_OBJECT`
rows where the engine declined to build a template, counted and published, and
nobody called that a reason to reject VeriFinger.

There is also a much worse option available, and it is the one worth naming. An
integrator under pressure to get 6,000 numbers can wrap the call and return 0.0
on exception. That produces a complete-looking result set in which "the algorithm
could not process this print" is indistinguishable from "these two fingers are
maximally dissimilar".

## Decision

**An exception from the upstream route is an algorithmic failure carrying no
score. It is never a rejection criterion and never a zero.**

```text
upstream returns a finite number
    -> RAW_SCORE

upstream raises while processing the prints it was handed
    -> ALGORITHMIC_FAILURE, no score attached

never:
    exception -> score 0.0
```

The zero-feature case is not special-cased. `ZeroDivisionError` is mapped like
every other upstream refusal, under its own code `NO_FEATURES_ON_FIRST_SIDE`, so
a reader can see how often it happened without it changing what the algorithm is.

**fpbench does not repair the algorithm to avoid it.** No denominator fallback,
no guard clause, no invented score for an empty feature set, no substituting a
different OpenCV flag to produce more extractable contours. Any of those would
make fpbench a co-author of the matcher.

G3 passes when such a failure is deterministic, carries no number, and can be
mapped without touching the algorithm. G3 fails only if proceeding would require
repairing it.

## The limit, and where it is enforced instead

This is not a licence to publish an empty result set. The requirement moves to
where it belongs — the end, where it can be measured rather than guessed:

> A result set of 6,000 outcomes containing no score at all does not establish
> Algorithm 5, whatever the failures were.

That is docs/adr/0128, and it is a statement about what the run produced rather
than a prediction made before it ran.

## Alternatives

**Reject the candidate on the first zero-feature image, as the research
proposed.** It is a real property, but it is a property the benchmark can already
express as data, and applying it at qualification time would reject on a
prediction rather than on a measurement.

**Catch the exception and return 0.0.** Puts a similarity into the record that
the algorithm never computed. The result-model layer refuses it structurally: a
failed `RawMatchResult` that carries a score raises, so this cannot be done by
accident.

**Skip the pair.** Corrupts every denominator downstream. There is no `SKIPPED`
in `ExecutionStatus` for exactly this reason.

## Consequences

Failure codes are named at the point where the information exists — in the bridge,
where the exception is caught — rather than inferred later from a traceback:
`NO_FEATURES_ON_FIRST_SIDE`, `CONVEXITY_DEFECTS_REFUSED_CONTOUR`,
`IMAGE_NOT_DECODABLE`, `OPENCV_REFUSED_INPUT`, `UPSTREAM_RAISED`.

The failure breakdown is published by count and code. Rates are not, at this
stage: a rate invites a comparison between algorithms before there is a common
operating point.

A missing input file is deliberately *not* an algorithmic failure. Upstream would
report it as an undecodable image, which would turn a broken workspace into 6,000
biometric-looking outcomes, so the adapter checks that both prepared files exist
and raises an infrastructure failure that stops the run.
