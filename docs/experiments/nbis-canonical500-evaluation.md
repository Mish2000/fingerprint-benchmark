# NBIS canonical 500 ppi — evaluation

Counting the 6,000 NBIS decisions into fourteen metrics, under the same policy
file both SourceAFIS evaluations used.

```bash
python -m fpbench.experiments.nbis_canonical500_evaluation prepare
python -m fpbench.experiments.nbis_canonical500_evaluation derive
python -m fpbench.experiments.nbis_canonical500_evaluation status
python -m fpbench.experiments.nbis_canonical500_evaluation finalize
python -m fpbench.experiments.nbis_canonical500_evaluation show
```

## One policy file, not two

`configs/metrics/plain_roll_biometric_metrics_v1.yaml` is cited by path, by all
three evaluations. There is no `nbis_..._metrics_v1.yaml`, and creating one would
be the single most damaging thing this stage could do quietly: a copy is a second
place for a denominator to live and a second chance for the two chains to stop
counting the same thing.

The file fixes the fourteen metrics, their numerators, their denominators, the
pooling rule, and the refusal to call the negative sanity set a false-match rate.
Its fingerprint is inside the metric set, inside the frozen measurement protocol,
and inside the comparison receipt, so a comparison over two metric sets counted
under different policies fails its own fairness audit.

## The fourteen metrics

```text
 1. plain_self_match_rate_decided
 2. plain_self_match_rate_attempt
 3. roll_self_match_rate_decided
 4. roll_self_match_rate_attempt

 5. self_eligibility_rate
 6. self_ineligible_rate
 7. self_undetermined_rate

 8. plain_roll_mated_unconditional_fnmr_decided
 9. plain_roll_mated_unconditional_non_success_rate_attempt

10. plain_roll_mated_conditional_selection_rate
11. plain_roll_mated_conditional_fnmr_decided
12. plain_roll_mated_conditional_non_success_rate_attempt

13. plain_roll_non_mated_sanity_match_rate_decided
14. plain_roll_non_mated_sanity_match_rate_attempt
```

Each is computed for SD300A, SD300B, SD300C and pooled: **14 × 4 = 56
observations**, and the config declares the number so that a metric silently
added or a release silently dropped fails here rather than changing a published
table.

Pooling sums the release numerators, sums the release denominators and divides
once. It never averages the three percentages — that agrees only while the
releases are the same size, and stops agreeing without saying so
([ADR 0028](../adr/0028-pooled-metrics-sum-counts.md)).

## Attempt rates and decided rates are different metrics

Every stage reports both, always. When nothing fails they are numerically
identical, and that is precisely the argument for keeping them apart: a single
blended number would start moving the day something did fail, for reasons nobody
could name from the number ([ADR 0027](../adr/0027-attempt-and-decided-rates-are-separate.md)).

The distinction is what makes the comparison downstream honest. Two attempt rates
over the same 1,500 attempts are directly comparable; two decided rates are
comparable only when both algorithms could decide the same attempts.

## The negative sanity set is not an FMR

1,500 same-subject, different-finger pairs, produced by one fixed cyclic shift
inside each subject. It is a closed set chosen for sanity, not a sample designed
for estimating a false-match rate over a population.

Reporting it as an FMR would be reporting an estimate of something nobody
sampled for. The metric policy carries `label_as_fmr: false`, the loader refuses
the file if it is ever true, and the report labels every row of it explicitly
([ADR 0030](../adr/0030-negative-sanity-is-not-general-fmr.md)).

## What this evaluation may not claim

```yaml
limitations:
  confidence_intervals: false
  threshold_calibration: false
  general_fmr_claim: false
  equal_operating_point_claim: false
```

Every flag names machinery that does not exist. There is no calibration manifest,
no bootstrap, no impostor design chosen for estimation, and no evidence that
NIST's documented `> 40` and SourceAFIS's documented `>= 40` sit at the same
error rate. The loader refuses the config if any is switched on: switching a flag
would not create the machinery it names.

## Expected shape

| | |
|---|---|
| decisions counted | 6,000 |
| eligibility units | 1,500 |
| rows per view | 1,500 (500 per release) |
| metric observations | 56 |
| final state | `EVALUATION_READY` |

## Evidence

```text
evidence/nbis-canonical500-evaluation/
├── README.md
├── <metric_set_id>.json          the receipt
├── <metric_set_id>.md            the rendered report
└── evaluation-finalization.json  the last-written marker
```

The finalization marker is published here and not in the SourceAFIS evaluation
directories, because the comparison downstream binds it by fingerprint and a
reader should be able to check that without opening a workspace.
