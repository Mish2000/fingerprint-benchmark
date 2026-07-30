# 0011 — Execution plans are immutable and deterministically derived

## Status

Accepted. Implemented in `fpbench.core.execution_plan_models`,
`fpbench.execution.planner` and `fpbench.storage.plan_store`.

## Context

A run is 6,000 comparisons. Between planning them and finishing them there will
be interruptions, and possibly weeks. Two questions have to be answerable at any
point in that stretch:

* **which comparisons was this run supposed to perform?**
* **have all of them been performed exactly once?**

Neither can be answered by counting result files. 5,999 files look exactly like
6,000 files unless something independent says how many there should have been.
And a plan that could be edited — to add a pair, to drop a stubborn one — would
answer the first question differently depending on when it was asked.

There is also a subtler hazard. If the plan's order came from whatever order the
pairs happened to arrive in, then two people planning the same experiment would
get different job ids, the same run would resume differently on different
machines, and a partially executed run could not be described at all.

## Decision

A plan is a **pure function of the run and its pair manifest**, frozen once and
never modified.

Determinism is imposed, not inherited:

```
1. protocol stage    SELF stages first, then mated, then non-mated
2. release           SD300A, SD300B, SD300C
3. pair_id           lexicographic tie-break
```

Shuffling the input pairs cannot change the plan, the job ids, or the
`plan_fingerprint`. Nor can the wall clock: `created_utc` is stored but excluded
from every digest.

`plan_fingerprint` covers the plan schema version, the run fingerprint, the pair
manifest hash, the job manifest hash, the job count, the stage and release
counts, and the ordered job fingerprints. `plan_id` is its first twelve
characters.

Enforced consequences:

* The planner **refuses** a pair manifest whose protocol, cohort or hash does not
  match the run. A plan built from the wrong manifest would execute perfectly
  and produce results nobody could attribute.
* Duplicate `pair_id`, `job_id` or `job_fingerprint` is a `PlanningError`. The
  planner never silently keeps the first of a pair — that would reintroduce
  dependence on input order through the back door.
* Job identity comes only from `build_comparison_job`. The planner mints no ids
  of its own, so there is exactly one answer to "which job covers this pair?".
* `PlanStore` has no `overwrite`. Re-storing the same plan is a no-op; a
  different plan under the same run is a `PlanConflictError`.
* `jobs.parquet` is written before `plan.json`, because `plan.json` is the marker
  that the plan is complete. A crash between the two leaves something visibly
  unfinished rather than a definition pointing at jobs that were never written.
* Reading a plan **recomputes** its job manifest hash. A hand-edited
  `jobs.parquet` fails loudly instead of quietly redefining the experiment.

Stage order is not arbitrary: running both SELF stages before any
cross-impression comparison means even a partial run already says which fingers
are usable, which is the first thing worth knowing when a matcher behaves oddly.

## Alternatives

**Plan lazily, job by job, as the run proceeds.** Rejected: there would be
nothing to audit against, and "have all comparisons been performed?" would be
unanswerable.

**Allow a plan to be amended.** Rejected. Since the run's own identity already
covers its pair manifest, a legitimately different set of comparisons *is* a
different run and lands in a different directory. An amendable plan would only
ever be used to paper over a mistake.

**Keep the input order.** Rejected: it makes the plan, and therefore every job
id, depend on how the caller happened to iterate.

## Consequences

* Changing the pair manifest produces a new run, not a modified plan. Old
  results stay valid and stay where they are.
* The plan is an artefact that must be preserved with the results — it is the
  only statement of what the run was for.
* Because a plan cannot change, progress and integrity both become simple
  set operations against it: which planned jobs have results, and which results
  belong to no planned job.
* Any future change to a fingerprint rule invalidates existing run and plan ids.
  `tests/regression/test_execution_plan_fingerprint.py` pins them so that such a
  change has to be acknowledged rather than discovered later.
