# 0020 — Research completion is external to batch execution, and follows runtime revalidation

## Status

Accepted. Implemented in `SequentialRunExecutor.execute(finalize=...)`,
`fpbench.execution.research` and `fpbench.experiments.sourceafis_native_full`.

## Context

`SequentialRunExecutor` audits and writes `completion.json` as soon as it finds no job
outstanding. For a dummy run that is exactly right: between the last comparison and the
audit there is nothing that could have changed.

For a research run there is. The executable may have been replaced during the hours the
run took, the working tree may no longer be the commit the run was created from, and the
results — individually valid — may misdescribe the pipeline that produced them. All three
have to be checked *before* anything says the run is verified.

The executor cannot do the checking. It knows about plans, jobs and result files, and it
must not learn about runtime bundles or git: a batch loop that had to understand
provenance is a batch loop that can get provenance wrong, and it would be
algorithm-specific machinery in the one place [ADR 0007](0007-no-algorithm-branching-in-runner.md)
forbids it.

## Decision

**`execute(finalize=True)` stays the default; a research run passes `finalize=False` and
a separate finalizer does the work in a fixed order.**

With `finalize=False` and every result present, the summary reports
`completed=True, verified=False` and no completion manifest exists. The run is finished
and not yet trustworthy, and those are visibly different states.

Finalisation then runs, in this order, and stops at the first failure:

1. verify the runtime bundle's full SHA-256;
2. verify the source revision is the one the run was created from;
3. verify the working tree is clean;
4. core `audit_run()` — one sound result per planned job;
5. algorithm evidence validation — every result names the right pipeline, runtime,
   source revision and resolution;
6. write the immutable result set ([ADR 0019](0019-result-sets-have-independent-immutable-identity.md));
7. write the completion manifest;
8. write the operational summary (derived, disposable);
9. write the sanitised research receipt;
10. read all of it back.

The order is not arbitrary. Provenance first, because a failure there invalidates
everything after it. The result set before the completion, because completion is the
strongest claim and must not exist for a run whose evidence could not be indexed. The
receipt last, because it cites all of the above by fingerprint. **Any failure leaves the
completion, the result set and the receipt unwritten** — a run that cannot be finalised is
not a run with a missing file, it is a run whose results cannot be attributed.

This produces a state stronger than `VERIFIED`, reported by `inspect_research_run()`:

```
NOT_PREPARED → PREPARED → PARTIAL → RESULTS_COMPLETE → CORE_VERIFIED → RESEARCH_READY
                                                    ↘ INVALID
```

`RESEARCH_READY` requires the whole chain, re-tested from the files every time it is
asked for. Like run progress, nothing is cached and no manifest is taken at its word
([ADR 0012](0012-run-progress-is-derived.md)).

## Alternatives

**Teach the executor about runtime bundles.** Rejected: it makes the generic executor
depend on a provenance model that only research runs have, and every future kind of
pre-completion check would land in the same place.

**A callback the executor invokes before finalising.** Rejected as the same coupling with
extra indirection; the executor would still own the ordering it has no basis to decide.

**Always require external finalisation.** Rejected because it would change stage 3B
behaviour for no benefit. The dummy full run has nothing to revalidate, and a default
that forces every caller to remember a second step is a default that gets forgotten.

**Write the completion first and retract it on failure.** There is no retraction.
`completion.json` is immutable by design ([ADR 0005](0005-immutable-raw-results.md)), and
a manifest that existed for even a moment saying a run was verified is a manifest someone
could have copied.

## Consequences

* Stage 3B behaviour is bit-for-bit unchanged: the default is still `True` and every
  existing test passes without modification.
* A research run has an extra command. `execute` can be run as often as it takes;
  `finalize` is run once, at the end, and is the only thing that can produce a receipt.
* A run interrupted between execution and finalisation is `RESULTS_COMPLETE` — an honest
  state with an obvious next step, rather than a run that looks finished.
* The finalizer is application-layer code (`fpbench.experiments`), which is where an
  algorithm-specific validator is allowed to live.
