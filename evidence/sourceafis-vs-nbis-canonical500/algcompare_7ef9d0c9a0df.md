# sourceafis and nbis at their documented operating points

> This comparison uses independently documented, uncalibrated operating points on identical inputs. It records paired observed outcomes. It does not establish equal FMR, general algorithm superiority, causality, or statistical significance.

- comparison: `algcompare_7ef9d0c9a0df`
- protocol: `stage7d_fair_measurement_protocol_v1` (`ac212d9893a4...`)
- operating-point relation: `independently_documented_not_equated`
- left = `sourceafis`, right = `nbis`; every difference is right minus left
- alignment: `d25b52159d25...` (stage 7C, re-verified)
- pairs: `ee4d942e23cd...`, 6000 compared
- fair-comparability audit: `4b36dcf753c3...`, clean

## The two operating points

| side | algorithm | rule | origin |
| --- | --- | --- | --- |
| left | `sourceafis` | documented | `documented_native` |
| right | `nbis` | documented | `documented_native` |

Both thresholds are written `40`. They come from two documents about two score scales and are not the same operating point; no claim of equal false-match rate, equal security level or equivalent threshold is made or implied.

## A. Full mated population - the primary analysis

All 1,500 mated PLAIN-ROLL attempts, the same denominator on both sides, nothing filtered. `NON_MATCH` and `UNDECIDABLE` are both counted as non-successes.

| metric | scope | sourceafis | nbis | right - left |
| --- | --- | --- | --- | --- |
| mated non-success rate (all 1,500 attempts) - PRIMARY | SD300A | 164/500 = 32.8000% | 199/500 = 39.8000% | 7/100 = +7.0000 pp |
| mated non-success rate (all 1,500 attempts) - PRIMARY | SD300B | 176/500 = 35.2000% | 196/500 = 39.2000% | 1/25 = +4.0000 pp |
| mated non-success rate (all 1,500 attempts) - PRIMARY | SD300C | 181/500 = 36.2000% | 200/500 = 40.0000% | 19/500 = +3.8000 pp |
| mated non-success rate (all 1,500 attempts) - PRIMARY | pooled | 521/1500 = 34.7333% | 595/1500 = 39.6667% | 37/750 = +4.9333 pp |
| mated FNMR (decided attempts only) | SD300A | 164/500 = 32.8000% | 199/500 = 39.8000% | 7/100 = +7.0000 pp |
| mated FNMR (decided attempts only) | SD300B | 176/500 = 35.2000% | 196/500 = 39.2000% | 1/25 = +4.0000 pp |
| mated FNMR (decided attempts only) | SD300C | 181/500 = 36.2000% | 200/500 = 40.0000% | 19/500 = +3.8000 pp |
| mated FNMR (decided attempts only) | pooled | 521/1500 = 34.7333% | 595/1500 = 39.6667% | 37/750 = +4.9333 pp |

## B. Eligibility and exclusions

1500 eligibility units, one per release, subject and finger.

### Eligibility transitions (sourceafis to nbis, pooled)

| sourceafis \ nbis | eligible | ineligible | undetermined |
| --- | --- | --- | --- |
| eligible | 1472 | 0 | 0 |
| ineligible | 26 | 2 | 0 |
| undetermined | 0 | 0 | 0 |

| metric | scope | sourceafis | nbis | right - left |
| --- | --- | --- | --- | --- |
| eligible units selected (of all units) | SD300A | 487/500 = 97.4000% | 498/500 = 99.6000% | 11/500 = +2.2000 pp |
| eligible units selected (of all units) | SD300B | 493/500 = 98.6000% | 500/500 = 100.0000% | 7/500 = +1.4000 pp |
| eligible units selected (of all units) | SD300C | 492/500 = 98.4000% | 500/500 = 100.0000% | 2/125 = +1.6000 pp |
| eligible units selected (of all units) | pooled | 1472/1500 = 98.1333% | 1498/1500 = 99.8667% | 13/750 = +1.7333 pp |

## C. Common eligible - a controlled secondary analysis

1472 units are ELIGIBLE on both sides. This set filters out exactly the units that were hard for either algorithm, so it answers a narrower question than section A: when both algorithms have shown that a finger's plain and rolled impressions match themselves, how did the plain-to-rolled decisions differ? It is not the primary result.

