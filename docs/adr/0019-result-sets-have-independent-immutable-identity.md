# 0019 — The ordered collection of raw result hashes has its own immutable identity

## Status

Accepted. Implemented in `fpbench.core.result_set_models`,
`fpbench.execution.result_set` and `fpbench.storage.result_set_store`.

## Context

The next stage applies thresholds to stored scores and produces decisions. A decision
record has to be able to say what it was derived from, and to have that claim be
checkable later — otherwise re-running an analysis against a directory whose contents
have moved produces different numbers with no indication that anything changed.

What exists today cannot carry that claim:

* `run_id` identifies the *inputs* — pairs, algorithm, environment, profile. It says
  nothing about the outputs, and two runs with the same id and different results are
  supposed to be impossible rather than detectable.
* `completion.json` says an audit passed. Its fingerprint covers the audit's *counts* and
  findings, not the results themselves; a run whose scores were all replaced with other
  valid scores would produce a different audit fingerprint only if the counts moved.
* The result files are one per job, in a directory. A directory is not a record.

## Decision

**Every finished research run gets a result set: the ordered list of its result hashes,
with a fingerprint of its own.**

```
results/<run_id>/result-set/
├── manifest.json      the identity
└── results.parquet    ordinal, job_id, result_hash — one row per planned job
```

`result_set_id` is `resultset_<12 chars>` of a digest over the result-set schema version,
the run fingerprint, the plan fingerprint, the **runtime bundle fingerprint**, the ordered
`(ordinal, job_id, result_hash)` triples, and the success and failure counts. It excludes
the creation timestamp, so the same evidence indexed twice is recognisably the same
evidence.

Three properties follow, and they are the whole reason for the record:

* **One changed score changes the identity.** `result_hash` is the digest of the entire
  stored record, so a different score, a different failure code, even a different timing
  produces a different result set.
* **Order is part of the identity.** The plan's ordinal is how a partially executed run is
  described precisely; two runs holding the same results in a different order are not
  interchangeable.
* **The runtime is part of the identity.** The same pairs scored by two builds of the same
  matcher are two bodies of evidence ([ADR 0018](0018-external-runtime-assets-are-content-addressed.md)).

The store re-reads every result file and re-derives every hash before writing, and again
on verification. An index assembled from numbers handed to it would agree with its caller
rather than with the evidence. It also refuses a run holding a result the set does not
account for, refuses duplicates, and refuses to overwrite: a different set under the same
run is a conflict, never a correction.

## Alternatives

**Extend `completion.json`.** Rejected: completion answers "was this run audited?", which
is a claim about process. Overloading it with a claim about content would make one record
carry two lifetimes — an audit can legitimately be re-run, and the evidence it inspected
must not change underneath.

**Cite the run id and re-audit each time.** Cheap and insufficient. It proves the results
are internally consistent *now*; it cannot prove they are the results an analysis used
last week.

**Store the scores in the manifest.** Rejected. It would create a second place the truth
lives, and the first thing a downstream reader would have to stop believing. The set is an
index, deliberately.

**Fingerprint the raw files byte for byte.** Rejected: parquet files carry a creation
timestamp in their metadata, so two byte-identical result *records* written a second apart
would not compare equal. `raw_result_hash` covers the record, which is what matters.

## Consequences

* The decision layer will reference `result_set_fingerprint`, not `run_id`, and can verify
  it at any point afterwards.
* Deleting or adding a result file makes the stored set fail verification, which turns the
  run `INVALID` rather than letting a stale identity vouch for changed evidence.
* Writing the set for 6,000 results costs one full pass over the raw files. It happens once,
  at finalisation.
* A run that is `VERIFIED` but has no result set is a real and reportable state
  (`CORE_VERIFIED`): the audit passed, and nothing is yet citable.
