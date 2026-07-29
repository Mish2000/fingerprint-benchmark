# 0009 — One immutable result file per job

## Status

Accepted. Implemented in `fpbench.storage.result_store` and
`fpbench.execution.runner`.

## Context

A run is 6,000 comparisons per algorithm per release. Some of them will be slow,
some will fail, and the machine will be interrupted at some point — a crash, a
reboot, a laptop lid. Two questions follow from that, and they have to be
answered together:

* where does a result go, and
* what happens when the same job is executed twice?

The obvious layout is one growing table per run. It is also the wrong one.
Parquet has no safe append: adding a row means rewriting the file, so an
interruption mid-write can destroy results that were already complete, and two
workers can never touch the same run.

The obvious answer to the second question — overwrite, last write wins — is
worse. Silently replacing a stored measurement is how a study loses the only
copy of something it cannot recompute.

## Decision

```
results/<run_id>/run.json
results/<run_id>/raw/jobs/<job_id>.parquet    exactly one row
```

* **One file per job.** Written to a temporary sibling and renamed, so a
  partial file never appears under its real name.
* **No overwrite, at all.** `ResultStore.write_raw_result` has no `overwrite`
  parameter and no `force`. An existing file raises `ResultConflictError`.
* **Resume is the runner's job, not the store's.** Before doing any work the
  runner looks for a stored result under the same `run_id` and `job_id`:
  * same `job_fingerprint` → `SKIPPED_EXISTING`. No preparation, no adapter
    call, no write.
  * different `job_fingerprint` → `ResultConflictError`.
* **`run.json` is idempotent.** Re-ensuring the same run is a no-op; a
  different run claiming the same id is a conflict.
* Every job file carries `schema_version`, `result_hash`, `run_id`, `job_id`,
  `job_fingerprint`, `pair_manifest_hash`, `algorithm_fingerprint`,
  `execution_profile_hash`, `fpbench_version`, `created_utc` and `row_count` in
  its parquet metadata, so a file separated from its directory can still be
  attributed.

This works because `run_id` and `job_id` are derived, not assigned: identical
inputs produce identical ids, so resuming lands in the same place by
construction rather than by bookkeeping.

## Alternatives

**One parquet file per run.** Rejected: no safe append, no resume granularity,
and no path to parallel execution.

**A database.** Solves concurrency properly, at the cost of a service to
install, configure and back up. Revisitable — the store is narrow enough to
swap — but not justified by 6,000 rows.

**Allow overwrite behind a flag.** Rejected. A flag that exists gets used, and
the failure mode is a silently changed result rather than a loud error.

## Consequences

* A run directory holds thousands of small files. That is fine on any modern
  filesystem, and a consolidated table can be generated from them whenever one
  is wanted — as a derived artefact, deletable and regenerable.
* Changing anything load-bearing produces a *new* run rather than mutating the
  old one. Disk grows monotonically; that is the intended trade.
* Because nothing is ever overwritten, parallel execution can be added later
  without a locking scheme: two workers on different jobs cannot collide, and
  two workers on the same job produce the same bytes and the same conflict
  check.
