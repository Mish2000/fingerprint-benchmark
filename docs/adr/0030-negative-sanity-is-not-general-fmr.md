# 0030 — The cyclic negative set is reported as an observed fraction, never as an FMR

## Status

Accepted. Implemented in `fpbench.metrics.policy` (metric ids and prohibited labels),
`require_honest_metric_id`, and the report's section 8.

## Context

[ADR 0025](0025-same-subject-different-finger-is-a-sanity-check.md) established that the
same-subject different-finger set is a sanity check and not a false-match-rate
experiment, and enforced that at the level of *names*: no view or policy id may contain
`fmr`, `population` or `accuracy`.

Stage 5B is where the temptation becomes concrete, because the stage's job is to divide
things. The sanity set is 1,500 non-mated comparisons with decisions attached. Dividing
the matches by the total produces a number. The number is a fraction of impostor
comparisons that matched. It looks exactly like an FMR, it will be read as one, and it is
wrong as one for reasons that are invisible from the number itself:

* **Closed set.** Fifty subjects, chosen once. An FMR is a statement about a population.
* **Same subject on both sides.** Impostor comparisons within one person are not
  representative of impostor comparisons between people, and the literature disagrees
  about which way the bias runs.
* **One fixed pairing.** Finger *i* against finger *i+1*, one shift, one direction — not
  the 4,500 available negative pairings and not a sample of them.
* **No interval is possible.** The design was not chosen for estimation.

There is a further, specific hazard that only appears once the number exists. The
expected answer is zero. A zero result invites the two worst possible sentences in
biometrics: "the algorithm produced no false matches" and "the false-match rate was
zero". The first is an unbounded claim from a bounded observation. The second states a
probability of zero, which no finite sample can support.

## Decision

**The sanity fraction is published as an observed count over a named population, in fixed
wording, and is never labelled a rate.**

Four enforcement points, because names, labels, prose and configuration all travel
separately.

*Metric ids.* `plain_roll_non_mated_sanity_match_rate_decided` and
`..._attempt`. The word `sanity` is in both. `require_honest_metric_id` refuses any id
containing `general_fmr`, `population_fmr`, `impostor_fmr` or `overall_fmr`.

*Definitions.* Both metrics carry `prohibited_labels` naming the terms they may not be
presented under, and those labels reach the metric policy fingerprint. Removing the
refusal changes the metric set's identity.

*Configuration.* `negative_sanity.label_as_fmr: false` is in the policy file, and the
loader refuses the file outright if it is ever true.

*Prose.* The report's section 8 uses fixed wording. Non-zero:

```
Observed matches in the closed-set same-subject different-finger negative
sanity check: 1/1500.
```

Zero:

```
Observed 0/1500 matching decisions in this sanity set.
```

Never "FMR was zero", never "the algorithm produced no false matches", never "the true
false-match probability is zero". The section then states, in the report itself rather
than in this document, that the set is closed, same-subject and single-pairing, and that
the fraction must not be presented as a general false-match rate.

**The refusal is not tested by grepping for `FMR`.** The report is *supposed* to contain
the sentence "This is not a general false-match rate estimate", and a blunt substring
assertion would force that sentence out of the document to keep the suite green — the
exact opposite of the intent. The tests match assertion *forms* instead: `FMR =`,
`FMR:`, `false-match rate = `.

**`NON_SUCCESS` is unavailable over this population.** Non-matches plus failures is the
honest attempt-level answer for a *mated* comparison. Over impostors it is not a quantity
anyone can interpret, and `resolve` refuses it.

## Alternatives

**Publish it as `non_mated_fmr` with a caveat.** This is the failure mode. Names travel;
caveats do not.

**Publish it as "preliminary FMR".** A preliminary number is a number.

**Do not publish the sanity result at all.** The check is genuinely useful — a non-zero
count is a red flag worth investigating immediately — and hiding a zero result would be
its own kind of dishonesty.

**Compute a real FMR from a proper negative design.** Wanted, and out of scope: it needs
a cross-subject negative-pair design chosen for estimation, which is a new pair manifest
and a new run.

## Consequences

* The stage publishes 1,500 impostor decisions and no false-match rate.
* A zero result is written `0/1500`, which is what was observed and all that was
  observed.
* A future FMR will arrive with its own pair manifest, its own run and its own ADR — and
  will not be able to reuse these metric ids, because they say `sanity`.
* Someone will still quote the fraction as an FMR. The report, the metric id and the
  receipt will each contradict them.
