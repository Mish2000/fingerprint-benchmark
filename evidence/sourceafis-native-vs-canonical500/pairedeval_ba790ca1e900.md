# Native versus canonical 500 ppi — paired comparison

This comparison records what changed between two runs that differed in one thing: the image preparation path. It establishes no resolution superiority, no causal claim, no general false-match rate, and no statistical significance.

## 1. Evaluation identity

| Field | Value |
| --- | --- |
| Paired evaluation | `pairedeval_ba790ca1e900` |
| Paired fingerprint | `ba790ca1e9000bba804be80ba213e56f8839b3af564dd3bc3486dcb8baf60c3b` |
| Policy | `sourceafis_native_vs_canonical500_paired_v1` |
| Native decision set id | `decisionset_0122544e71b1` |
| Native eligibility set id | `eligibilityset_77dbf75cdc76` |
| Native metric set id | `metricset_f6ffa71f3880` |
| Native result set id | `resultset_2bf3cacfd806` |
| Native run id | `run_7ac1cecc0bb3` |
| Canonical decision set id | `decisionset_df0d584bdede` |
| Canonical eligibility set id | `eligibilityset_d87d6591d517` |
| Canonical metric set id | `metricset_b4c70fbfd1d3` |
| Canonical result set id | `resultset_087b084fb8a8` |
| Canonical run id | `run_4c59fa02a6ab` |
| Native run commit | `36ea36c7ee25b2f3babb0f623b269bd9a4edd7ce` |
| Canonical run commit | `733f68468d26d630cb7986bc8d37c90403d1ea12` |
| Comparison commit | `d000fb1d9f0f23ed3a96fe5ec7e89e3fc41aa13a` |

## 2. What changed and what stayed fixed

Both runs used the same algorithm, the same build, the same bridge jar, the same runtime bundle, the same cohort, the same 6,000 pairs in the same order and the same threshold. The variable that changed was the image preparation path.

This is **not** an isolation of resolution. The canonical path performs an external Lanczos resampling to 500 ppi before the matcher sees the image; the native path hands SourceAFIS the delivered image at its own resolution and lets SourceAFIS handle the ppi itself. Those are two different preparation pipelines, not two resolutions of one pipeline (spec section 62).

## 3. SD300A exact-control result

SD300A's canonical artefacts preserve their source rasters byte for byte, so identical pixels went through an identical build. Every comparison must therefore have reproduced exactly.

| Check | Count | Of |
| --- | ---: | ---: |
| Scores compared | 2000 | 2000 |
| Scores equal | 2000 | 2000 |
| Result statuses equal | 2000 | 2000 |
| Decisions equal | 2000 | 2000 |

Control audit clean: **yes**.

## 4. Native standalone result

The native evaluation stands on its own and is published separately as `metricset_f6ffa71f3880`. Its numbers are reproduced below only in the native column of section 12.

## 5. Canonical standalone result

The canonical evaluation stands on its own and is published separately as `metricset_b4c70fbfd1d3`.

## 6. PLAIN SELF transition matrix

| Transition | SD300A | SD300B | SD300C | pooled |
| --- | ---: | ---: | ---: | ---: |
| MATCH → MATCH | 487 | 490 | 491 | 1468 |
| MATCH → NON_MATCH | 0 | 0 | 0 | 0 |
| MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| NON_MATCH → MATCH | 0 | 3 | 1 | 4 |
| NON_MATCH → NON_MATCH | 13 | 7 | 8 | 28 |
| NON_MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| UNDECIDABLE → MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → NON_MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → UNDECIDABLE | 0 | 0 | 0 | 0 |
| **total** | 500 | 500 | 500 | 1500 |

## 7. ROLL SELF transition matrix

