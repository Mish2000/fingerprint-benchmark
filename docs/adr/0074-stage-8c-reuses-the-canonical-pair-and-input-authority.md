# 0074 — Stage 8C reuses the canonical pair and input authority

*Status: Accepted — 2026-08-05, stage 8C*

## Context

Stage 8C runs a third algorithm over the experiment SourceAFIS and NBIS already
ran. The question it answers is "what does the qualified flx route score on
these 6,000 pairs?", and that question only has an answer if *these* is the same
word in all three sentences.

Stage 7C established the pattern for the second algorithm and it holds here
unchanged: the reference run `run_4c59fa02a6ab` owns the cohort, the 6,000-row
pair manifest and its order; the prepared image set `prepset_be560e047991` owns
the 3,000 immutable 500 ppi PNGs. Neither is re-derived, and the
`CanonicalRunAlignmentReport` compares the two sides record by record rather
than count by count (docs/adr/0051, docs/adr/0054).

What is new is that Stage 8C cannot reuse the reference run's *execution
profile*. `canonical_500_lanczos3_60s_v1` gives an adapter 60 seconds per
comparison. The flx route measured 0.763 s per extraction, 2.8 s of worker
startup and 1.1 s of model load on the pinned runtime, and the generic engine
gives the adapter one deadline covering the whole job — two preprocess calls,
two extraction calls and one comparison. Stage 7C's
`require_execution_controls_equal` requires the candidate run to reproduce the
reference profile id, timeout and parameters exactly, which for flx would be a
budget chosen for a Java matcher applied to a PyTorch one.

So "same experiment" has to be stated precisely enough to separate the inputs,
which must be identical, from the operational budget, which cannot be.

## Decision

Stage 8C reuses the reference run's **input authority** and declares its own
**operational budget**.

Identical, and checked record by record before a run exists:

```
dataset and protocol identity      cohort id
pair manifest hash                 6,000 pair ids, in the plan's order
pair kind, release, subject, finger position
left and right image identity, probe/gallery direction
replicate index
prepared set id and fingerprint    all 3,000 prepared entries and their hashes
transform profile and its runtime fingerprint
runtime materialization policy
```

Deliberately not identical:

```
execution profile id      flx_canonical500_sequential_no_retry_v1
job deadline              480 s, covering 2 preprocess + 2 extract + 1 compare
                          plus a 60 s orchestration margin
algorithm, adapter, integration and runtime bundle
```

The check is a new algorithm-neutral function,
`require_canonical_input_controls_equal`, beside the existing
`require_execution_controls_equal` rather than a widening of it. Stage 7C's
function keeps its exact meaning, so no NBIS or SourceAFIS fingerprint moves.

`job_id` is excluded from alignment on purpose. Job ids are derived from the run
that owns them, so a new run necessarily has new ones; comparing them would
report a difference that is required to exist.

## Alternatives considered

**Reuse `canonical_500_lanczos3_60s_v1` unchanged.** A 60 s job deadline
against a route whose own per-operation deadlines already sum to 420 s means the
run's outcome depends on which timeout fires first. The stage would be measuring
its own orchestration.

**Widen `require_execution_controls_equal` with a flag.** The function is shared
with Stage 7C, and a flag that makes the timeout optional makes it optional for
NBIS too. A second, narrower function says exactly what Stage 8C claims, and
Stage 7C's guarantee is unchanged by construction.

**Give Stage 8C its own alignment engine.** The row-by-row comparison is the
part with teeth and it is already algorithm-neutral. A second copy would be a
second place for "the same pairs" to be defined, and they would eventually
disagree.

**Change the reference run's profile so all three share one.** The reference run
is finalised, published and cited by four downstream chains. It does not move.

## Consequences

The alignment report Stage 8C stores has the same schema and the same
fingerprint rule as Stage 7C's, so a reader who has verified one can read the
other without learning a new document.

A reviewer comparing flx timings with SourceAFIS or NBIS timings is comparing
runs with different deadlines. The operational summary says so, and no
biometric claim rests on it — Stage 8C publishes no metric at all
(docs/adr/0076).

The pair manifest is loaded with `allow_creation=False`. A workspace that has
lost the manifest is an error, not an invitation to build a new one that would
happen to have the same shape and different contents.
