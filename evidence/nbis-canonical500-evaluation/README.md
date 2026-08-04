# NBIS canonical 500 ppi evaluation

The 6,000 NBIS decisions counted into fourteen metrics, under the same policy
file both SourceAFIS evaluations used.

## What the receipt proves

That fourteen named metrics were computed over one exact decision set, one exact
eligibility set and three exact evaluation views, under
`configs/metrics/plain_roll_biometric_metrics_v1.yaml` — the same file, cited by
the same path, as the native and canonical SourceAFIS evaluations.

There is no NBIS copy of that policy. A copy would be a second place for a
denominator to live and a second chance for the two chains to stop counting the
same thing, which is the one failure a cross-algorithm comparison cannot survive.

Fourteen metrics for SD300A, SD300B, SD300C and pooled: **56 observations**. The
evaluation config declares the number, so a metric silently added or a release
silently dropped fails before anything is published.

## What the numbers are, and are not

They are observed counts under one documented, uncalibrated threshold, on one
closed cohort of 50 subjects, at one image preparation.

They are not estimates of population performance. There is no confidence
interval, no bootstrap and no significance test, because there is no sampling
design that would justify one.

The same-subject different-finger set is **not a false-match rate**. It is a
closed set built by one fixed cyclic pairing, chosen for sanity rather than for
estimation. The metric policy carries `label_as_fmr: false` and the loader
refuses the file if it is ever true (docs/adr/0030).

Nothing was calibrated, and the threshold is NIST's own rule of thumb rather than
an operating point with a measured error rate (docs/adr/0057).

## Attempt rates and decided rates

Both are reported for every stage, always. When nothing fails they are
numerically identical, which is exactly why they are kept apart: a single blended
number would start moving the day something did fail, for reasons nobody could
name from the number (docs/adr/0027).

Pooled numbers sum the release numerators, sum the release denominators and
divide once. They never average the three percentages (docs/adr/0028).

## Files

```text
<metric_set_id>.json          the sanitised receipt
<metric_set_id>.md            the rendered report
evaluation-finalization.json  the last-written marker
```

The finalization marker is published here and not in the SourceAFIS evaluation
directories because the cross-algorithm comparison binds it by fingerprint, and a
reader should be able to check that without opening a workspace.

The full method note is in `docs/experiments/nbis-canonical500-evaluation.md`.