| metric | scope | sourceafis | nbis | right - left |
| --- | --- | --- | --- | --- |
| non-success rate over the common eligible set | SD300A | 151/487 = 31.0062% | 187/487 = 38.3984% | 36/487 = +7.3922 pp |
| non-success rate over the common eligible set | SD300B | 169/493 = 34.2799% | 189/493 = 38.3367% | 20/493 = +4.0568 pp |
| non-success rate over the common eligible set | SD300C | 173/492 = 35.1626% | 192/492 = 39.0244% | 19/492 = +3.8618 pp |
| non-success rate over the common eligible set | pooled | 493/1472 = 33.4918% | 568/1472 = 38.5870% | 75/1472 = +5.0951 pp |
| FNMR over the common eligible set (decided only) | SD300A | 151/487 = 31.0062% | 187/487 = 38.3984% | 36/487 = +7.3922 pp |
| FNMR over the common eligible set (decided only) | SD300B | 169/493 = 34.2799% | 189/493 = 38.3367% | 20/493 = +4.0568 pp |
| FNMR over the common eligible set (decided only) | SD300C | 173/492 = 35.1626% | 192/492 = 39.0244% | 19/492 = +3.8618 pp |
| FNMR over the common eligible set (decided only) | pooled | 493/1472 = 33.4918% | 568/1472 = 38.5870% | 75/1472 = +5.0951 pp |

## D. Each side's own conditional set - descriptive only

Each algorithm's conditional rates over *its own* eligible set. Where the two eligible sets differ these are two measurements over two populations and their difference is undefined; the table says so rather than subtracting them.

| metric | scope | sourceafis | nbis | right - left |
| --- | --- | --- | --- | --- |
| conditional non-success rate over each side's own eligible set | SD300A | 151/487 = 31.0062% | 197/498 = 39.5582% | - (different eligible populations - difference undefined) |
| conditional non-success rate over each side's own eligible set | SD300B | 169/493 = 34.2799% | 196/500 = 39.2000% | - (different eligible populations - difference undefined) |
| conditional non-success rate over each side's own eligible set | SD300C | 173/492 = 35.1626% | 200/500 = 40.0000% | - (different eligible populations - difference undefined) |
| conditional non-success rate over each side's own eligible set | pooled | 493/1472 = 33.4918% | 593/1498 = 39.5861% | - (different eligible populations - difference undefined) |
| conditional FNMR over each side's own eligible set | SD300A | 151/487 = 31.0062% | 197/498 = 39.5582% | - (different eligible populations - difference undefined) |
| conditional FNMR over each side's own eligible set | SD300B | 169/493 = 34.2799% | 196/500 = 39.2000% | - (different eligible populations - difference undefined) |
| conditional FNMR over each side's own eligible set | SD300C | 173/492 = 35.1626% | 200/500 = 40.0000% | - (different eligible populations - difference undefined) |
| conditional FNMR over each side's own eligible set | pooled | 493/1472 = 33.4918% | 593/1498 = 39.5861% | - (different eligible populations - difference undefined) |

## SELF comparisons

PLAIN and ROLL are reported separately. The all-attempt denominator is 1,500 on both sides and is directly comparable; the decided-only rates are comparable only where both sides decided the same attempts.

| metric | scope | sourceafis | nbis | right - left |
| --- | --- | --- | --- | --- |
| PLAIN SELF match rate (all attempts) | SD300A | 487/500 = 97.4000% | 498/500 = 99.6000% | 11/500 = +2.2000 pp |
| PLAIN SELF match rate (all attempts) | SD300B | 493/500 = 98.6000% | 500/500 = 100.0000% | 7/500 = +1.4000 pp |
| PLAIN SELF match rate (all attempts) | SD300C | 492/500 = 98.4000% | 500/500 = 100.0000% | 2/125 = +1.6000 pp |
| PLAIN SELF match rate (all attempts) | pooled | 1472/1500 = 98.1333% | 1498/1500 = 99.8667% | 13/750 = +1.7333 pp |
| PLAIN SELF match rate (decided only) | SD300A | 487/500 = 97.4000% | 498/500 = 99.6000% | 11/500 = +2.2000 pp |
| PLAIN SELF match rate (decided only) | SD300B | 493/500 = 98.6000% | 500/500 = 100.0000% | 7/500 = +1.4000 pp |
| PLAIN SELF match rate (decided only) | SD300C | 492/500 = 98.4000% | 500/500 = 100.0000% | 2/125 = +1.6000 pp |
| PLAIN SELF match rate (decided only) | pooled | 1472/1500 = 98.1333% | 1498/1500 = 99.8667% | 13/750 = +1.7333 pp |
| ROLL SELF match rate (all attempts) | SD300A | 500/500 = 100.0000% | 500/500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (all attempts) | SD300B | 500/500 = 100.0000% | 500/500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (all attempts) | SD300C | 500/500 = 100.0000% | 500/500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (all attempts) | pooled | 1500/1500 = 100.0000% | 1500/1500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (decided only) | SD300A | 500/500 = 100.0000% | 500/500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (decided only) | SD300B | 500/500 = 100.0000% | 500/500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (decided only) | SD300C | 500/500 = 100.0000% | 500/500 = 100.0000% | 0/1 = +0.0000 pp |
| ROLL SELF match rate (decided only) | pooled | 1500/1500 = 100.0000% | 1500/1500 = 100.0000% | 0/1 = +0.0000 pp |

