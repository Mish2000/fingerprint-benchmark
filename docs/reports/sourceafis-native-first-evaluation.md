# The first SourceAFIS evaluation, and how to read it

Metric set `metricset_3a10972a121d`, over decision set `decisionset_0122544e71b1`,
over run `run_7ac1cecc0bb3`.

Report: [`evidence/sourceafis-native-evaluation/metricset_3a10972a121d.md`](../../evidence/sourceafis-native-evaluation/metricset_3a10972a121d.md)
Receipt: [`evidence/sourceafis-native-evaluation/metricset_3a10972a121d.json`](../../evidence/sourceafis-native-evaluation/metricset_3a10972a121d.json)

This document is about how to read that report. The report itself carries the numbers
and their caveats; what follows is the reasoning a reader needs and the mistakes the
numbers invite.

## What was measured

SourceAFIS for Java 3.18.1, at each release's native resolution, over 50 subjects and ten
fingers in three SD300 releases. 6,000 comparisons, all of which produced a score. One
threshold: 40, which SourceAFIS's own authors document.

Five populations, each reported per release and pooled:

| Population | Size | Result |
| --- | --- | --- |
| PLAIN SELF | 1,500 | 1,468 matched |
| ROLL SELF | 1,500 | 1,500 matched |
| SELF eligibility | 1,500 units | 1,468 eligible, 32 ineligible, 0 undetermined |
| Mated PLAIN–ROLL, unconditional | 1,500 | 492 non-matches |
| Mated PLAIN–ROLL, SELF-conditional | 1,468 included of 1,500 | 460 non-matches |
| Same-subject different-finger sanity | 1,500 | 2 matches |

Nothing failed. All 6,000 comparisons produced a score, so every decided rate equals its
attempt-level counterpart, and the report says so rather than merging them.

## Seven things this does not establish

### The threshold is documented, not calibrated

40 is a number SourceAFIS's authors published about their own evaluation on their own
data. It was applied here unchanged, and no other threshold was tried. There is no code
path in the metric engine that reads a raw score, scans thresholds, or recomputes a
decision — it counts decisions stage 5A already derived and verified.

A calibrated threshold will come from a *development* cohort, which does not exist yet,
and never from the 50 test subjects these results are reported over
([ADR 0021](../adr/0021-decision-profiles-are-immutable-and-external.md)).

**In particular, the mated non-match fraction of 492/1500 is a result about threshold 40,
not about SourceAFIS.** A different threshold would produce a different number from the
same 6,000 scores, at no cost, which is exactly why re-thresholding was kept free
([ADR 0003](../adr/0003-decision-outside-adapter.md)).

### Decision FNMR and attempt non-success are different metrics

They are numerically identical here because nothing failed. They are reported separately
anyway, because the day an extraction fails, one denominator changes and the other does
not, and a single blended number would move for reasons nobody could name from the number
([ADR 0027](../adr/0027-attempt-and-decided-rates-are-separate.md)).

The report's operational section prints the undecidable counts — all zero — so a reader
can see the two rates coincide *because nothing failed* rather than because they are the
same metric.

### The conditional result covers a different population

`460/1468` is not `492/1500` improved. It is a different measurement over 1,468 of the
1,500 mated comparisons, chosen by a rule that removes exactly the fingers most likely to
fail: those that did not match themselves.

That is why the selection rate is a published metric rather than context. A conditional
result whose selection fraction is missing is a knob that makes any matcher look
arbitrarily good ([ADR 0029](../adr/0029-conditional-results-must-report-selection.md)).
Both exclusion categories are published too — ineligible (a measured SELF failure) and
undetermined (a SELF comparison that produced no score) — because collapsing them would
report an absent measurement as a failure.

### The sanity fraction is not a false-match rate

2/1500 is an observed count in a closed-set, same-subject, different-finger check at one
fixed cyclic pairing. It is not an FMR, cannot be converted into one by dividing, and must
not be presented as one ([ADR 0030](../adr/0030-negative-sanity-is-not-general-fmr.md)).

The set is closed (fifty people, chosen once), both sides come from one subject, and only
one of the many available negative pairings was used. A real false-match rate needs a
cross-subject negative design chosen for estimation — a different pair manifest and a
different run.

What the two matches *are* good for: they are worth investigating. A non-zero count in
this check is the signal it exists to produce.

### Pooled values are sums, not averages

Every pooled row is the sum of the three release numerators over the sum of the three
release denominators. It is not `(rate_A + rate_B + rate_C) / 3`.

The two agree here, because each release contributes exactly 500 comparisons. That is a
fact about this pair manifest and not a property of anything, and the code computes the
sum regardless ([ADR 0028](../adr/0028-pooled-metrics-sum-counts.md)).

### There are no intervals

No confidence interval, no standard error, no bootstrap, no significance test. The design
was not chosen for estimation, and the machinery does not exist. A reader who wants to
know whether SD300A's 164/500 differs meaningfully from SD300B's 157/500 will not find an
answer here, and should not construct one from these numbers.

### There is no resolution finding

The three releases are reported side by side. Nothing is claimed about the difference
between them. They differ in more than capture resolution, no significance test was
performed, and none would be valid on this design.

## How to check it

```bash
python -m fpbench.experiments.sourceafis_native_evaluation status
```

`EVALUATION_READY` means every link still holds. Specifically, the verifier re-derives:

1. that the source derivation is still `DECISION_READY`;
2. the definition, policy and report-profile fingerprints;
3. all 24 count records, recomputed from the decisions, the eligibility set and the three
   views — not compared against themselves;
4. every numerator and denominator, re-resolved from its enum against the stored counts;
5. every fraction, from the two integers;
6. every pooled value, against the sum of its releases;
7. all 56 observation hashes, the two ordered hashes, and the metric-set fingerprint.

A metric set is not evidence of itself. Any broken link reports `INVALID` rather than
degrading quietly.

```bash
python -m fpbench.experiments.sourceafis_native_evaluation show
```

prints the verified report, and refuses to print anything from a chain that is not
`EVALUATION_READY`.

## Three commits, three questions

The report's identity table names three commits, and they answer three different
questions:

| Commit | Question |
| --- | --- |
| Run source commit | Which code ran the 6,000 comparisons? |
| Decision derivation commit | Which code applied threshold 40 to their scores? |
| Metric derivation commit | Which code counted the results? |

They are frequently not the same, and a report that printed one of them would invite the
reader to assume all three ([ADR 0017](../adr/0017-research-runs-pin-fpbench-source-revision.md)).

## Further reading

* [Metric policy `plain_roll_biometric_metrics_v1`](../metrics/metric-policy-v1.md) — the
  fourteen metrics and the four refusals.
* [Denominator semantics](../metrics/denominator-semantics.md) — what each of the five
  denominators covers, and why a metric may not choose freely.
* [SELF eligibility](../evaluation/self-eligibility.md) — how the 1,468 eligible units
  were determined.
* [The three evaluation views](../evaluation/plain-roll-views.md) — which comparisons
  belong to which evaluation, fixed in stage 5A before any number depended on it.
