# Observed biometric results under decision profile `sourceafis_java_3_18_1_documented_40_v1`

Metric set `metricset_09f2460277b4`.

Every rate below is published as its exact numerator and denominator. The percentage beside a fraction is a rendering of those two integers, rounded to 4 decimal places for reading; the integers are the result.

## 1. Evaluation identity

| Field | Value |
| --- | --- |
| Algorithm | `sourceafis_java` |
| Implementation version | `3.18.1` |
| Adapter | `sourceafis_java_subprocess` |
| Integration mode | `subprocess_per_comparison` |
| Execution profile | `native_identity_60s_v1` |
| Resolution | `native` |
| Decision profile | `sourceafis_java_3_18_1_documented_40_v1` |
| Threshold | `40` (greater_than_or_equal, origin `documented_native`) |
| Run | `run_7ac1cecc0bb3` |
| Result set | `resultset_2bf3cacfd806` |
| Decision set | `decisionset_0122544e71b1` |
| Eligibility set | `eligibilityset_77dbf75cdc76` |
| Metric set | `metricset_09f2460277b4` |
| Run source commit | `36ea36c7ee25b2f3babb0f623b269bd9a4edd7ce` |
| Decision derivation commit | `716ca20929b821cce8796c11d35e979afcad1a6f` |
| Metric derivation commit | `647f02b3ab9b074c8ebed9a66816da4ba6910a7c` |

## 2. Protocol and threshold

Each release contributes, per subject and finger, one PLAIN SELF comparison, one ROLL SELF comparison, one mated PLAIN–ROLL comparison and one same-subject different-finger comparison at a fixed cyclic finger shift.

A comparison is a MATCH when its score satisfies `greater_than_or_equal` against threshold `40`. That threshold has origin `documented_native`: it is a number the algorithm's own authors published, applied here unchanged. **It was not calibrated on this data, and no other threshold was tried.**

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
| SD300A | 500 | 487 | 13 | 0 | 487/500 (97.4000%) | 487/500 (97.4000%) |
| SD300B | 500 | 490 | 10 | 0 | 490/500 (98.0000%) | 490/500 (98.0000%) |
| SD300C | 500 | 491 | 9 | 0 | 491/500 (98.2000%) | 491/500 (98.2000%) |
| pooled | 1500 | 1468 | 32 | 0 | 1468/1500 (97.8667%) | 1468/1500 (97.8667%) |

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
| SD300A | 500 | 487 | 13 | 0 | 487/500 (97.4000%) |
| SD300B | 500 | 490 | 10 | 0 | 490/500 (98.0000%) |
| SD300C | 500 | 491 | 9 | 0 | 491/500 (98.2000%) |
| pooled | 1500 | 1468 | 32 | 0 | 1468/1500 (97.8667%) |

## 6. Unconditional PLAIN–ROLL genuine results

Every mated PLAIN–ROLL comparison, with nothing excluded.

**Decision FNMR** is mated non-matches over mated comparisons that produced a score. **Attempt non-success rate** is mated non-matches *plus* comparisons that produced no score, over every attempt. The two answer different questions and are never combined.

| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | Decision FNMR | Attempt non-success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 336 | 164 | 0 | 164/500 (32.8000%) | 164/500 (32.8000%) |
| SD300B | 500 | 343 | 157 | 0 | 157/500 (31.4000%) | 157/500 (31.4000%) |
| SD300C | 500 | 329 | 171 | 0 | 171/500 (34.2000%) | 171/500 (34.2000%) |
| pooled | 1500 | 1008 | 492 | 0 | 492/1500 (32.8000%) | 492/1500 (32.8000%) |

## 7. SELF-conditional PLAIN–ROLL genuine results

The same mated comparisons, counted only where the finger passed both SELF tests. Excluded rows stay in **Total rows** and are accounted for by the two exclusion columns; they are not in any conditional denominator.

The selection rate is part of the result, not context for it. A conditional rate over a different population is a different measurement from the unconditional one above — not the same measurement improved.

| Release | Total rows | Included | Excluded: ineligible | Excluded: undetermined | Included MATCH | Included NON_MATCH | Included UNDECIDABLE | Selection rate | Conditional decision FNMR | Conditional attempt non-success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 487 | 13 | 0 | 336 | 151 | 0 | 487/500 (97.4000%) | 151/487 (31.0062%) | 151/487 (31.0062%) |
| SD300B | 500 | 490 | 10 | 0 | 343 | 147 | 0 | 490/500 (98.0000%) | 147/490 (30.0000%) | 147/490 (30.0000%) |
| SD300C | 500 | 491 | 9 | 0 | 329 | 162 | 0 | 491/500 (98.2000%) | 162/491 (32.9939%) | 162/491 (32.9939%) |
| pooled | 1500 | 1468 | 32 | 0 | 1008 | 460 | 0 | 1468/1500 (97.8667%) | 460/1468 (31.3351%) | 460/1468 (31.3351%) |

## 8. Same-subject different-finger negative sanity check

Observed matches in the closed-set same-subject different-finger negative sanity check: 2/1500.

| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | Observed decided match fraction | Observed attempt match fraction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD300A | 500 | 0 | 500 | 0 | 0/500 (0.0000%) | 0/500 (0.0000%) |
| SD300B | 500 | 1 | 499 | 0 | 1/500 (0.2000%) | 1/500 (0.2000%) |
| SD300C | 500 | 1 | 499 | 0 | 1/500 (0.2000%) | 1/500 (0.2000%) |
| pooled | 1500 | 2 | 1498 | 0 | 2/1500 (0.1333%) | 2/1500 (0.1333%) |

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
| Mated (SELF-conditional, included only) | SD300A | 487 | 0 |
| Mated (SELF-conditional, included only) | SD300B | 490 | 0 |
| Mated (SELF-conditional, included only) | SD300C | 491 | 0 |
| Mated (SELF-conditional, included only) | pooled | 1468 | 0 |

## 10. What these results do not establish

* **Not a calibrated threshold.** No threshold was chosen, searched for or optimised here. No ROC curve, DET curve or equal-error rate was computed.
* **Not a general false-match rate.** The only non-mated comparisons in this evaluation are same-subject, different-finger, closed-set and cyclically paired.
* **Not a statistical comparison between releases.** The per-release values are reported side by side and nothing is claimed about the difference between them. No significance test was performed and none would be valid on this design.
* **Not a resolution finding.** Nothing here says one capture resolution performs better than another; the releases differ in more than resolution.
* **Not a comparison between algorithms.** One matcher, one build, one documented threshold.
* **Not an estimate with an interval.** No confidence interval, bootstrap or hypothesis test is reported.
