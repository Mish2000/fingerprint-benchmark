# 0010 — An adapter is told nothing about the comparison it is performing

## Status

Accepted. Implemented in `fpbench.core.execution_models.ComparisonContext`,
`fpbench.execution.jobs` and `fpbench.execution.runner`.

## Context

The harness knows, for every comparison, whether the two images are from the
same finger. That is the entire point of the protocol. It is also information
that must not reach the matcher.

The risk is not that someone writes a cheating adapter on purpose. It is that
the information leaks in and gets used without anyone noticing:

* a readable `job_id` like `sourceafis_sd300b_plain_roll_00001000_f01` tells a
  wrapper the stage and the subject;
* passing the `ComparisonPair` "because the adapter might want the pair id for
  logging" hands over `ground_truth` in the same object;
* an adapter that retries harder on pairs it expects to match will produce
  better numbers, and nothing in the results will say why.

An adapter that *cannot* know is not a matter of discipline. It is a property
of the types.

## Decision

`compare()` receives exactly two prepared images and an operational context:

```python
def compare(left: PreparedImage, right: PreparedImage, context: ComparisonContext)
```

`ComparisonContext` carries `run_id`, `job_id`, `attempt`,
`working_directory`, `artifact_directory`, `timeout_seconds` and
`deterministic_seed`. It does **not** carry `pair_id`, `protocol_stage`,
`ground_truth`, `subject_id`, `finger_position`, `threshold` or
`decision_profile`.

`PreparedImage` is held to the same rule: resolution, media type, digest and
checksum status, but no subject, no finger, no impression.

`job_id` is `job_` plus 16 hex characters of a digest. Its opacity is the point
— a readable id would reintroduce exactly what the context excludes. The same
applies to `run_id`.

The adapter also never applies a threshold and never returns a decision; it
returns a raw score and the direction that score runs in (docs/adr/0003).

## Alternatives

**Pass the pair, trust the adapter.** Rejected: it makes correctness a matter
of every future adapter author's discipline, including authors of third-party
wrappers.

**Pass the pair id but not the ground truth.** Rejected: `pair_id` encodes the
stage (`..._mated`, `..._plain_self`), so it *is* the ground truth in a thin
disguise.

**Readable job ids for debugging.** Rejected as a default. Debugging joins
`job_id` back to `pair_id` through the stored result, which costs one lookup
and leaks nothing into the adapter.

## Consequences

* Debugging a specific comparison means a join rather than reading a filename.
  The result record carries both ids, so the join is trivial.
* An adapter cannot implement per-stage behaviour even where that would be
  legitimate — a genuinely different execution profile is the supported way to
  express such a difference, and it is recorded in the run fingerprint.
* The property is testable, and is tested: `ComparisonContext` and
  `PreparedImage` are asserted to have no forbidden field, `job_id` is asserted
  to leak no substring of the pair, and a fake adapter in the runner's
  integration tests inspects the context it actually received.