| Transition | SD300A | SD300B | SD300C | pooled |
| --- | ---: | ---: | ---: | ---: |
| MATCH → MATCH | 500 | 500 | 500 | 1500 |
| MATCH → NON_MATCH | 0 | 0 | 0 | 0 |
| MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| NON_MATCH → MATCH | 0 | 0 | 0 | 0 |
| NON_MATCH → NON_MATCH | 0 | 0 | 0 | 0 |
| NON_MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| UNDECIDABLE → MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → NON_MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → UNDECIDABLE | 0 | 0 | 0 | 0 |
| **total** | 500 | 500 | 500 | 1500 |

## 8. Eligibility transition matrix

| Transition | SD300A | SD300B | SD300C | pooled |
| --- | ---: | ---: | ---: | ---: |
| ELIGIBLE → ELIGIBLE | 487 | 490 | 491 | 1468 |
| ELIGIBLE → INELIGIBLE | 0 | 0 | 0 | 0 |
| ELIGIBLE → UNDETERMINED | 0 | 0 | 0 | 0 |
| INELIGIBLE → ELIGIBLE | 0 | 3 | 1 | 4 |
| INELIGIBLE → INELIGIBLE | 13 | 7 | 8 | 28 |
| INELIGIBLE → UNDETERMINED | 0 | 0 | 0 | 0 |
| UNDETERMINED → ELIGIBLE | 0 | 0 | 0 | 0 |
| UNDETERMINED → INELIGIBLE | 0 | 0 | 0 | 0 |
| UNDETERMINED → UNDETERMINED | 0 | 0 | 0 | 0 |
| **total** | 500 | 500 | 500 | 1500 |

## 9. Unconditional mated transition matrix

| Transition | SD300A | SD300B | SD300C | pooled |
| --- | ---: | ---: | ---: | ---: |
| MATCH → MATCH | 336 | 300 | 291 | 927 |
| MATCH → NON_MATCH | 0 | 43 | 38 | 81 |
| MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| NON_MATCH → MATCH | 0 | 24 | 28 | 52 |
| NON_MATCH → NON_MATCH | 164 | 133 | 143 | 440 |
| NON_MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| UNDECIDABLE → MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → NON_MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → UNDECIDABLE | 0 | 0 | 0 | 0 |
| **total** | 500 | 500 | 500 | 1500 |

## 10. Common-eligible mated comparison

Over the 1468 of 1500 mated comparisons whose finger both runs found eligible. This is the only mated population the two runs share, and therefore the only one whose conditional rates may be subtracted.

| Transition | SD300A | SD300B | SD300C | pooled |
| --- | ---: | ---: | ---: | ---: |
| MATCH → MATCH | 336 | 300 | 291 | 927 |
| MATCH → NON_MATCH | 0 | 43 | 38 | 81 |
| MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| NON_MATCH → MATCH | 0 | 24 | 28 | 52 |
| NON_MATCH → NON_MATCH | 151 | 123 | 134 | 408 |
| NON_MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| UNDECIDABLE → MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → NON_MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → UNDECIDABLE | 0 | 0 | 0 | 0 |
| **total** | 487 | 490 | 491 | 1468 |

## 11. Negative-sanity transition matrix

Closed-set same-subject different-finger negative sanity check. This is **not** a general, population or impostor false-match rate (docs/adr/0030).

| Transition | SD300A | SD300B | SD300C | pooled |
| --- | ---: | ---: | ---: | ---: |
| MATCH → MATCH | 0 | 1 | 0 | 1 |
| MATCH → NON_MATCH | 0 | 0 | 1 | 1 |
| MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| NON_MATCH → MATCH | 0 | 0 | 0 | 0 |
| NON_MATCH → NON_MATCH | 500 | 499 | 499 | 1498 |
| NON_MATCH → UNDECIDABLE | 0 | 0 | 0 | 0 |
| UNDECIDABLE → MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → NON_MATCH | 0 | 0 | 0 | 0 |
| UNDECIDABLE → UNDECIDABLE | 0 | 0 | 0 | 0 |
| **total** | 500 | 500 | 500 | 1500 |

