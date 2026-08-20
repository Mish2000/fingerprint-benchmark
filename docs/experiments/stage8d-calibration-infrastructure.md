# Stage 8D — Generic calibration infrastructure qualification

**Outcome:** `CALIBRATION_INFRASTRUCTURE_READY`

Stage 8D builds the machinery a real calibration will run on, qualifies it on
synthetic fixtures, and calibrates nothing.

## Why the scope changed

Stage 8C closed with `opens_stage_8d: true`, and the plan then was that Stage 8D
would turn the 6,000 published flx raw scores into decisions. Stage 8C itself
established why it cannot: the flx scale has no upstream-documented operating
point, so a threshold would have to be *chosen*, and the only scores available to
choose it from are the 6,000 evaluation scores it would then be reported on.

Two further facts arrived afterwards. The algorithm list is not final — at least
five are intended, and algorithms 4 and 5 are not yet identified, so their score
directions and scales are unknown. And no development cohort has ever been drawn;
this project has one cohort and its role is `TEST`.

Choosing a target rate, a development cohort and a pair protocol now would mean
choosing them for two algorithms nobody has seen, and re-choosing them later
would make every earlier threshold incomparable with every later one. So the
stage keeps its name and changes its scope (docs/adr/0078).

Stage 8C is not rewritten. `evidence/flx-canonical500-raw/` is untouched,
`stage-8c-finalization.json` is not re-derived, and the historical README that
predicted flx decisions is left alone — a document that recorded what was
believed is evidence of what was believed.

## What it built

```
src/fpbench/calibration/                 the engine
src/fpbench/calibration/source.py        verified ResultSet-to-label binding
src/fpbench/core/calibration_models.py   the persisted artifacts
src/fpbench/core/calibration_errors.py   the failure vocabulary
src/fpbench/storage/calibration_store.py append-only files
```

plus `DecisionProfile` schema 3, which is the only schema that may carry the
three links a calibrated threshold has to name: the operating point it came from,
the protocol that selected it, and the development source it was selected on.
Schemas 1 and 2 are untouched and pinned by literal digest.

See [the architecture](../calibration/architecture.md) and
[how a boundary is selected](../calibration/operating-point-selection.md).

## What it deliberately did not do

| | |
|---|---|
| select a development dataset | no |
| perform a calibration | no |
| read an SD300 score row | no |
| read any algorithm's score distribution | no |
| choose a target FMR | no |
| produce a production threshold | no |
| produce a production `DecisionProfile` | no |
| create a `DecisionSet` | no |
| compute eligibility, metrics, ROC, DET or EER | no |
| normalize scores between algorithms | no |
| change historical evidence | no |
| change the two documented `40` thresholds | no |
| change Stage 7D or Stage 8C results | no |

## The synthetic qualification

29 fixtures, each small enough that its expected answer is worked out in the
case's own description. Nothing in it touches a dataset, a runtime, a checkpoint,
a prior result set or a workspace: it is pure Python over numbers that were never
measured.

**Selection cases** — a higher-is-better matcher reaching a `1/4` ceiling exactly;
a lower-is-better matcher selecting `<= 5` under the same ceiling; a ceiling
undershot to zero at `> 0.7` because two equal `0.7`s cannot be split; an
operating point that admits no impostor at all; a population where every score is
identical, whose answer is a strict boundary at the only score that exists;
duplicate scores counted once each and decided together; comparisons that
produced no score, excluded from the rate and reported beside it; and a pair of
cases sharing one impostor population under two very different genuine ones —
one above every impostor, one interleaved between them — which must select the
same boundary and differ only in the mated counts measured at it.

**Identity cases** — 25 rotations of the same rows producing one operating point;
a JSON round trip changing nothing; verification re-deriving the stored answer
rather than reading it back; an operating point becoming a schema-3
`CALIBRATED_DEVELOPMENT` profile carrying all three links.

**Refusal cases** — and the *class* of each refusal is checked, not merely that
something was raised: an evaluation-role binding; a binding resolving to a
registered protected result set; a binding claiming development over a registered
protected cohort; running with no registry loaded at all; a binding and its
results disagreeing about score direction; a missing impostor population; a
missing genuine population; an impostor population that wholly failed; duplicate
pair ids; a non-finite score; a malformed decimal; a score arriving as a binary
float; verification against the wrong result set, the wrong pair manifest, and
the wrong protocol. The catalogue also fixes the result-body regression
explicitly: the same source binding is refused when verification is handed
scores multiplied onto a second scale, even though the pair ids and populations
are unchanged.

## Published evidence

```
evidence/stage8d-calibration-infrastructure/
├── README.md
├── synthetic-qualification.json
├── protected-evaluation-registry.json
├── calibration-contract-report.json
└── stage-8d-finalization.json
```

None of it holds a score, a threshold, a distribution, a subject identifier or a
finger identifier. The synthetic cases publish *fingerprints and counts*: the
operating-point fingerprint covers the threshold and the comparator, so a verifier
that re-runs a fixture compares identities exactly and the evidence never carries
a number a reader could mistake for a measurement.

## Running it

```bash
pytest -m "stage8d_contract" -q
```

The suite needs no dataset, no runtime and no optional dependency, and the CI job
fails if anything in it skips — a suite that skipped silently would look identical
to one that passed.

## What comes next

Algorithm expansion, not calibration. The marker records
`opens_algorithm_expansion: true` rather than opening a calibration stage, because
opening one would be the decision docs/adr/0078 defers.

```
Stage 9A   algorithm 4 — artifact qualification
Stage 9B   algorithm 4 — runtime and adapter qualification
Stage 9C   algorithm 4 — canonical_500 raw run
```

and the same three for algorithm 5. Only once the algorithm list is declared
final does a real calibration stage open: it will choose a development cohort, a
pair protocol and a target operating point **once**, and then run exactly this
methodology over every algorithm.
