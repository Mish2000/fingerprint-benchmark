# Metric policy `plain_roll_biometric_metrics_v1`

The policy that turns 6,000 decisions into fourteen published numbers, and the
reasoning behind each of its refusals.

Configuration: [`configs/metrics/plain_roll_biometric_metrics_v1.yaml`](../../configs/metrics/plain_roll_biometric_metrics_v1.yaml)
Catalogue: `fpbench.metrics.policy.METRIC_CATALOGUE`

## What the file can and cannot do

The policy file **selects** metrics from a catalogue fixed in code. It cannot define one.

That asymmetry is the whole design. A threshold is a number somebody chooses, and it
belongs in configuration. `plain_roll_mated_conditional_fnmr_decided` is a *definition* —
"included mated non-matches over included mated decided attempts" — and a definition
assembled at load time from YAML fragments is a definition that can be quietly re-pointed
at a different denominator, producing a different measurement under an unchanged name.

So the file has boolean switches and nothing else. An unrecognised switch is an error
rather than a shrug: a typo that silently computed one metric fewer is exactly the class
of failure this stage exists to make impossible.

## The fourteen metrics

Every metric names a numerator, a denominator, and the count family it reads. All three
reach the policy fingerprint.

### SELF

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `plain_self_match_rate_decided` | `MATCH` | `DECIDED_ATTEMPTS` |
| `plain_self_match_rate_attempt` | `MATCH` | `ALL_ATTEMPTS` |
| `roll_self_match_rate_decided` | `MATCH` | `DECIDED_ATTEMPTS` |
| `roll_self_match_rate_attempt` | `MATCH` | `ALL_ATTEMPTS` |

The difference between the two denominators is exactly the number of comparisons that
produced no score. See [ADR 0027](../adr/0027-attempt-and-decided-rates-are-separate.md).

### Eligibility

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `self_eligibility_rate` | `ELIGIBLE` | `ALL_ELIGIBILITY_UNITS` |
| `self_ineligible_rate` | `INELIGIBLE` | `ALL_ELIGIBILITY_UNITS` |
| `self_undetermined_rate` | `UNDETERMINED` | `ALL_ELIGIBILITY_UNITS` |

Three-valued throughout. An eligibility rate published without both exclusion categories
invites the reader to assume the remainder failed; some of it was merely never measured.

### Unconditional genuine

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `plain_roll_mated_unconditional_fnmr_decided` | `NON_MATCH` | `DECIDED_ATTEMPTS` |
| `plain_roll_mated_unconditional_non_success_rate_attempt` | `NON_SUCCESS` | `ALL_ATTEMPTS` |

`NON_SUCCESS` is `NON_MATCH + UNDECIDABLE` and is defined nowhere else. The second metric
is deliberately **not** called an FNMR: it is an operational rate that includes
comparisons the matcher never got to answer.

### SELF-conditional genuine

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `plain_roll_mated_conditional_selection_rate` | `INCLUDED` | `ALL_ATTEMPTS` |
| `plain_roll_mated_conditional_fnmr_decided` | `NON_MATCH` | `DECIDED_CONDITIONAL_ATTEMPTS` |
| `plain_roll_mated_conditional_non_success_rate_attempt` | `NON_SUCCESS` | `INCLUDED_CONDITIONAL_ATTEMPTS` |

The selection rate is the only denominator in the stage that spans excluded rows, and it
is mandatory: a conditional result without it is uninterpretable
([ADR 0029](../adr/0029-conditional-results-must-report-selection.md)). Outcome
numerators over this family always mean the *included* outcome — an excluded row's
outcome would otherwise land in a numerator whose denominator excludes it.

### Negative sanity

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `plain_roll_non_mated_sanity_match_rate_decided` | `MATCH` | `DECIDED_ATTEMPTS` |
| `plain_roll_non_mated_sanity_match_rate_attempt` | `MATCH` | `ALL_ATTEMPTS` |

Both ids contain `sanity`. Both definitions carry `prohibited_labels` naming the terms
they may not be presented under, and those labels are inside the policy fingerprint. This
is **not** a false-match rate
([ADR 0030](../adr/0030-negative-sanity-is-not-general-fmr.md)).

The policy also stores what the negative set *is*, so that a reader holding only
`metric-policy.json` does not have to follow a fingerprint to find out:

```yaml
negative_sanity_negative_kind:        same_subject_different_finger
negative_sanity_pairing_strategy:     cyclic_finger_shift
negative_sanity_closed_set:           "true"
negative_sanity_primary_fmr_estimate: "false"
negative_sanity_purpose:              negative_sanity_check
```

Stage 5A's view manifest carries the same facts and the metric set pins that view's
fingerprint, so the two cannot drift. Removing any of these keys changes the policy
fingerprint and therefore the metric-set id.

## What the policy refuses

Four refusals, each checked by the loader rather than documented and hoped for.

**`negative_sanity.label_as_fmr: true`** — refused. The impostor set is closed,
same-subject and cyclically paired.

**`mated_conditional.retain_exclusion_reasons: false`** — refused. A conditional result
without its exclusion counts cannot be read.

**`pooled_aggregation` other than `sum_counts_then_divide`** — refused. Pooled values sum
counts and divide once ([ADR 0028](../adr/0028-pooled-metrics-sum-counts.md)).

**`subject_weighting` other than `none`** — refused. Weighting subjects equally rather
than comparisons equally is a defensible and *different* metric; it needs its own policy
and its own ADR.

## Policy identity versus report rendering

The display block — `percentage_decimal_places`, `always_show_fraction`, `zero_format` —
is parsed from the policy file and is deliberately **outside** the policy fingerprint.

Rounding a percentage to five places instead of four changes how a report reads and
changes nothing about what was measured. If it changed the policy fingerprint it would
change the metric-set id, and every republication would look like a new result.

Those fields reach the [`ReportProfile`](../reports/sourceafis-native-first-evaluation.md)
fingerprint instead, which is what the manifest binds for rendering. That leaves them
unbound by the policy — so the metric-set store additionally requires the stored policy
and the stored report profile to *agree* about them. A divergence means one of the two
files was edited.

The verifier does not stop at that fingerprint agreement. It rebuilds the report profile,
summary identity and complete Markdown rendering from the verified run, decision profile,
source manifests, counts and observations, then requires the stored renderings to match.
A self-consistent edit to a displayed threshold or report sentence therefore remains
invalid even if every publication hash and the finalization marker are recomputed.

All integer fields entering this layer are strict JSON/YAML integers. Ordinals, count
components, manifest row totals, receipt pairs, expected-shape counts and percentage
precision reject floats, numeric strings, booleans and nulls rather than normalising them
before fingerprinting.

## Threshold provenance

Threshold 40 is **documented, not calibrated**. It is a number SourceAFIS's own authors
published, applied here unchanged
([ADR 0021](../adr/0021-decision-profiles-are-immutable-and-external.md)). The metric
engine has no code path that reads a raw score, scans thresholds, or recomputes a
decision — it counts decisions that stage 5A already derived and verified.