## Negative sanity set - not a false-match rate

The same 1,500 same-subject, different-finger pairs on both sides, built by one fixed cyclic pairing. It is a closed set chosen for sanity rather than for estimation: it is not an FMR, not a false-match-rate estimate, and not a statement about impostor population performance.

| metric | scope | sourceafis | nbis | right - left |
| --- | --- | --- | --- | --- |
| same-subject sanity match rate (all attempts) - NOT an FMR | SD300A | 0/500 = 0.0000% | 0/500 = 0.0000% | 0/1 = +0.0000 pp |
| same-subject sanity match rate (all attempts) - NOT an FMR | SD300B | 1/500 = 0.2000% | 0/500 = 0.0000% | -1/500 = -0.2000 pp |
| same-subject sanity match rate (all attempts) - NOT an FMR | SD300C | 0/500 = 0.0000% | 0/500 = 0.0000% | 0/1 = +0.0000 pp |
| same-subject sanity match rate (all attempts) - NOT an FMR | pooled | 1/1500 = 0.0667% | 0/1500 = 0.0000% | -1/1500 = -0.0667 pp |
| same-subject sanity match rate (decided only) - NOT an FMR | SD300A | 0/500 = 0.0000% | 0/500 = 0.0000% | 0/1 = +0.0000 pp |
| same-subject sanity match rate (decided only) - NOT an FMR | SD300B | 1/500 = 0.2000% | 0/500 = 0.0000% | -1/500 = -0.2000 pp |
| same-subject sanity match rate (decided only) - NOT an FMR | SD300C | 0/500 = 0.0000% | 0/500 = 0.0000% | 0/1 = +0.0000 pp |
| same-subject sanity match rate (decided only) - NOT an FMR | pooled | 1/1500 = 0.0667% | 0/1500 = 0.0000% | -1/1500 = -0.0667 pp |

## Decision transition matrices

Every matrix carries all nine cells, including the zeros. Rows are the `sourceafis` outcome, columns the `nbis` outcome.

### PLAIN SELF

| sourceafis \ nbis | match | non_match | undecidable |
| --- | --- | --- | --- |
| match | 1472 | 0 | 0 |
| non_match | 26 | 2 | 0 |
| undecidable | 0 | 0 | 0 |

### ROLL SELF

| sourceafis \ nbis | match | non_match | undecidable |
| --- | --- | --- | --- |
| match | 1500 | 0 | 0 |
| non_match | 0 | 0 | 0 |
| undecidable | 0 | 0 | 0 |

### mated PLAIN-ROLL, all attempts

| sourceafis \ nbis | match | non_match | undecidable |
| --- | --- | --- | --- |
| match | 767 | 212 | 0 |
| non_match | 138 | 383 | 0 |
| undecidable | 0 | 0 | 0 |

### mated PLAIN-ROLL, common eligible only

| sourceafis \ nbis | match | non_match | undecidable |
| --- | --- | --- | --- |
| match | 767 | 212 | 0 |
| non_match | 137 | 356 | 0 |
| undecidable | 0 | 0 | 0 |

### same-subject different-finger sanity set

| sourceafis \ nbis | match | non_match | undecidable |
| --- | --- | --- | --- |
| match | 0 | 1 | 0 |
| non_match | 0 | 1499 | 0 |
| undecidable | 0 | 0 | 0 |

## What this comparison does not establish

This comparison uses independently documented, uncalibrated operating points on identical inputs. It records paired observed outcomes. It does not establish equal FMR, general algorithm superiority, causality, or statistical significance.

No threshold was calibrated. No SD300 score was read in order to choose one. No raw score was compared, normalised, subtracted or correlated across the two algorithms. No confidence interval and no significance test was computed.

