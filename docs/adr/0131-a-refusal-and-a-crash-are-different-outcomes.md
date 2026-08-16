# A refusal and a crash are different outcomes

## Status

Accepted, implemented.

## Context

Stage 15A's result set contains 5,610 rows under the failure code
`template_extraction_failed`, upstream code
`CONVEXITY_DEFECTS_REFUSED_CONTOUR`. Read as published, that says: the algorithm
was given a print and could not build a template from it.

What actually happened is that `cv2.convexityDefects` raised, from inside the
package, on a contour whose convex-hull indices are not monotonous — a condition
an Otsu-binarised fingerprint produces routinely — and the whole image was
abandoned. The image was valid. The algorithm never declined it; the
implementation fell over on it.

Both descriptions produce the same row in the same result set, and the difference
between them is the difference between a candidate that is conservative and a
candidate that is defective. Stage 15A's integrity machinery could not see it:
every check reads green either way, because both are "not a score" and both are
deterministic.

Stage 16A's G4 would have caught it, had a fixture reached it — and that is the
second half of the lesson. Stage 15A's qualification ran on this project's
synthetic ridge fields, which extract fine. Every *real* fingerprint tested,
from two independent vendors' sample sets, was refused. A qualification whose
fixtures cannot distinguish the two behaviours is not a qualification, in exactly
the way docs/adr/0079's regression test whose fixture could not distinguish two
selectors was not a regression test.

FingerFlow makes the distinction concrete before any execution. Its two upstream
assemblies classify the same input in opposite ways: one refuses explicitly when
there are fewer minutiae than the model needs, the other has no guard at all and
lets a short vector reach a model whose input shape is fixed. The same
fingerprint is a declared non-result under one and a shape exception under the
other.

## Decision

**Two disjoint classes, named in the vocabulary and never merged.**

```text
EXPLICIT_ALGORITHMIC_NON_RESULT
    upstream states the condition and returns from it — no core detected,
    fewer minutiae than the model accepts. A result: the algorithm declined
    this input, and the result set records the refusal.

UNHANDLED_IMPLEMENTATION_EXCEPTION
    a valid fingerprint reached an internal tensor, index, shape or OpenCV
    exception and the route aborted. Not a result, not a template-extraction
    failure, and not evidence about the fingerprint.
```

The rules that follow:

- An unhandled implementation exception on valid input is a **qualification
  failure**, not a row. During G4 it fails the gate. During a production run it
  is recorded as a route failure and never as `template_extraction_failed`,
  because filing it there would make the result set say something about the
  fingerprint that is not true.
- A systemic failure mechanism found mid-run stops the run. The candidate is
  classified as unsuitable and the upstream is not repaired — a `try/except` or a
  changed contour mode is a different algorithm, which is the whole reason
  Stage 15A's candidate could not simply be fixed.
- `Stage16AUnhandledImplementationError` exists so that the second class cannot
  be filed as the first by an `except` clause that is one line too broad.
- G4's probe list names `no_core_or_insufficient_minutiae` explicitly, so the
  case that separates the two classes is exercised deliberately rather than
  encountered by luck.

## Alternatives

**One class, "the algorithm produced no score".** What Stage 15A effectively had.
Rejected: it is precisely the conflation that let a structurally broken route
publish 5,610 rows that read as ordinary refusals.

**Treat every exception as disqualifying.** Rejected. An algorithm that raises a
documented, named exception for a condition it declares — no core detected — is
behaving correctly, and Python's normal way of returning "no" is to raise. What
matters is whether upstream *states* the condition, not whether control leaves by
an exception.

**Decide the class from the exception type.** Rejected. `ZeroDivisionError` was
Stage 15A's honest "no features on the first side" and would be a defect in
another route. The class is decided by whether upstream declares the condition,
which is a question about the source, not about the traceback.

## Consequences

A result set's refusal rows now mean one thing, and a benchmark reading them
years from now can trust that a refusal was the algorithm's decision.

The cost is that classifying a failure requires reading upstream to see whether it
declares the condition — the classification is not derivable from the runtime
alone. Stage 16A pays that cost inside G2, where every route question is already
being settled against upstream authority, and the two questions turn out to be
the same question: an assembly that does not say what happens below the minutiae
count is an assembly that cannot tell you which class its failure belongs to.

This is also why Stage 16A stops at G2 rather than proceeding to probe. With the
route unclosed, the failure class of a short-minutiae image is genuinely
undetermined upstream, and fpbench choosing one would be choosing whether the
candidate looks strict or broken.
