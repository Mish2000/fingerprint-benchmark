# 0078 — Stage 8D builds calibration infrastructure without calibrating

*Status: Accepted — 2026-08-07, stage 8D*

## Context

Stage 8C closed with `opens_stage_8d: true`, and the plan of record at that
moment was that Stage 8D would turn the 6,000 published flx raw scores into
decisions. Stage 8C itself established why it cannot:

> A decision set over these scores would mean somebody chose a threshold for the
> flx scale, and there is no such threshold to choose.

The flx score scale has no upstream-documented operating point. SourceAFIS
documents 40 and NIST documents "greater than 40"; nobody documents a number for
this matcher. So a Stage 8D that produced flx decisions would have to choose a
threshold, and the only scores available to choose it from are the 6,000
evaluation scores it would then be reported on. That is the one form of leakage
this project has refused since docs/adr/0021.

Two further facts arrived after Stage 8C was written:

* the algorithm list is not final — at least five algorithms are intended, and
  algorithms 4 and 5 are not yet identified, so their score directions and score
  scales are unknown;
* a development cohort has never been drawn. There is one cohort in this
  project, and its role is `TEST`.

Choosing a target false-match rate, a development cohort and a pair protocol now
would mean choosing them for two algorithms nobody has seen, and re-choosing
them later would make every earlier threshold incomparable with every later one.

## Decision

Stage 8D keeps its name and changes its scope. It builds the generic,
algorithm-neutral machinery that a real calibration will later run on, and it
performs no calibration.

Its success outcome is

```
CALIBRATION_INFRASTRUCTURE_READY
```

which asserts exactly this and nothing more:

```
calibration engine exists
synthetic qualification passed
development/evaluation boundary enforced
threshold selection deterministic
operating-point provenance supported
```

and denies, in the finalization marker's own fields:

```
real_calibration_performed      false
real_development_dataset_selected false
production_threshold_count      0
production_decision_profile_count 0
evaluation_score_rows_read      false
sd300_score_statistics_read     false
```

Stage 8C is not rewritten. Its marker, its evidence and its `opens_stage_8d`
claim stay byte-identical; `evidence/flx-canonical500-raw/` is not edited, and
`stage-8c-finalization.json` is not re-derived. The change of plan is recorded
here rather than by amending a closed stage's published record.

The README of Stage 8C still says Stage 8D will continue to flx decisions. That
sentence was true when it was written and is left alone: a historical document
that predicted a later decision is evidence of what was believed, and editing it
would destroy that without adding anything this ADR does not already say.

Real calibration is deferred to a stage that does not exist yet, and which will
not exist until the algorithm list is declared final. That stage will choose a
development cohort, a pair-generation protocol and a target operating point
**once**, and then run the identical methodology over every algorithm.

## Alternatives considered

**Skip to Stage 9A.** Stage 8C already closed with `opens_stage_8d: true`, and
the numbering is part of the published record. Renaming the next stage to avoid
admitting a scope change would leave a marker pointing at a stage that never
existed.

**Calibrate flx on the 6,000 SD300 scores anyway, and label it clearly.** The
label would not fix it. A threshold chosen on the same 50 subjects it is then
reported on produces an FMR estimate that is a description of the fitting, not a
measurement, and no caveat downstream can separate the two again.

**Build nothing until the algorithm list is final.** The infrastructure is the
part that does not depend on which algorithms are chosen: exact rate arithmetic,
boundary semantics, tie atomicity, role enforcement and provenance are the same
for five algorithms as for three. Building it now is what makes the eventual
calibration a single act rather than five improvised ones.

**Ship the models without the qualification.** Untested selection code is the
component least able to survive being written once and used years later. The
synthetic fixtures are the part of Stage 8D that makes the rest citable.

## Consequences

Stage 8D publishes `evidence/stage8d-calibration-infrastructure/` and adds
`src/fpbench/calibration/`. It creates no `DecisionSet`, no production
`DecisionProfile`, no threshold and no metric.

Nothing about the flx raw scores changes. They remain published, raw and
undecided, exactly as Stage 8C left them.

The next stages are algorithm expansion, not calibration:

```
Stage 9A   algorithm 4 — artifact qualification
Stage 9B   algorithm 4 — runtime and adapter qualification
Stage 9C   algorithm 4 — canonical_500 raw run
```

and the same three for algorithm 5. Stage 8D's marker records
`opens_algorithm_expansion: true` rather than opening a calibration stage,
because opening one would be the decision this ADR defers.
