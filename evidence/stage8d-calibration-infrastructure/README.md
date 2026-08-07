# Stage 8D — Generic calibration infrastructure qualification

**Outcome:** `CALIBRATION_INFRASTRUCTURE_READY`

This directory is the published evidence that a generic, algorithm-neutral
calibration engine exists and was qualified. It is **not** evidence that anything
was calibrated.

## What the outcome asserts

```
calibration engine exists
synthetic qualification passed
development/evaluation boundary enforced
threshold selection deterministic
operating-point provenance supported
```

## What it denies

Each of these is a field in `stage-8d-finalization.json`, checked by the marker's
own constructor rather than written as prose:

```
real_calibration_performed          false
real_development_dataset_selected   false
production_threshold_count          0
production_decision_profile_count   0
evaluation_score_rows_read          false
sd300_score_statistics_read         false
historical_decision_profiles_changed false
stage8c_evidence_changed            false
```

No SD300 score row was read. No score distribution of SourceAFIS, NBIS or flx was
examined. No target FMR was chosen. No `DecisionSet` was created. No threshold
exists that did not exist before this stage.

## Why the scope changed

Stage 8C closed with `opens_stage_8d: true`, and the plan then was flx decisions.
The flx score scale has no upstream-documented operating point, so a threshold
would have to be chosen — and the only scores available to choose it from are the
6,000 evaluation scores it would then be reported on. Meanwhile the algorithm list
is not final, and no development cohort has ever been drawn.

So Stage 8D kept its name and changed its scope: it builds the machinery now, and
a real calibration happens once, later, over every algorithm at once
(docs/adr/0078).

Stage 8C's evidence is untouched. `evidence/flx-canonical500-raw/` was not edited
and `stage-8c-finalization.json` was not re-derived.

## The files

| File | What it is |
|---|---|
| `protected-evaluation-registry.json` | the identities a calibration must refuse — identities only, no score and no count of one |
| `synthetic-qualification.json` | 26 fixtures, their outcomes as fingerprints and counts |
| `calibration-contract-report.json` | the structural facts: module digests, enforced absences, schema versions, the legacy identities that did not move |
| `stage-8d-finalization.json` | the last-written authority, binding all of the above and the exact bytes of every file here |

## What is not in this directory

No real fingerprint score. No real threshold. No SD300 score statistic. No
histogram, ROC, DET or EER. No embedding. No finger identifier and no subject
identifier.

The synthetic cases publish *fingerprints and counts* rather than thresholds. An
operating-point fingerprint covers the threshold and the comparator, so a verifier
that re-runs a fixture compares identities exactly — and nothing here is a number
a reader could mistake for a measurement.

## Verifying it

```bash
pytest -m "stage8d" -q
```

The gate re-reads Stage 8C's marker to confirm the stage this one follows, rebuilds
the protected registry from the published documents its frozen identities were
copied from, re-runs all 26 synthetic fixtures, recomputes the engine source
fingerprints, and re-hashes every file in this directory against the marker.

Nothing in it needs a dataset, a runtime, a checkpoint, Java, or a workspace.

## What this opens

Algorithm expansion, not calibration:

```
Stage 9A   algorithm 4 — artifact qualification
Stage 9B   algorithm 4 — runtime and adapter qualification
Stage 9C   algorithm 4 — canonical_500 raw run
```

and the same three for algorithm 5. A real calibration stage opens only once the
algorithm list is declared final — it will choose a development cohort, a pair
protocol and a target operating point once, and then run exactly this methodology
over every algorithm.
