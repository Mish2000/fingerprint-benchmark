# The SourceAFIS documented threshold of 40

`configs/decisions/sourceafis_java_3_18_1_documented_40_v1.yaml`

## What this threshold is

SourceAFIS's own documentation names 40 as a recommended threshold and attaches a claim
about the false-match rate its authors observed at that value. This project uses that
number as its **first** decision profile, because it has a traceable origin and needs no
calibration to be defensible as a starting point.

That is the whole claim. Forty is not "the right threshold for SD300", it is not a value
this project measured, and the upstream claim beneath it has not been verified here.

The profile records the distinction in a field that reaches its own fingerprint:

```yaml
origin: documented_native
provenance:
  source_kind: upstream_documentation
  source_reference: sourceafis_fingerprint_matcher_javadoc_3_18_1
  upstream_claim: approximate_fmr_0_0001
  upstream_claim_is_not_benchmark_result: true
calibration:
  performed: false
  test_cohort_used: false
```

So a profile cannot quietly change its story: presenting 40 as a calibrated threshold
would change `origin`, which changes the fingerprint, which changes every decision set
derived under it.

## The rule

```
score >= 40  → MATCH
score <  40  → NON_MATCH
```

A score of **exactly 40 is a MATCH**. There is no epsilon, no rounding before the
comparison, no clipping, and no normalisation. The threshold is stored as the canonical
decimal string `"40"` and compared in `Decimal`, so the boundary is decided by the rule
rather than by whichever parser saw the number last.

`"40.0"`, `"+40"` and `"4e1"` all canonicalise to `"40"` and produce the same profile
fingerprint. `NaN` and infinities are refused.

## What it applies to

```yaml
algorithm:
  algorithm_id: sourceafis_java
  implementation_version: "3.18.1"
  score_direction: higher_is_better
scope:
  execution_profiles:
    - native_identity_60s_v1
```

The profile is bound at load time to the **exact algorithm fingerprint** of the run it is
applied to. "Score 40 means match" is a claim about a specific matcher build, not about a
number, so the same threshold against a different jar is a different profile with a
different fingerprint.

The execution profile matters for the same reason: a threshold chosen for images at
native resolution does not automatically transfer to images resampled to 500 ppi. When
resampling arrives it will need its own entry, added deliberately.

Applying the profile to anything it does not describe raises
`DecisionProfileApplicabilityError`. There is no warn-and-continue.

## A failure is not a non-match

A comparison that produced no score cannot be thresholded. It becomes:

```
application_status = UNDECIDABLE
decision           = None
source_failure_code = <the code the run recorded>
```

There is no `NO_MATCH_DUE_TO_FAILURE`. Counting a crashed comparison as a non-match would
corrupt every denominator a later stage computes
([ADR 0006](../adr/0006-self-failure-semantics.md)).

For the current SD300 run this branch is unused: all 6,000 comparisons produced scores.
The code supports it because the next run may not.

## Calibration, and why there is none yet

`calibrated_development` is a valid origin that this stage refuses to execute. A
calibrated threshold needs a calibration manifest derived from a **development** cohort,
and neither exists.

What it must never be derived from is the TEST cohort — the same 50 subjects the results
are reported over. The loader refuses a config with `test_cohort_used: true` outright,
because that single line is the difference between a study and a self-fulfilling one.

## What a decision under this profile is not

It is not a performance measurement. Six thousand decisions under a documented threshold
tell you what that threshold does to those scores; turning that into FMR, FNMR, EER or an
accuracy figure needs failure denominators, SELF eligibility rules and a justification
for the threshold itself — none of which stage 5A provides
([ADR 0021](../adr/0021-decision-profiles-are-immutable-and-external.md)).
