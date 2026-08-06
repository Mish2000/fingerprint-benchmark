# Stage 8C — the canonical 6,000 comparisons under the qualified flx route

This directory is the committed evidence for one question:

> what raw scores and what execution outcomes does the flx route Stage 8B
> qualified produce, given exactly the same 6,000 pairs and the same 3,000
> `canonical_500` images SourceAFIS and NBIS were given?

**Outcome: `FLX_CANONICAL500_RAW_READY`.**

```
6,000 planned comparisons        6,000 immutable stored outcomes
6,000 raw scores                 0 algorithmic failures
0 blocking failures              clean canonical alignment
```

## What this is not

It is not a result about fingerprint recognition. There is no threshold here, no
decision, no eligibility, no metric, and no comparison with SourceAFIS or NBIS.
Nothing in this directory reports a minimum, a maximum, a mean, a median, a
percentile, a histogram, a distribution or an example score.

That is a deliberate limit, not an omission. The flx score is
`dot(texture) + dot(minutia)` in `[-2, 2]`, produced by an author-supplied
implementation of one DeepPrint variant, and nobody has published an operating
point on that scale. A threshold may not be chosen from the scores in this run
either, because SD300 is the evaluation set and fitting a parameter to it would
make the resulting rate an upper bound on nothing. Stage 8D has to freeze its
threshold source, comparator, boundary semantics and calibration status in a
separate, prior act (docs/adr/0076, docs/adr/0065).

The marker says so in machine-readable form:

```json
"permits_decisions": false,      "opens_stage_8d": true,
"prior_result_scores_read": false, "score_statistics_published": false
```

## The run

```
experiment       flx_canonical500_full_v1
algorithm        flx_deepprint_texminu_512_without_localization
integration      flx_deepprint_texminu_research_v1
run              run_902136b3b8ae   902136b3b8ae7274...
plan             plan_b1e805736760  6,000 jobs
result set       resultset_d63e523e0436
runtime bundle   runtime_6885b26bb4da
source commit    ec8881a34c8d6b00060ee5868c77aeaf9344c7cf
```

Every image came from the input set Stage 6A materialised, and every pair from
the manifest the reference SourceAFIS run used, row for row, in its order:

```
reference run    run_4c59fa02a6ab
reference plan   plan_b4ae66e91923
reference set    resultset_087b084fb8a8
cohort           sd300_50_subjects_test_22f8d52a7478
pair manifest    ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b
prepared set     prepset_be560e047991
```

The alignment report compares the two runs record by record — every field of
every one of the 6,000 pairs and every field of all 3,000 prepared entries,
positionally in the plan's order — rather than count against count. It is clean.

## The shape

| Pair kind | SD300A | SD300B | SD300C | Total |
| --- | ---: | ---: | ---: | ---: |
| `plain_self` | 500 | 500 | 500 | 1,500 |
| `roll_self` | 500 | 500 | 500 | 1,500 |
| `plain_roll_mated` | 500 | 500 | 500 | 1,500 |
| `plain_roll_non_mated` | 500 | 500 | 500 | 1,500 |
| **Total** | 2,000 | 2,000 | 2,000 | **6,000** |

`plain_roll_non_mated` is the manifest's own name for the kind. Calling it a
non-mated sanity check is reporting language and changes nothing about it.

## Two extraction counts, and why they differ

```
preprocess calls          12,000
logical extractions       12,000
physical forward rows     24,000
comparison calls           6,000
```

Both extraction numbers are true and they measure different things. 12,000 is
how many representations the run produced. 24,000 is how much arithmetic the
checkpoint did, because the pinned texture branch cannot process a batch of one:
one extraction feeds the identical preprocessed tensor twice, asserts the two
output rows are bitwise equal, and represents row 0 (docs/adr/0070,
docs/adr/0075).

Every one of the 6,000 stored results records its own counts, measured from the
route rather than assumed, and all 6,000 record two preprocess calls and two
logical extractions — including every SELF pair, where both sides point at the
same PNG and are still read, preprocessed and extracted independently.

## Operational facts

```
wall clock span         16,008.9 s
adapter per comparison  median 1,651.9 ms   min 1,481.5   p95 5,220.1   max 6,294.4
sequential              1 worker, 0 retries, job deadline 480 s
```

The timing spread is not a property of the route. The run executed on a laptop
that spent part of it on battery, where sustained CPU power is cut hard, and the
same comparison took roughly 1.5 s plugged in and roughly 4.8 s on battery. That
is why the p95 is three times the median. **These figures must not be read as a
throughput measurement of flx**, and nothing in this stage rests on them: the
route is bitwise deterministic at tolerance 0, so clock speed changes how long a
comparison takes and not what it returns.

## Files

| File | What it is |
| --- | --- |
| `run_902136b3b8ae.json` | the research receipt, as the engine published it |
| `research-receipt.json` | the same receipt, under the name a reader looks for |
| `research-finalization.json` | the general chain's last-written marker |
| `algorithm-validation.json` | the flx pass over all 6,000 stored results |
| `alignment-report.json` | the record-by-record comparison with the reference run |
| `operational-summary.json` | counts, timings and failure codes — no score |
| `runtime-provenance.json` | what ran, on what, bound to what |
| `stage-8c-finalization.json` | the last file written, binding all of the above |

Deliberately absent: the checkpoint, the source archive, SD300 images, prepared
PNGs, 299×299 tensors, embeddings, representation hashes, raw score rows, the
ResultSet, worker files and absolute paths. The verifier walks every published
document as data and refuses a forbidden key at any depth.

## Verifying this

Two different things, and the difference matters.

**Evidence-only** needs no dataset, no checkpoint, no torch and no workspace. It
reads these documents, rebuilds all four flx profiles from the repository's own
source, re-hashes the exact bytes and checks the documents agree with each other:

```bash
make stage8c-evidence
```

It makes no claim that the algorithm was executed — `algorithm_executed` is
always false — and CI does not run the 6,000 comparisons.

**Workspace** verification needs SD300, the prepared set, the raw ResultSet, the
checkpoint and the 2.06 GB runtime bundle, and verifies the experiment itself.
See `docs/experiments/flx-canonical500-raw.md`.

## One honest note about the chain

`research-finalization.json` names `f1de94e` as its verifier commit, while
`stage-8c-finalization.json` names the commit that published this directory. The
research chain was finalised first; two defects in Stage 8C's own post-checks
were then fixed, and the regenerable artefacts were re-derived under the newer
code through the documented refresh path. The immutable artefacts were not
rewritten, which is why the two commits differ. Both are ancestors of the
publication and both can be checked out; the marker binds the research
finalization by fingerprint rather than by commit, so the chain still closes
(docs/adr/0017).
