# 0013 — A failed comparison does not make a run incomplete

## Status

Accepted. Implemented in `fpbench.execution.batch_runner`,
`fpbench.execution.audit` and `fpbench.execution.completion`.

## Context

Real matchers fail on real images. A card scan with too little ridge detail
yields no template; a tool times out; an image the harness considers fine is
rejected by the algorithm. On 6,000 comparisons some number of these is expected,
and on the SELF stages the failures may be the most interesting result the study
produces.

So a question has to be settled before any of it runs: **is a run with 30 failed
comparisons finished, or broken?**

Answering "broken" would be catastrophic. It would mean the run can never be
completed, that the executor should stop at the first difficult image, and that
the only way to finish is to quietly exclude whatever refuses to score — which
is exactly how a benchmark ends up reporting results for the easy subset.

Answering "finished, ignore it" is the other trap: it conflates a comparison that
scored below threshold with one that never produced a score, and the difference
is the whole point of the SELF stages (docs/adr/0006).

## Decision

Three concepts, kept separate and never collapsed:

```
comparison success/failure   did this algorithm produce a score for this pair?
run completeness             does every planned job have a valid result record?
run integrity                do the stored results agree with the plan?
```

A run is **complete** when every planned job has a readable, well-attributed
result record. That record may say `SUCCESS` with a score or `FAILURE` with a
code; either satisfies completeness.

A run is **verified** when a clean audit says so. `RunCompletion` records
`success_count` and `failure_count` separately, and `failure_count > 0` is a
perfectly ordinary completed run.

Concretely:

* The executor continues past a comparison failure and records it.
* The audit does not treat a failure as an issue. `is_clean` is about missing,
  extra, unreadable or misattributed results — never about scores.
* What *does* stop a run is a conflict: `ResultConflictError`,
  `PlanConflictError`, a corrupt result, a job that does not match its pair, a
  failed preflight. Those mean the directory can no longer be trusted, and
  continuing would mix incomparable results together.
* `KeyboardInterrupt`, `SystemExit` and `GeneratorExit` are never caught. An
  interrupt is not a comparison outcome and must not be recorded as one.

## Alternatives

**Fail the run on the first comparison failure.** Rejected: it makes the harness
unusable on real data and biases every result toward images that happen to be
easy.

**Retry failures until they succeed.** Rejected for stage 3B, and it is not a
substitute for this decision anyway: a genuinely unmatchable image would retry
forever. Retry policy belongs to the failure taxonomy — `TIMEOUT` may deserve one,
`INPUT_INVALID` never does — and is a later stage.

**Store failures elsewhere, outside the result set.** Rejected: it makes every
reported rate depend on which file you happened to read, and the denominators
would silently exclude the hardest cases.

## Consequences

* Every reported figure must state its denominator, and distinguish "did not
  match" from "produced no score". A summary that groups them may be acceptable
  for a supervisor; the database and the analysis must not.
* A run that verifies is not a run that succeeded. `failure_count` has to be read
  alongside `success_count`, and a high failure count is a finding to
  investigate, not a run to discard.
* Failure analysis is a first-class output rather than an afterthought — on the
  SELF stages it may be the primary one.
