# Committed derivation evidence

One file per decision set, written by `finalize` and committed deliberately:

```
evidence/sourceafis-native-decisions/<decision_set_id>.json
```

## What a derivation receipt is

It proves that a specific set of decisions was derived, deterministically, from a
specific set of raw scores, under a specific threshold, by a specific commit of this
harness — and that the eligibility set and the three evaluation views that follow from
those decisions were derived and re-verified too.

Every field is an identifier, a fingerprint, or a count of **structure**: how many
decisions, how many eligibility units, how many rows in each view.

## What it is not

It carries **no metric and no outcome**. Not how many comparisons matched, not how many
fingers were eligible, not how many rows the conditional view included, not FMR, not
FNMR, not EER, not accuracy. It says so in its own text:

> This receipt proves deterministic decision and eligibility derivation. It contains no
> biometric performance metric or conclusion.

Those numbers are not withheld because they are secret. They are withheld because a
number derived from a threshold nobody has justified, over denominators nobody has
defined, is not a result — and a file that carried it would be quoted as one
([ADR 0021](../../docs/adr/0021-decision-profiles-are-immutable-and-external.md)).

It also carries no personal or biometric data: no score, no subject id, no image id, no
filename, and no path. That is enforced by
`fpbench.core.derivation_models.require_sanitised_derivation()` over the rendered
document, not by care.

## Checking one

Given the repository and a workspace holding the run:

```bash
git checkout <derivation_source_commit>
python -m fpbench.experiments.sourceafis_native_decisions status
```

`DECISION_READY` means the whole chain still holds: the source run is still
`RESEARCH_READY`, every decision still follows from its raw score, every eligibility
verdict from its two SELF decisions, every inclusion flag from its verdict, and the
receipt and marker still name exactly those artefacts. Any broken link reports `INVALID`
rather than degrading quietly.
