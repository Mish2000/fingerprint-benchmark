# Committed evaluation evidence

Two files per metric set, written by `finalize` and committed deliberately:

```
evidence/sourceafis-native-evaluation/<metric_set_id>.json   machine-readable
evidence/sourceafis-native-evaluation/<metric_set_id>.md     human-readable
```

Both are byte-identical to the verified copies in the workspace. Neither is
regenerated: an existing file with identical bytes is a no-op, and one with different
bytes is a conflict.

## What an evaluation receipt is

A receipt proves that a specific set of counts was taken from a specific set of
decisions, under a specific metric policy, by a specific commit of this harness — and
that every rate it publishes is stored as the two integers it was computed from.

Unlike a [derivation receipt](../sourceafis-native-decisions/README.md), this one **does**
carry outcomes. That is the point of the stage. Stage 5A refused to publish a count of
matches because the definitions that would make such a number honest did not exist yet:
no metric policy, no named denominators, no explicit population. They exist now, and this
receipt names all three.

Every metric appears as `numerator` and `denominator`, per release and pooled. No
percentage is stored. A reader with this file can recompute every number in the report
and check that each pooled value is the sum of its three releases.

## What an evaluation receipt is not

It carries **no estimate**. There is no confidence interval, no standard error, no
significance test and no ROC, DET or EER — the design was not chosen for estimation and
the machinery does not exist.

It carries **no calibrated threshold**. Threshold 40 is a number SourceAFIS's authors
published, applied unchanged. No search over thresholds was performed
([ADR 0021](../../docs/adr/0021-decision-profiles-are-immutable-and-external.md)).

It carries **no false-match rate**. The only non-mated comparisons in this evaluation are
same-subject, different-finger, closed-set and cyclically paired. Their match fraction is
published as an observed count in a sanity check and must not be presented as an FMR
([ADR 0030](../../docs/adr/0030-negative-sanity-is-not-general-fmr.md)).

It carries **no resolution finding**. Per-release values are reported side by side and
nothing is claimed about the difference between them.

It carries no personal or biometric data: no score, no subject id, no finger id, no image
id, no pair id, no job id, no filename, no path, no template, no minutiae, and no
breakdown finer than a release. That is enforced by
`fpbench.core.evaluation_models.require_sanitised_evaluation()` over the rendered
document, not by care.

## Checking one

Given the repository and a workspace holding the run:

```bash
python -m fpbench.experiments.sourceafis_native_evaluation status
```

`EVALUATION_READY` means every link still holds: the source derivation is still
`DECISION_READY`, every count re-derives from the decisions and the views, every
denominator re-resolves from its enum, every pooled value is the sum of its releases, and
the report on disk is the report the finalization marker was issued over. Any broken link
reports `INVALID` rather than degrading quietly.

To print the verified report:

```bash
python -m fpbench.experiments.sourceafis_native_evaluation show
```

It refuses to print anything from a chain that is not `EVALUATION_READY`. There is no
partial view — a report over an unverified chain is a table of numbers with nothing
behind it.