## 12. Score-direction diagnostics

| Direction | Comparisons |
| --- | ---: |
| canonical lower | 1384 |
| equal | 3061 |
| canonical higher | 1555 |
| unavailable | 0 |

Counts only. No mean, no median and no distribution of the per-pair deltas is computed at this stage (spec section 31).

### Paired rates

Every rate is printed as the two integers it was computed from. A difference is shown only where the two sides covered the same rows.

| Rate | Scope | Native | Canonical | Difference | Comparability |
| --- | --- | --- | --- | ---: | --- |
| PLAIN SELF attempt match fraction | SD300A | 487/500 (97.4000%) | 487/500 (97.4000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| PLAIN SELF attempt match fraction | SD300B | 490/500 (98.0000%) | 493/500 (98.6000%) | 3/500 = +0.6000 pp | same attempts on both sides |
| PLAIN SELF attempt match fraction | SD300C | 491/500 (98.2000%) | 492/500 (98.4000%) | 1/500 = +0.2000 pp | same attempts on both sides |
| PLAIN SELF attempt match fraction | pooled | 1468/1500 (97.8667%) | 1472/1500 (98.1333%) | 1/375 = +0.2667 pp | same attempts on both sides |
| ROLL SELF attempt match fraction | SD300A | 500/500 (100.0000%) | 500/500 (100.0000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| ROLL SELF attempt match fraction | SD300B | 500/500 (100.0000%) | 500/500 (100.0000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| ROLL SELF attempt match fraction | SD300C | 500/500 (100.0000%) | 500/500 (100.0000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| ROLL SELF attempt match fraction | pooled | 1500/1500 (100.0000%) | 1500/1500 (100.0000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| SELF eligibility fraction | SD300A | 487/500 (97.4000%) | 487/500 (97.4000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| SELF eligibility fraction | SD300B | 490/500 (98.0000%) | 493/500 (98.6000%) | 3/500 = +0.6000 pp | same attempts on both sides |
| SELF eligibility fraction | SD300C | 491/500 (98.2000%) | 492/500 (98.4000%) | 1/500 = +0.2000 pp | same attempts on both sides |
| SELF eligibility fraction | pooled | 1468/1500 (97.8667%) | 1472/1500 (98.1333%) | 1/375 = +0.2667 pp | same attempts on both sides |
| Unconditional mated attempt non-success fraction | SD300A | 164/500 (32.8000%) | 164/500 (32.8000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Unconditional mated attempt non-success fraction | SD300B | 157/500 (31.4000%) | 176/500 (35.2000%) | 19/500 = +3.8000 pp | same attempts on both sides |
| Unconditional mated attempt non-success fraction | SD300C | 171/500 (34.2000%) | 181/500 (36.2000%) | 1/50 = +2.0000 pp | same attempts on both sides |
| Unconditional mated attempt non-success fraction | pooled | 492/1500 (32.8000%) | 521/1500 (34.7333%) | 29/1500 = +1.9333 pp | same attempts on both sides |
| Unconditional mated decision FNMR | SD300A | 164/500 (32.8000%) | 164/500 (32.8000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Unconditional mated decision FNMR | SD300B | 157/500 (31.4000%) | 176/500 (35.2000%) | 19/500 = +3.8000 pp | same attempts on both sides |
| Unconditional mated decision FNMR | SD300C | 171/500 (34.2000%) | 181/500 (36.2000%) | 1/50 = +2.0000 pp | same attempts on both sides |
| Unconditional mated decision FNMR | pooled | 492/1500 (32.8000%) | 521/1500 (34.7333%) | 29/1500 = +1.9333 pp | same attempts on both sides |
| Negative-sanity attempt match fraction | SD300A | 0/500 (0.0000%) | 0/500 (0.0000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Negative-sanity attempt match fraction | SD300B | 1/500 (0.2000%) | 1/500 (0.2000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Negative-sanity attempt match fraction | SD300C | 1/500 (0.2000%) | 0/500 (0.0000%) | -1/500 = -0.2000 pp | same attempts on both sides |
| Negative-sanity attempt match fraction | pooled | 2/1500 (0.1333%) | 1/1500 (0.0667%) | -1/1500 = -0.0667 pp | same attempts on both sides |
| Common-eligible selection fraction | SD300A | 487/500 (97.4000%) | 487/500 (97.4000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Common-eligible selection fraction | SD300B | 490/500 (98.0000%) | 490/500 (98.0000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Common-eligible selection fraction | SD300C | 491/500 (98.2000%) | 491/500 (98.2000%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Common-eligible selection fraction | pooled | 1468/1500 (97.8667%) | 1468/1500 (97.8667%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Common-eligible mated attempt non-success fraction | SD300A | 151/487 (31.0062%) | 151/487 (31.0062%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Common-eligible mated attempt non-success fraction | SD300B | 147/490 (30.0000%) | 166/490 (33.8776%) | 19/490 = +3.8776 pp | same attempts on both sides |
| Common-eligible mated attempt non-success fraction | SD300C | 162/491 (32.9939%) | 172/491 (35.0305%) | 10/491 = +2.0367 pp | same attempts on both sides |
| Common-eligible mated attempt non-success fraction | pooled | 460/1468 (31.3351%) | 489/1468 (33.3106%) | 29/1468 = +1.9755 pp | same attempts on both sides |
| Common-eligible mated decision FNMR | SD300A | 151/487 (31.0062%) | 151/487 (31.0062%) | 0/1 = 0.0000 pp | same attempts on both sides |
| Common-eligible mated decision FNMR | SD300B | 147/490 (30.0000%) | 166/490 (33.8776%) | 19/490 = +3.8776 pp | same attempts on both sides |
| Common-eligible mated decision FNMR | SD300C | 162/491 (32.9939%) | 172/491 (35.0305%) | 10/491 = +2.0367 pp | same attempts on both sides |
| Common-eligible mated decision FNMR | pooled | 460/1468 (31.3351%) | 489/1468 (33.3106%) | 29/1468 = +1.9755 pp | same attempts on both sides |
| Per-run conditional mated decision FNMR (different selections) | SD300A | 151/487 (31.0062%) | 151/487 (31.0062%) | not comparable | different selections; no difference is computed |
| Per-run conditional mated decision FNMR (different selections) | SD300B | 147/490 (30.0000%) | 169/493 (34.2799%) | not comparable | different selections; no difference is computed |
| Per-run conditional mated decision FNMR (different selections) | SD300C | 162/491 (32.9939%) | 173/492 (35.1626%) | not comparable | different selections; no difference is computed |
| Per-run conditional mated decision FNMR (different selections) | pooled | 460/1468 (31.3351%) | 493/1472 (33.4918%) | not comparable | different selections; no difference is computed |

## 13. Limitations

- One cohort of 50 subjects, one dataset, one algorithm, one threshold.
- The threshold was transferred unchanged from SourceAFIS's own documentation. Nothing here is calibrated, and no alternative threshold was tried.
- No confidence interval, no significance test, no bootstrap and no McNemar test. The machinery behind each of them is absent, deliberately.
- The negative set is closed-set and same-subject. It is a sanity check and is not a false-match rate of any kind.
- The canonical path changes the whole preparation pipeline, not only the resolution.

## 14. What this comparison does not establish

- That 500 ppi is better or worse than 1000 or 2000 ppi.
- That downsampling improves or harms the algorithm.
- That resolution caused any observed difference.
- That SourceAFIS is more accurate on either path.
- That any observed difference is statistically significant.
- Any general or population false-match rate.

Total paired comparisons: 6000. Eligibility units: 1500. Common-eligible mated rows: 1468.
