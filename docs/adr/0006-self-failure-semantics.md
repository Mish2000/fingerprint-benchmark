# 0006 — An operational failure is not a non-match

## Status

Accepted. Not yet implemented — the failure taxonomy belongs to the runner.
The SELF-filtering logic that depends on it exists in
`fpbench.protocols.self_filtering`.

## Context

Two very different things can prevent a comparison from being called a match:

* the algorithm ran, produced a score, and the score did not reach the
  threshold;
* the algorithm never produced a usable score at all — the image would not
  decode, no template could be extracted, the process timed out or crashed, a
  dependency was missing.

Collapsing both into `False` makes the SELF stages uninterpretable. An image
that fails to match *itself* is either a genuine matcher limitation or a broken
input, and those call for entirely different follow-up.

## Decision

Execution status and biometric decision are recorded separately:

```
execution_status: success        execution_status: failure
decision: non_match              decision: unavailable
                                 failure_code: template_extraction_failed
```

With a shared failure taxonomy:

```
INPUT_INVALID              QUALITY_REJECTED       TIMEOUT
IMAGE_DECODE_FAILED        TEMPLATE_EXTRACTION_FAILED   PROCESS_CRASHED
PREPARATION_FAILED         MATCHING_FAILED        DEPENDENCY_MISSING
NO_SCORE                   UNSUPPORTED_RESOLUTION INTERNAL_ERROR
```

For the SELF-filtering rule the protocol asks for, both count as a failure: a
finger that fails either SELF stage — for either reason — is excluded from the
filtered PLAIN-ROLL result. Which pair ids count as failed is decided by the
analysis layer and passed into `collect_failed_fingers`; the filtering code
itself does not interpret results.

A summary report for the supervisor may present both as "rejected". The
database and the analysis must always keep them apart.

## Alternatives

**Raise an exception on failure.** Rejected: an unmatched image is data, not a
crash. A failed comparison must be stored and counted like any other, or the
denominators are wrong.

**One `success: bool` field.** Rejected: it is exactly the conflation this ADR
exists to prevent.

## Consequences

* Every reported rate must state its denominator. "12 of 500 rejected" is
  ambiguous until it says how many of those never produced a score.
* Retry policy depends on the failure code: `TIMEOUT` may be worth retrying,
  `INVALID_IMAGE` never is, and `NON_MATCH` is not a failure at all.
* Failure analysis becomes a first-class output, not an afterthought — for the
  SELF stages it may be the most informative result the study produces.
