# 0012 — Run progress is derived, never stored as a counter

## Status

Accepted. Implemented in `fpbench.execution.progress` and
`fpbench.core.run_state_models`.

## Context

The obvious way to track a long run is a counter: increment it as each job
finishes, read it to see how far along you are. It is also the way to end up
with a number nobody can trust.

A counter and the files it claims to describe can disagree for entirely ordinary
reasons — the process died between writing a result and updating the counter, the
counter was written first and the result never landed, someone deleted a result
by hand, two runs shared a directory. The failure is silent in the worst possible
way: the counter says 6,000 and the analysis proceeds on 5,999 comparisons.

The same problem afflicts a persisted `RUNNING` state. After a crash, nothing on
disk can tell you whether a process is still alive, so a stored `RUNNING` is a
claim that stops being true the moment the machine reboots.

## Decision

**Progress is recomputed from the immutable plan and the result files on disk,
every time it is asked for.** There is no counter anywhere, and `RunState` has no
`RUNNING` member.

```
RunState.PLANNED    no results yet
RunState.PARTIAL    some planned jobs have results, some do not
RunState.COMPLETE   every planned job has a readable result, nothing verified it
RunState.VERIFIED   a clean audit ran and its completion manifest is on disk
RunState.INVALID    an extra, unreadable or misattributed result was found
```

`RunProgress` may be cached to `derived/progress.json`, and that file may be
overwritten or deleted freely — regenerating it costs one pass over a directory.
Nothing reads it to make a decision.

Two invariants hold whenever nothing is wrong:

```
stored_results == successful_results + failed_results
planned_jobs   == stored_results + missing_results
```

The first breaks precisely when a result file cannot be read, which is what
`unreadable_results` exists to surface and what forces the state to `INVALID`.

`inspect_run_progress` is the cheap question and `audit_run` is the expensive
one, but the cheap one is still not allowed to guess: it may only report
`VERIFIED` when a completion manifest exists *and* names this run and this plan.
A stale manifest from an earlier plan must not vouch for results it never saw.

`SequentialRunExecutor` follows the same rule. Its `remaining_jobs` count comes
from the filesystem rather than from its own loop, because a previous
invocation's work counts too and only the files know about it.

## Alternatives

**Maintain a counter and reconcile it periodically.** Rejected: reconciliation is
the derivation, so the counter adds a second source of truth for no benefit.

**Persist a `RUNNING` state with a heartbeat.** Rejected as premature. It buys
something only for concurrent or distributed execution, which stage 3B
deliberately does not have, and it would need liveness detection to mean
anything.

**Trust the executor's return value.** Rejected: a summary describes one
invocation. Asking "is this run finished?" must not depend on having witnessed
every invocation.

## Consequences

* Reading progress is O(planned jobs) in file existence checks, plus one read per
  stored result to classify it. At 6,000 jobs that is seconds; if it ever
  matters, the cached snapshot is already the answer.
* Deleting a result file moves the state backwards, which is correct: the run
  genuinely is less finished than it was.
* No bookkeeping can drift out of sync with reality, because there is no
  bookkeeping.
