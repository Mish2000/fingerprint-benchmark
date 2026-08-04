# Observed biometric results under decision profile `nbis_mindtct_bozorth3_5_0_0_nistir7391_gt40_canonical500_v1`

Metric set `metricset_614450282fdb`.

Every rate below is published as its exact numerator and denominator. The percentage beside a fraction is a rendering of those two integers, rounded to 4 decimal places for reading; the integers are the result.

## 1. Evaluation identity

| Field | Value |
| --- | --- |
| Algorithm | `nbis_mindtct_bozorth3` |
| Implementation version | `5.0.0` |
| Adapter | `nbis_mindtct_bozorth3_subprocess` |
| Integration mode | `subprocess_per_stage` |
| Execution profile | `canonical_500_lanczos3_60s_v1` |
| Resolution | `canonical_500` |
| Decision profile | `nbis_mindtct_bozorth3_5_0_0_nistir7391_gt40_canonical500_v1` |
| Threshold | `40` (greater_than, origin `documented_native`) |
| Run | `run_f0468f28ffba` |
| Result set | `resultset_73a9d93a8528` |
| Decision set | `decisionset_52b1ee4e6aca` |
| Eligibility set | `eligibilityset_9e717ecf6a82` |
| Metric set | `metricset_614450282fdb` |
| Run source commit | `05e55f8c1241fdb20d96c7e3547d8c64d170b4da` |
| Decision derivation commit | `8ce1562ff9988def8f79cb2da2741b0fe6358733` |
| Metric derivation commit | `5684cbb60d3be7707df418c6ad8514d498580fe3` |

## 2. Protocol and threshold

Each release contributes, per subject and finger, one PLAIN SELF comparison, one ROLL SELF comparison, one mated PLAIN–ROLL comparison and one same-subject different-finger comparison at a fixed cyclic finger shift.

A comparison is a MATCH when its score satisfies `greater_than` against threshold `40`. That threshold has origin `documented_native`: it is a number the algorithm's own authors published, applied here unchanged. **It was not calibrated on this data, and no other threshold was tried.**

A comparison that produced no score at all is `UNDECIDABLE`. It is never counted as a non-match. Every population below is therefore reported twice: once over the comparisons that produced a score, and once over every comparison attempted.

## 3. Important limitations

* The threshold is **documented, not calibrated**. Nothing here says it is the right one, and no search over thresholds was performed.
* The cohort is closed: a fixed set of subjects, chosen once. Every number is an observation about this cohort, not an estimate of a population.
* No confidence interval, standard error or significance test is reported, because the design was not chosen for estimation.
* The negative set is `same_subject_different_finger` paired by `cyclic_finger_shift`, over a closed set. It is a sanity check. It is **not** a general false-match rate and cannot be converted into one by dividing.
* Conditional results below cover a filtered population. They are published only together with the fraction of rows that filter kept.
* Releases are reported separately and pooled. Pooled values sum the release counts and divide once; they are not averages of the release percentages.

## 4. SELF results

A SELF comparison compares an image with itself, through two independent template extractions. It measures whether the pipeline can recognise a print as itself, which is a precondition for reading anything into a cross-impression result.

### 4.1 PLAIN SELF

| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | Decided match rate | Attempt match rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 498 | 2 | 0 | 498/500 (99.6000%) | 498/500 (99.6000%) |
| SD300B | 500 | 500 | 0 | 0 | 500/500 (100.0000%) | 500/500 (100.0000%) |
| SD300C | 500 | 500 | 0 | 0 | 500/500 (100.0000%) | 500/500 (100.0000%) |
| pooled | 1500 | 1498 | 2 | 0 | 1498/1500 (99.8667%) | 1498/1500 (99.8667%) |

### 4.2 ROLL SELF

| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | Decided match rate | Attempt match rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 500 | 0 | 0 | 500/500 (100.0000%) | 500/500 (100.0000%) |
| SD300B | 500 | 500 | 0 | 0 | 500/500 (100.0000%) | 500/500 (100.0000%) |
| SD300C | 500 | 500 | 0 | 0 | 500/500 (100.0000%) | 500/500 (100.0000%) |
| pooled | 1500 | 1500 | 0 | 0 | 1500/1500 (100.0000%) | 1500/1500 (100.0000%) |

## 5. SELF eligibility

A unit is one release, one subject, one finger. It is **eligible** when both of its SELF comparisons matched, **ineligible** when one of them returned a non-match, and **undetermined** when one of them produced no score. The third category is not a kind of failure: it records that nothing was measured.

| Release | Units | Eligible | Ineligible | Undetermined | Eligibility rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 498 | 2 | 0 | 498/500 (99.6000%) |
| SD300B | 500 | 500 | 0 | 0 | 500/500 (100.0000%) |
| SD300C | 500 | 500 | 0 | 0 | 500/500 (100.0000%) |
| pooled | 1500 | 1498 | 2 | 0 | 1498/1500 (99.8667%) |

## 6. Unconditional PLAIN–ROLL genuine results

Every mated PLAIN–ROLL comparison, with nothing excluded.

**Decision FNMR** is mated non-matches over mated comparisons that produced a score. **Attempt non-success rate** is mated non-matches *plus* comparisons that produced no score, over every attempt. The two answer different questions and are never combined.

| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | Decision FNMR | Attempt non-success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 301 | 199 | 0 | 199/500 (39.8000%) | 199/500 (39.8000%) |
| SD300B | 500 | 304 | 196 | 0 | 196/500 (39.2000%) | 196/500 (39.2000%) |
| SD300C | 500 | 300 | 200 | 0 | 200/500 (40.0000%) | 200/500 (40.0000%) |
| pooled | 1500 | 905 | 595 | 0 | 595/1500 (39.6667%) | 595/1500 (39.6667%) |

## 7. SELF-conditional PLAIN–ROLL genuine results

The same mated comparisons, counted only where the finger passed both SELF tests. Excluded rows stay in **Total rows** and are accounted for by the two exclusion columns; they are not in any conditional denominator.

The selection rate is part of the result, not context for it. A conditional rate over a different population is a different measurement from the unconditional one above — not the same measurement improved.

| Release | Total rows | Included | Excluded: ineligible | Excluded: undetermined | Included MATCH | Included NON_MATCH | Included UNDECIDABLE | Selection rate | Conditional decision FNMR | Conditional attempt non-success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 498 | 2 | 0 | 301 | 197 | 0 | 498/500 (99.6000%) | 197/498 (39.5582%) | 197/498 (39.5582%) |
| SD300B | 500 | 500 | 0 | 0 | 304 | 196 | 0 | 500/500 (100.0000%) | 196/500 (39.2000%) | 196/500 (39.2000%) |
| SD300C | 500 | 500 | 0 | 0 | 300 | 200 | 0 | 500/500 (100.0000%) | 200/500 (40.0000%) | 200/500 (40.0000%) |
| pooled | 1500 | 1498 | 2 | 0 | 905 | 593 | 0 | 1498/1500 (99.8667%) | 593/1498 (39.5861%) | 593/1498 (39.5861%) |

## 8. Same-subject different-finger negative sanity check

Observed 0/1500 matching decisions in this sanity set.

| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | Observed decided match fraction | Observed attempt match fraction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 0 | 500 | 0 | 0/500 (0.0000%) | 0/500 (0.0000%) |
| SD300B | 500 | 0 | 500 | 0 | 0/500 (0.0000%) | 0/500 (0.0000%) |
| SD300C | 500 | 0 | 500 | 0 | 0/500 (0.0000%) | 0/500 (0.0000%) |
| pooled | 1500 | 0 | 1500 | 0 | 0/1500 (0.0000%) | 0/1500 (0.0000%) |

This set compares two *different* fingers of the *same* subject, paired by `cyclic_finger_shift` over a closed cohort. It exists to catch a matcher that fires on obviously different fingers, and a non-zero count here is a reason to investigate the integration.

It is not an impostor experiment: the set is closed, both sides come from one person, and only one pairing was used. **This is not a general false-match rate estimate, and the fraction above must not be presented as one.** A rate over impostors would need a negative-pair design chosen for estimation, which is a different pair manifest and a different run.

## 9. Operational and failure accounting

A comparison that produced no score is `UNDECIDABLE`. It is not a non-match and never enters a decided denominator. Where these counts are zero, the decided and attempt rates above coincide numerically; they remain separate metrics, because the day one of them is non-zero a single blended number would move for reasons nobody could name.

| Population | Release | Attempts | Undecidable |
| --- | --- | ---: | ---: |
| PLAIN SELF | SD300A | 500 | 0 |
| PLAIN SELF | SD300B | 500 | 0 |
| PLAIN SELF | SD300C | 500 | 0 |
| PLAIN SELF | pooled | 1500 | 0 |
| ROLL SELF | SD300A | 500 | 0 |
| ROLL SELF | SD300B | 500 | 0 |
| ROLL SELF | SD300C | 500 | 0 |
| ROLL SELF | pooled | 1500 | 0 |
| Mated (unconditional) | SD300A | 500 | 0 |
| Mated (unconditional) | SD300B | 500 | 0 |
| Mated (unconditional) | SD300C | 500 | 0 |
| Mated (unconditional) | pooled | 1500 | 0 |
| Negative sanity | SD300A | 500 | 0 |
| Negative sanity | SD300B | 500 | 0 |
| Negative sanity | SD300C | 500 | 0 |
| Negative sanity | pooled | 1500 | 0 |
| Mated (SELF-conditional, included only) | SD300A | 498 | 0 |
| Mated (SELF-conditional, included only) | SD300B | 500 | 0 |
| Mated (SELF-conditional, included only) | SD300C | 500 | 0 |
| Mated (SELF-conditional, included only) | pooled | 1498 | 0 |

## 10. What these results do not establish

* **Not a calibrated threshold.** No threshold was chosen, searched for or optimised here. No ROC curve, DET curve or equal-error rate was computed.
* **Not a general false-match rate.** The only non-mated comparisons in this evaluation are same-subject, different-finger, closed-set and cyclically paired.
* **Not a statistical comparison between releases.** The per-release values are reported side by side and nothing is claimed about the difference between them. No significance test was performed and none would be valid on this design.
* **Not a resolution finding.** Nothing here says one capture resolution performs better than another; the releases differ in more than resolution.
* **Not a comparison between algorithms.** One matcher, one build, one documented threshold.
* **Not an estimate with an interval.** No confidence interval, bootstrap or hypothesis test is reported.
