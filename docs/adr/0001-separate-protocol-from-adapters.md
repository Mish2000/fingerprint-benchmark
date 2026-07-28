# 0001 — The protocol is independent of the algorithm

## Status

Accepted. Implemented in `fpbench.protocols` and `fpbench.storage`.

## Context

The study compares several fingerprint recognition algorithms — SourceAFIS,
NBIS/Bozorth3 and potentially others — on the same experiment: 50 subjects,
ten fingers each, four comparison stages, across three SD300 releases.

If each algorithm decided for itself which images to use and how to pair them,
the comparison between algorithms would be meaningless: a difference in results
could always be a difference in the experiment rather than in the matcher. It
would also be impossible to say that two runs a month apart tested the same
thing.

## Decision

The harness owns the experiment. Cohort selection and pair generation happen
once, produce `cohort.json` and `pairs.parquet`, and every algorithm consumes
exactly those files.

Concretely, the dependency direction is enforced by module boundaries:

```
core        imports nothing from the project
datasets    imports core                    (never protocols)
protocols   imports core                    (never adapters)
adapters    imports core                    (never protocols)
storage     imports core
execution   imports all of the above
evaluation  imports core and storage        (never adapters)
```

A protocol never learns that algorithms exist; an adapter never learns which
stage it is serving or what a genuine pair is.

## Alternatives

**Let each adapter build its own pairs.** Rejected: it makes cross-algorithm
comparison unsound and duplicates the eligibility logic per algorithm.

**Generate pairs per run, in memory.** Rejected: the pair set then depends on
the code version at run time, so results from different weeks are not
comparable, and a failed run cannot be resumed.

## Consequences

* The pair manifest is a first-class artefact and must be versioned and
  preserved with the results that reference it.
* Adding an algorithm cannot change the experiment — which is the point, but it
  also means an algorithm that genuinely needs a different input (a different
  resolution, say) needs a new *execution profile*, not a special case.
* Every stage in the pipeline can be tested in isolation, because none of them
  needs a working matcher to run.
