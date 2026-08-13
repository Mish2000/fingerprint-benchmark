# Stage 11B — VeriFinger 2025.2 over the canonical 500 ppi SD300 comparisons

`VERIFINGER_CANONICAL500_RAW_COMPLETE`. VeriFinger 2025.2 is the benchmark's
fourth algorithm, and this directory is what that claim rests on: 6,000 raw
outcomes over the same pairs, in the same order, over the same pixels that
SourceAFIS, NBIS and flx already ran.

Stage 11A qualified a *candidate* — seventeen gates, on artifact evidence and one
bounded local run, with no production surface anywhere. Stage 11B turns that
candidate into an algorithm and then runs it.

## What ran

```
prepset_be560e047991                       the same 3,000 canonical 500 ppi PNGs
      |
      v
verifinger_java_subprocess                 one JVM per comparison
      |
      v
VeriFinger 2025.2, official Java binding   verify(reference, candidate)
      |
      v
6,000 stored raw outcomes                  immutable, and never a threshold

run_52731bb3407e / plan_0a66249b7412 / resultset_960baecb83b8
```

Aligned row for row against `run_4c59fa02a6ab` — the same pair manifest
`ee4d942e…`, the same cohort `sd300_50_subjects_test_22f8d52a7478`, 500
comparisons in every one of the twelve release-and-stage cells. Nothing here
selects a cohort, generates a pair or writes a PNG: the pair manifest is loaded
with `allow_creation=False`, and a `CanonicalRunAlignmentReport` compares the two
runs record by record — every field of every pair and every field of all 3,000
prepared entries, positionally in the plan's order — rather than count against
count.

Left is the reference and right is the candidate, fixed. No reversal, no maximum
of the two orderings, no averaging, no sorting of paths. Stage 11A observed
symmetry on vendor fixtures; an observation is not a licence to reorder.

## What came out

```
6,000 comparison attempts    6,000 stored outcomes    0 missing    0 duplicate
5,919 scores
   81 algorithm failures     0 infrastructure failures
12,000 logical extractions   6,000 verify invocations  6,000 JVM processes
```

| engine status | rows | |
|---|---:|---|
| `OK` | 4,442 | a score |
| `MATCH_NOT_FOUND` | 1,477 | **also a score** |
| `BAD_OBJECT` | 81 | no score |

The 1,477 `MATCH_NOT_FOUND` rows are the point of the whole score route.
VeriFinger's own 1:1 sample sets `MatchingThreshold = 48`; the bridge keeps that
so upstream's route is reproduced exactly, and then fpbench reads the integer
score under `MATCH_NOT_FOUND` just as it does under `OK`. Those 1,477 are
successful comparisons that scored below the vendor's own threshold, and treating
them as failures — or as zeros — would have been fpbench choosing an operating
point by accident.

The 81 `BAD_OBJECT` rows are VeriFinger declining a print: a quality threshold it
set itself, a template it would not build. That is a property of real
fingerprints, it is counted, and it was not "fixed" to reach 100 % coverage. The
requirement was 6,000 *outcomes*, never 6,000 scores.

**No failure was recorded as a score of zero**, and no infrastructure failure was
recorded at all — a licence that was refused, a model file that moved, an engine
fault or a JVM that died would each have blocked the result set.

Timings, per comparison, including JVM startup, licence acquisition, engine
construction, two extractions and one match: median 1,775 ms, p99 2,051 ms, max
3,652 ms, against a 180-second job deadline chosen from qualification and smoke
timings before SD300 was opened. Wall clock 10,594 s.

## The runtime this rests on

Seventeen components — seven native libraries, two model data files and the eight
jars actually on the classpath — each with a size, a SHA-256 and a path relative
to the SDK archive. Each was re-hashed before the run and again after it, re-read
out of the pinned archive to prove where it came from, and checked cheaply before
every one of the 6,000 comparisons. Drift stops the run and is never recorded as
a biometric failure.

Stage 11A pinned ten of the seventeen. `NMediaProc.dll`, `NDevices.dll` and five
jars were loaded by the engine and unpinned until now; the qualification harness
put every jar in `Bin/Java` on the classpath, which meant a MySQL driver and a
Swing look-and-feel were on the classpath of a fingerprint comparison. The
production route names its dependencies.

Every one of the 6,000 stored results carries the same runtime manifest
fingerprint `0f2aed19…`, so a run whose engine changed halfway would be visible
rather than plausible.

The 4.7 GB the manifest describes lives in a local artifact store outside this
repository. Nothing published here is a vendor byte, a licence, a serial or a
machine path.

## What is deliberately not here

No mean, no median score, no histogram, no ROC, no EER, no FMR, no FNMR, no
accuracy, and no statement about which algorithm is better. Stage 11B produces
raw outcomes; a threshold, a calibration and a metric are later layers over these
stored scores.

The four algorithms now have four raw result sets and no common operating point.
VeriFinger's 48 is a vendor scale anchor, not something comparable to SourceAFIS's
documented 40 or to NBIS's — and choosing one from these scores would fit a
parameter to the evaluation set.

The prohibition is enforced rather than promised: a config loader that refuses
threshold-shaped keys at any depth, a bridge that cannot return a decision, a
result-set validator that refuses a stored score with a fractional part, and a
finalization that refuses to publish a document carrying a forbidden key.

## The files

| file | what it is |
|---|---|
| `algorithm-profile.json` | the frozen production identity |
| `runtime-binding.json` | the seventeen-component closure and its three guards |
| `adapter-profile.json` | how the adapter drives the route, and what it refuses |
| `bridge-contract.json` | the wire format, its refusals and its failure codes |
| `adapter-smoke.json` | the production smoke, on fixtures that are not SD300 |
| `canonical-run-binding.json` | the reference run, plan, pairs and inputs |
| `operational-summary.json` | counts, codes and timings — and no score |
| `stage-11b-finalization.json` | the marker |
| `run_52731bb3407e.json` | the shared engine's own research receipt |

The run definition, the plan and the result set stay in the engine's structure
and are not copied out under a Stage 11B name.

## Verifying it

Evidence only — no dataset, no SDK, no licence, no JVM, no workspace:

```bash
make stage11b-evidence
```

The contract itself, against a fake bridge:

```bash
make stage11b-contract
```

Reproducing the run needs the pinned SDK, an activated trial licence and SD300;
none of the three is in CI and none ever will be. The documented invocation is
[docs/experiments/verifinger-canonical500-raw.md](../../docs/experiments/verifinger-canonical500-raw.md).
