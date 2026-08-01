# 0037 — The documented threshold transfers to canonical inputs unchanged

*Status: Accepted — 2026-08-01, stage 6B*

## Context

Deciding the canonical run needs a threshold. Three options were available.

Reuse the native profile. Impossible without weakening it: its scope names
`native_identity_60s_v1` and nothing else, deliberately, because a threshold is
chosen for images prepared a particular way (docs/adr/0021, docs/adr/0022).
Widening that scope would be exactly the quiet change the scope exists to
prevent.

Choose a new threshold for the canonical inputs. Defensible in isolation — 40 was
never claimed to be optimal for anything — and fatal for the comparison. The two
runs would then differ in the preparation path *and* in the threshold, and every
observed transition would be the sum of two effects with no way to separate them.

Transfer 40 unchanged into a new profile whose scope is the canonical execution
profile.

## Decision

The third. `sourceafis_java_3_18_1_documented_40_canonical500_v1` carries the
identical rule — `score >= 40`, origin `documented_native` — under a scope that
covers `canonical_500_lanczos3_60s_v1` and nothing else.

It also carries a `transfer` block:

```yaml
transfer:
  source_profile_id: sourceafis_java_3_18_1_documented_40_v1
  threshold_unchanged: true
  calibration_performed: false
  test_cohort_used: false
  interpretation: upstream_documented_threshold_transferred_to_canonical_inputs
```

Every field of that block lands in `metadata`, which is inside
`decision_profile_fingerprint`. So a transfer that started claiming a
calibration, pointed at a different source profile, or moved the number would be
a **different profile with a different fingerprint**, and every decision derived
under it would be visibly a different decision set.

The loader enforces the block's meaning rather than merely recording it:
`threshold_unchanged: false` is refused as "not a transfer", and either
calibration flag being true is refused outright.

## Consequences

The sentence the canonical report has to be able to say is true: *the threshold
of 40 was transferred without change in order to isolate the effect of image
preparation*. It may not say "recommended canonical threshold", "threshold
adapted to 500 ppi", "validated on SD300" or "optimal", and there is no code path
that could make any of those true.

40 remains what it always was: a number SourceAFIS's authors published, with a
traceable origin, that this project has not calibrated and does not endorse. A
calibrated profile still needs a development cohort, and the 50 test subjects
still may not supply one.

The comparison is a comparison of one variable, which is the only reason its
numbers can be attributed to anything.

## Alternatives considered

**Widen the native profile's scope.** Would delete the mechanism that makes
threshold transfer visible at all.

**Calibrate for the canonical path.** Would need a development cohort that does
not exist, and would make the paired comparison uninterpretable even if it did.
